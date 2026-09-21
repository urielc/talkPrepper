"""Keyword (FTS5), semantic (embeddings) and hybrid search over talks.

One ``SearchEngine`` is created per process; it lazily loads the chunk matrix
and the embedding model.
"""

from __future__ import annotations

import math
import re
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .config import CHUNKS_NPY, DEFAULT_EMBEDDING_MODEL
from . import db as dbm

STOPWORDS = set("""
a about above after again against all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have
having he her here hers herself him himself his how i if in into is it its itself just me more most
my myself no nor not now of off on once only or other our ours ourselves out over own same she should
so some such than that the their theirs them themselves then there these they this those through to
too under until up very was we were what when where which while who whom why will with would you your
yours yourself yourselves shall unto thou thee thy thine ye hath doth also may might must let us one
two three many much every even upon said says say like know knew think thought come came go went get
got make made take took give gave see saw seen way day days time times year years thing things
brothers sisters brethren dear friends today tonight talk conference general president elder sister
someone something anyone anything everyone everything nothing needed need needs fully really truly simply
often always never ever still yet already almost quite rather perhaps maybe others another each other
don't didn't doesn't won't wouldn't couldn't shouldn't can't cannot isn't aren't wasn't weren't i'm i've
you're we're they're it's that's there's here's let's who's what's he's she's
people person life lives world church gospel lord god jesus christ savior heavenly father spirit
saints members family families home children young youth men women man woman
""".split())

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@dataclass
class TalkHit:
    talk_id: str
    score: float
    snippets: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {"talk_id": self.talk_id, "score": round(self.score, 4),
                "snippets": self.snippets[:3], "sources": sorted(self.sources)}


def fts_query(q: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Quoted phrases are kept as phrases; other words become individual terms
    (implicit AND). FTS5 operators in the input are neutralised by quoting.
    """
    q = q.replace("“", '"').replace("”", '"')
    parts = []
    for phrase in re.findall(r'"([^"]+)"', q):
        parts.append('"' + phrase.replace('"', ' ') + '"')
    rest = re.sub(r'"[^"]+"', " ", q)
    for w in re.findall(r"[A-Za-z0-9’']+", rest):
        w = w.replace("'", "''").replace("’", "''")
        parts.append(f'"{w}"')
    return " ".join(parts)


def fts_or_query(terms: list[str]) -> str:
    # Each term is wrapped in double quotes, so a term containing one would close
    # the string early and the rest would be read as FTS5 syntax. Drop them.
    return " OR ".join(f'"{t}"' for t in (t.replace('"', " ").strip() for t in terms) if t)


class SearchEngine:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._lock = threading.Lock()
        self._matrix: np.ndarray | None = None
        self._chunk_talks: list[str] = []
        self._chunk_ids: list[int] = []
        self._model = None
        self._model_name = None

    # ------------------------------------------------------------ loading

    def reload(self) -> None:
        with self._lock:
            self._matrix = None
            self._chunk_talks = []
            self._chunk_ids = []

    def _ensure_matrix(self) -> bool:
        if self._matrix is not None:
            return True
        with self._lock:
            if self._matrix is not None:
                return True
            if not CHUNKS_NPY.exists():
                return False
            rows = self.conn.execute("SELECT id, talk_id FROM chunks ORDER BY id").fetchall()
            m = np.load(CHUNKS_NPY)
            if m.shape[0] != len(rows):
                return False
            self._chunk_ids = [r["id"] for r in rows]
            self._chunk_talks = [r["talk_id"] for r in rows]
            self._matrix = m
            return True

    @property
    def semantic_available(self) -> bool:
        return self._ensure_matrix()

    def _embedder(self):
        name = dbm.get_meta(self.conn, "embedding_model", DEFAULT_EMBEDDING_MODEL)
        if self._model is None or self._model_name != name:
            from .indexer import get_embedder
            self._model = get_embedder(name)
            self._model_name = name
        return self._model

    def embed_query(self, text: str) -> np.ndarray:
        v = self._embedder().encode([QUERY_PREFIX + text], normalize_embeddings=True,
                                    convert_to_numpy=True, show_progress_bar=False)[0]
        return v.astype(np.float32)

    # ------------------------------------------------------------ filters

    def _allowed_talks(self, years: tuple[int, int] | None, speaker: str | None,
                       conference: str | None) -> set[str] | None:
        if not years and not speaker and not conference:
            return None
        sql = "SELECT t.id FROM talks t JOIN conferences c ON c.id=t.conference_id WHERE 1=1"
        args: list = []
        if years:
            sql += " AND c.year BETWEEN ? AND ?"
            args += [years[0], years[1]]
        if speaker:
            sql += " AND t.speaker LIKE ?"
            args.append(f"%{speaker}%")
        if conference:
            sql += " AND c.id = ?"
            args.append(conference)
        return {r[0] for r in self.conn.execute(sql, args)}

    # ------------------------------------------------------------ keyword

    def keyword_search(self, q: str, limit: int = 20, allowed: set[str] | None = None,
                       per_talk_snippets: int = 2) -> list[TalkHit]:
        match = fts_query(q)
        if not match:
            return []
        hits = self._fts_paragraphs(match, limit, allowed, per_talk_snippets)
        if not hits:
            # Relax to OR when the AND query finds nothing.
            terms = re.findall(r"[A-Za-z0-9]+", q)
            terms = [t for t in terms if t.lower() not in STOPWORDS]
            if len(terms) > 1:
                hits = self._fts_paragraphs(fts_or_query(terms), limit, allowed, per_talk_snippets)
        return hits

    def _fts_paragraphs(self, match: str, limit: int, allowed: set[str] | None,
                        per_talk_snippets: int) -> list[TalkHit]:
        rows = self.conn.execute(
            "SELECT p.talk_id, bm25(paragraphs_fts) AS score, "
            "snippet(paragraphs_fts, 0, '<mark>', '</mark>', '…', 32) AS snip "
            "FROM paragraphs_fts JOIN paragraphs p ON p.id = paragraphs_fts.rowid "
            "WHERE paragraphs_fts MATCH ? ORDER BY score LIMIT ?",
            (match, max(limit * 12, 300)),
        ).fetchall()
        agg: dict[str, TalkHit] = {}
        for r in rows:
            tid = r["talk_id"]
            if allowed is not None and tid not in allowed:
                continue
            s = -float(r["score"])
            h = agg.get(tid)
            if h is None:
                h = agg[tid] = TalkHit(tid, 0.0, [], {"keyword"})
            # Sum of top paragraph scores with diminishing returns.
            h.score += s / (1 + 0.5 * len(h.snippets))
            if len(h.snippets) < per_talk_snippets:
                h.snippets.append(r["snip"])
        out = sorted(agg.values(), key=lambda h: -h.score)
        return out[:limit]

    # ------------------------------------------------------------ semantic

    def semantic_search_vec(self, qvec: np.ndarray, limit: int = 20,
                            allowed: set[str] | None = None, exclude: str | None = None,
                            per_talk_snippets: int = 2) -> list[TalkHit]:
        if not self._ensure_matrix():
            return []
        scores = self._matrix @ qvec
        k = min(len(scores), max(limit * 15, 400))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        agg: dict[str, TalkHit] = {}
        chunk_rows: list[int] = []
        for i in top:
            tid = self._chunk_talks[i]
            if tid == exclude or (allowed is not None and tid not in allowed):
                continue
            h = agg.get(tid)
            if h is None:
                h = agg[tid] = TalkHit(tid, float(scores[i]), [], {"semantic"})
                h.snippets.append(str(self._chunk_ids[i]))  # placeholder chunk id
            elif len(h.snippets) < per_talk_snippets:
                h.snippets.append(str(self._chunk_ids[i]))
                h.score += 0.15 * float(scores[i])
            if len(agg) >= limit and all(len(h.snippets) >= per_talk_snippets for h in agg.values()):
                break
        hits = sorted(agg.values(), key=lambda h: -h.score)[:limit]
        self._fill_chunk_snippets(hits)
        return hits

    def semantic_search(self, q: str, limit: int = 20, allowed: set[str] | None = None) -> list[TalkHit]:
        if not self._ensure_matrix():
            return []
        return self.semantic_search_vec(self.embed_query(q), limit, allowed)

    def _fill_chunk_snippets(self, hits: list[TalkHit]) -> None:
        ids = [int(s) for h in hits for s in h.snippets]
        if not ids:
            return
        q = ",".join("?" * len(ids))
        texts = {r["id"]: r["text"] for r in
                 self.conn.execute(f"SELECT id, text FROM chunks WHERE id IN ({q})", ids)}
        for h in hits:
            new = []
            for s in h.snippets:
                t = texts.get(int(s), "")
                # Drop the "Title — Speaker" prefix line, trim.
                body = t.split("\n", 1)[1] if "\n" in t else t
                new.append(_trim(body, 320))
            h.snippets = new

    # ------------------------------------------------------------ hybrid

    def hybrid_search(self, q: str, limit: int = 20, allowed: set[str] | None = None) -> list[TalkHit]:
        kw = self.keyword_search(q, limit * 2, allowed)
        sem = self.semantic_search(q, limit * 2, allowed)
        return rrf_fuse([kw, sem], limit)

    def search(self, q: str, mode: str = "hybrid", limit: int = 20,
               years: tuple[int, int] | None = None, speaker: str | None = None,
               conference: str | None = None) -> list[TalkHit]:
        allowed = self._allowed_talks(years, speaker, conference)
        if mode == "keyword" or (mode == "semantic" and not self.semantic_available):
            return self.keyword_search(q, limit, allowed)
        if mode == "semantic":
            return self.semantic_search(q, limit, allowed)
        return self.hybrid_search(q, limit, allowed)

    # ------------------------------------------------------------ related talks

    def talk_vector(self, talk_id: str) -> np.ndarray | None:
        if not self._ensure_matrix():
            return None
        idx = [i for i, t in enumerate(self._chunk_talks) if t == talk_id]
        if not idx:
            return None
        v = self._matrix[idx].mean(axis=0)
        n = np.linalg.norm(v)
        return (v / n).astype(np.float32) if n else None

    def key_terms(self, talk_id: str, n: int = 10) -> list[str]:
        """Top TF-IDF terms of a talk's body, using the FTS vocabulary for IDF."""
        rows = self.conn.execute(
            "SELECT text FROM paragraphs WHERE talk_id=? AND is_note=0", (talk_id,)).fetchall()
        tf: dict[str, int] = defaultdict(int)
        for r in rows:
            for w in re.findall(r"[A-Za-z][A-Za-z’']+", r["text"].lower()):
                w = w.replace("’", "'")
                if len(w) < 4 or w in STOPWORDS or w.endswith("'s"):
                    continue
                tf[w] += 1
        if not tf:
            return []
        total_docs = self.conn.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0]
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS temp.pvocab USING fts5vocab(main, paragraphs_fts, 'row')")
        cands = sorted(tf.items(), key=lambda kv: -kv[1])[:80]
        scored = []
        for w, f in cands:
            # porter-stem lookups: query vocab with the stemmed token via a MATCH is
            # heavy; approximate by the row-count of the raw term when present.
            row = self.conn.execute("SELECT doc FROM temp.pvocab WHERE term=?", (w,)).fetchone()
            if row is None:
                row = self.conn.execute(
                    "SELECT doc FROM temp.pvocab WHERE term>=? AND term<? ORDER BY term LIMIT 1",
                    (w[:5], w[:5] + "￿")).fetchone()
            df = row[0] if row else 1
            idf = math.log((total_docs + 1) / (df + 1)) + 1
            scored.append((f * idf, w))
        scored.sort(reverse=True)
        return [w for _, w in scored[:n]]

    def related_talks(self, talk_id: str, limit: int = 20,
                      terms: list[str] | None = None) -> tuple[list[TalkHit], list[str]]:
        """Talks like this one. ``terms`` replaces the automatic key terms for this
        call only; the semantic leg still uses the talk's own vector, so results stay
        anchored to the talk and the terms re-rank them rather than redirecting."""
        terms = terms if terms else self.key_terms(talk_id)
        kw: list[TalkHit] = []
        if terms:
            kw = [h for h in self._fts_paragraphs(fts_or_query(terms), limit * 2, None, 2)
                  if h.talk_id != talk_id]
        sem: list[TalkHit] = []
        v = self.talk_vector(talk_id)
        if v is not None:
            sem = self.semantic_search_vec(v, limit * 2, None, exclude=talk_id)
        return rrf_fuse([kw, sem], limit), terms


def rrf_fuse(result_lists: list[list[TalkHit]], limit: int, k: int = 60) -> list[TalkHit]:
    fused: dict[str, TalkHit] = {}
    for hits in result_lists:
        for rank, h in enumerate(hits):
            f = fused.get(h.talk_id)
            if f is None:
                f = fused[h.talk_id] = TalkHit(h.talk_id, 0.0, [], set())
            f.score += 1.0 / (k + rank + 1)
            f.sources |= h.sources
            for s in h.snippets:
                if s not in f.snippets:
                    f.snippets.append(s)
    out = sorted(fused.values(), key=lambda h: -h.score)[:limit]
    if out:
        top = out[0].score
        for h in out:
            h.score = h.score / top  # normalise to 0..1 for display
    return out


def _trim(text: str, n: int) -> str:
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    cut = text[:n]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut + "…"
