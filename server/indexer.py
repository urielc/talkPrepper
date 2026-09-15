"""Build the search index from the scraped talks JSON and the scripture JSON.

Rebuilds every index table from scratch; user tables are untouched. Chunk
embeddings are reused for chunks whose text hash is unchanged so a re-index
after a re-scrape only embeds what actually changed.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import db as dbm
from .citations import (
    parse_scripture_refs, parse_talk_citations, normalize_title, REF_RE,
)
from .config import (
    TALKS_JSON, SCRIPTURES_JSON, CHUNKS_NPY, CHUNK_HASHES, EMBEDDINGS_DIR,
    CHUNK_TARGET_WORDS, CHUNK_MAX_WORDS, DEFAULT_EMBEDDING_MODEL,
)
from .scriptures import load_scriptures_into_db, download_scriptures

MONTH_NAMES = {4: "April", 10: "October"}
ProgressCb = Callable[[str, int, int], None]


@dataclass
class IndexStats:
    conferences: int = 0
    talks: int = 0
    paragraphs: int = 0
    scripture_refs: int = 0
    talk_refs: int = 0
    talk_refs_resolved: int = 0
    verses: int = 0
    chunks: int = 0
    chunks_embedded: int = 0
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d.pop("extra", None)
        return d


# ---------------------------------------------------------------- helpers

_CONF_URL_RE = re.compile(r"/general-conference/(\d{4})/(\d{2})(?:/([^/?#]+))?")


def parse_conference_url(url: str) -> tuple[str, int, int] | None:
    m = _CONF_URL_RE.search(url)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    return f"{year}-{month:02d}", year, month


def talk_id_from_url(url: str) -> str | None:
    m = _CONF_URL_RE.search(url)
    if not m or not m.group(3):
        return None
    return f"{m.group(1)}-{m.group(2)}/{m.group(3)}"


_NOTE_HINTS = re.compile(
    r"\b(Liahona|Ensign|Conference Report|General Handbook|Teachings of Presidents|"
    r"Guide to the Scriptures|Bible Dictionary|Preach My Gospel|Gospel Topics|"
    r"churchofjesuschrist\.org|Improvement Era|New Era|footnote)\b",
    re.IGNORECASE,
)


_STRONG_NOTE = re.compile(
    r"^(?:See |see |For example, see|Cf\. )"                       # cross-reference opener
    r"|[“\"][^”\"]{3,}[”\"][^.]{0,80}\b(?:1[89]|20)\d\d\b"         # quoted title … year (a citation)
    r"|\b(?:https?://|www\.)|\.(?:org|edu|com|net)\b"               # URL
    r"|,\s*\d{1,4}(?:[–-]\d{1,4})?\.?$"                            # trailing page number
    r"|^[A-Z][a-z]+ (?:[A-Z]\. )?[A-Z][a-zA-Z]+, [“\"]"             # Author Name, “Title”
    r"|^(?:In |in )?(?:Conference Report|Teachings of Presidents|Doctrines of Salvation|History of the Church)\b"
)


def note_signal(text: str) -> int:
    """0 = prose, 1 = weak (short line with a scripture ref or number), 2 = strong citation."""
    words = text.split()
    if not words:
        return 0
    if _STRONG_NOTE.search(text) or _NOTE_HINTS.search(text):
        return 2
    if len(words) <= 25:
        if REF_RE.search(text):
            return 1
        if re.search(r"\d", text) and len(words) <= 12:
            return 1
    return 0


def looks_like_note(text: str) -> bool:
    return note_signal(text) > 0


def mark_notes(paragraphs: list[str]) -> list[bool]:
    """Footnotes are a contiguous block at the end. Walk backwards while the
    paragraphs look like citations; tolerate a single non-note line inside the
    block (e.g. a long quoted footnote). The block must contain at least one
    strong citation signal, otherwise it is just a talk ending in scripture
    quotations."""
    flags = [False] * len(paragraphs)
    i = len(paragraphs) - 1
    misses = 0
    start = len(paragraphs)
    strong = 0
    while i >= 0:
        sig = note_signal(paragraphs[i])
        if sig:
            start = i
            misses = 0
            if sig == 2:
                strong += 1
        else:
            misses += 1
            if misses > 1:
                break
        i -= 1
    # Never mark more than the last 60% of a talk as notes, require at least 2
    # note paragraphs, and at least one unmistakable citation among them.
    if len(paragraphs) - start >= 2 and start >= len(paragraphs) * 0.4 and strong >= 1:
        for j in range(start, len(paragraphs)):
            flags[j] = True
    return flags


def speaker_from_paragraphs(paragraphs: list[str]) -> str:
    for p in paragraphs[:3]:
        m = re.match(r"(?:Presented by|By)\s+(.+)", p)
        if m and len(m.group(1)) < 80:
            return m.group(1).strip()
    return ""


def chunk_paragraphs(paragraphs: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
    """Group consecutive (idx, text) paragraphs into ~CHUNK_TARGET_WORDS chunks.
    Returns (para_start, para_end, text)."""
    chunks: list[tuple[int, int, str]] = []
    buf: list[tuple[int, str]] = []
    words = 0
    for idx, text in paragraphs:
        n = len(text.split())
        if buf and words + n > CHUNK_MAX_WORDS:
            chunks.append((buf[0][0], buf[-1][0], "\n".join(t for _, t in buf)))
            buf, words = [], 0
        buf.append((idx, text))
        words += n
        if words >= CHUNK_TARGET_WORDS:
            chunks.append((buf[0][0], buf[-1][0], "\n".join(t for _, t in buf)))
            buf, words = [], 0
    if buf:
        # Merge a tiny trailing chunk into the previous one.
        if chunks and words < CHUNK_TARGET_WORDS // 3:
            ps, _, prev = chunks.pop()
            chunks.append((ps, buf[-1][0], prev + "\n" + "\n".join(t for _, t in buf)))
        else:
            chunks.append((buf[0][0], buf[-1][0], "\n".join(t for _, t in buf)))
    return chunks


def text_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- embeddings

_model_cache: dict[str, object] = {}


def get_embedder(model_name: str = DEFAULT_EMBEDDING_MODEL):
    if model_name not in _model_cache:
        from sentence_transformers import SentenceTransformer
        _model_cache[model_name] = SentenceTransformer(model_name, device="cpu")
    return _model_cache[model_name]


def embed_texts(texts: list[str], model_name: str, batch_size: int = 64,
                progress: ProgressCb | None = None) -> np.ndarray:
    model = get_embedder(model_name)
    out = []
    total = len(texts)
    for i in range(0, total, batch_size * 8):
        batch = texts[i:i + batch_size * 8]
        vecs = model.encode(batch, batch_size=batch_size, normalize_embeddings=True,
                            convert_to_numpy=True, show_progress_bar=False)
        out.append(vecs.astype(np.float32))
        if progress:
            progress("embedding", min(i + len(batch), total), total)
    if not out:
        return np.zeros((0, model.get_sentence_embedding_dimension()), dtype=np.float32)
    return np.vstack(out)


# ---------------------------------------------------------------- main build

def build_index(conn: sqlite3.Connection, talks_json: Path = TALKS_JSON,
                scriptures_json: Path = SCRIPTURES_JSON,
                embedding_model: str = DEFAULT_EMBEDDING_MODEL,
                progress: ProgressCb | None = None,
                skip_embeddings: bool = False) -> IndexStats:
    t0 = time.time()
    stats = IndexStats()

    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    # ---- preserve old chunk vectors keyed by text hash for reuse. The hash
    # list lives in a sidecar file so reuse works even if the chunks table has
    # already been replaced by an interrupted rebuild.
    old_vecs: dict[str, np.ndarray] = {}
    if CHUNKS_NPY.exists() and not skip_embeddings:
        try:
            old_matrix = np.load(CHUNKS_NPY)
            hashes: list[str] = []
            if CHUNK_HASHES.exists():
                hashes = json.loads(CHUNK_HASHES.read_text())
            else:
                rows = conn.execute("SELECT id, text_hash FROM chunks ORDER BY id").fetchall()
                if len(rows) == old_matrix.shape[0]:
                    hashes = [r["text_hash"] for r in rows]
            if len(hashes) == old_matrix.shape[0]:
                for i, h in enumerate(hashes):
                    old_vecs[h] = old_matrix[i]
        except Exception:
            old_vecs = {}

    report("loading talks")
    with open(talks_json, encoding="utf-8") as f:
        data = json.load(f)

    dbm.drop_index_tables(conn)
    dbm.ensure_schema(conn)

    # ---- conferences / talks / paragraphs
    conferences: dict[str, tuple] = {}
    talk_rows: list[tuple] = []
    para_rows: list[tuple] = []          # (talk_id, idx, text, is_note)
    talk_paragraphs: dict[str, list[tuple[int, str, bool]]] = {}

    conf_items = list(data["conferences"].items())
    for ci, (conf_url, conf) in enumerate(conf_items):
        parsed = parse_conference_url(conf_url)
        if not parsed:
            continue
        cid, year, month = parsed
        conferences[cid] = (cid, year, month, f"{MONTH_NAMES.get(month, str(month))} {year}", conf_url)
        for ord_, t in enumerate(conf["talks"]):
            tid = talk_id_from_url(t["url"])
            if not tid:
                continue
            paragraphs = [p for p in t.get("paragraphs", []) if p and p.strip()]
            speaker = (t.get("speaker") or "").strip() or speaker_from_paragraphs(paragraphs)
            speaker = speaker.replace("\xa0", " ")
            title = (t.get("title") or "").strip().replace("\xa0", " ")
            flags = mark_notes(paragraphs)
            wc = sum(len(p.split()) for p, fl in zip(paragraphs, flags) if not fl)
            talk_rows.append((tid, cid, speaker, title, t["url"], wc, ord_))
            plist = []
            for idx, (p, fl) in enumerate(zip(paragraphs, flags)):
                para_rows.append((tid, idx, p, int(fl)))
                plist.append((idx, p, fl))
            talk_paragraphs[tid] = plist
        report("talks", ci + 1, len(conf_items))

    with dbm.transaction(conn):
        conn.executemany("INSERT INTO conferences(id, year, month, label, url) VALUES(?,?,?,?,?)",
                         conferences.values())
        conn.executemany(
            "INSERT INTO talks(id, conference_id, speaker, title, url, word_count, ord) VALUES(?,?,?,?,?,?,?)",
            talk_rows)
        conn.executemany("INSERT INTO paragraphs(talk_id, idx, text, is_note) VALUES(?,?,?,?)", para_rows)
        conn.executemany("INSERT INTO talks_fts(id, title, speaker) VALUES(?,?,?)",
                         [(r[0], r[3], r[2]) for r in talk_rows])
        conn.execute("INSERT INTO paragraphs_fts(paragraphs_fts) VALUES('rebuild')")
    stats.conferences = len(conferences)
    stats.talks = len(talk_rows)
    stats.paragraphs = len(para_rows)

    # ---- scripture refs + talk citations (need paragraph ids)
    report("citations", 0, stats.talks)
    para_ids = {(r["talk_id"], r["idx"]): r["id"]
                for r in conn.execute("SELECT id, talk_id, idx FROM paragraphs")}
    titles_by_conf: dict[str, list[tuple[str, str]]] = {}
    for tid, cid, _sp, title, *_ in talk_rows:
        titles_by_conf.setdefault(cid, []).append((normalize_title(title), tid))

    sref_rows, tref_rows = [], []
    for i, (tid, plist) in enumerate(talk_paragraphs.items()):
        for idx, text, is_note in plist:
            pid = para_ids[(tid, idx)]
            for r in parse_scripture_refs(text):
                sref_rows.append((tid, pid, r.book, r.chapter, r.verse_start, r.verse_end,
                                  r.raw, r.start, r.end))
            if is_note or "Liahona" in text or "Ensign" in text or "Conference Report" in text:
                for c in parse_talk_citations(text):
                    cited = None
                    if c.conference_month:
                        cid = f"{c.year}-{c.conference_month:02d}"
                        cited = _resolve_title(titles_by_conf.get(cid, []), c.title)
                    tref_rows.append((tid, pid, cited, c.title, c.year, c.conference_month, c.raw))
        if (i + 1) % 200 == 0:
            report("citations", i + 1, stats.talks)
    with dbm.transaction(conn):
        conn.executemany(
            "INSERT INTO scripture_refs(talk_id, paragraph_id, book, chapter, verse_start, verse_end, raw, char_start, char_end) "
            "VALUES(?,?,?,?,?,?,?,?,?)", sref_rows)
        conn.executemany(
            "INSERT INTO talk_refs(talk_id, paragraph_id, cited_talk_id, raw_title, raw_year, raw_month, raw) "
            "VALUES(?,?,?,?,?,?,?)", tref_rows)
    stats.scripture_refs = len(sref_rows)
    stats.talk_refs = len(tref_rows)
    stats.talk_refs_resolved = sum(1 for r in tref_rows if r[2])

    # ---- scriptures
    report("scriptures")
    if not scriptures_json.exists():
        download_scriptures(scriptures_json)
    stats.verses = load_scriptures_into_db(conn, scriptures_json)

    # ---- chunks + embeddings
    report("chunking")
    chunk_rows: list[tuple] = []   # (talk_id, para_start, para_end, text, hash)
    for tid, cid, speaker, title, *_ in talk_rows:
        body = [(idx, p) for idx, p, fl in talk_paragraphs[tid] if not fl]
        prefix = f"{title} — {speaker}\n" if speaker else f"{title}\n"
        for ps, pe, text in chunk_paragraphs(body):
            full = prefix + text
            chunk_rows.append((tid, ps, pe, full, text_hash(full)))
    with dbm.transaction(conn):
        conn.executemany(
            "INSERT INTO chunks(talk_id, para_start, para_end, text, text_hash) VALUES(?,?,?,?,?)",
            chunk_rows)
    stats.chunks = len(chunk_rows)

    if not skip_embeddings:
        todo_idx = [i for i, r in enumerate(chunk_rows) if r[4] not in old_vecs]
        report("embedding", 0, len(todo_idx))
        new_vecs = embed_texts([chunk_rows[i][3] for i in todo_idx], embedding_model,
                               progress=progress) if todo_idx else None
        dim = (new_vecs.shape[1] if new_vecs is not None and new_vecs.size
               else next(iter(old_vecs.values())).shape[0] if old_vecs else 384)
        matrix = np.zeros((len(chunk_rows), dim), dtype=np.float32)
        for i, r in enumerate(chunk_rows):
            if r[4] in old_vecs:
                matrix[i] = old_vecs[r[4]]
        for j, i in enumerate(todo_idx):
            matrix[i] = new_vecs[j]
        EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
        np.save(CHUNKS_NPY, matrix)
        CHUNK_HASHES.write_text(json.dumps([r[4] for r in chunk_rows]))
        stats.chunks_embedded = len(todo_idx)
        dbm.set_meta(conn, "embedding_model", embedding_model)

    dbm.set_meta(conn, "built_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    dbm.set_meta(conn, "talks_json", str(talks_json))
    stats.seconds = round(time.time() - t0, 1)
    dbm.set_meta(conn, "stats", json.dumps(stats.to_dict()))
    conn.execute("VACUUM")
    report("done")
    return stats


def _resolve_title(candidates: list[tuple[str, str]], title: str | None) -> str | None:
    if not title:
        return None
    nt = normalize_title(title)
    if not nt:
        return None
    for norm, tid in candidates:
        if norm == nt:
            return tid
    for norm, tid in candidates:
        if norm.startswith(nt) or nt.startswith(norm):
            if min(len(norm), len(nt)) >= 8:
                return tid
    return None
