"""Topic study summary: an AI overview of a queue of sources, built the way a talk digest is.

``gather`` loads the full text of each queued source (capped), ``candidates`` finds real further-study
material so suggestions are never invented, and ``generate_study`` makes one structured-JSON call, validates
every source label, scripture reference and candidate id the model returns, and stores the result on the
``studies`` row.
"""

from __future__ import annotations

import json
import re
import sqlite3

from . import get_provider
from .base import ProviderError
from .. import josephus as jos
from .. import manuals as man
from ..audience import class_members, class_name, is_class, question_style
from ..citations import parse_ref
from ..scriptures import format_ref, get_verses
from ..search import SearchEngine
from ..settings import get_settings
from ..studies import MAX_SOURCES, study_to_dict

MAX_WORDS = 60_000        # across all sources; the longest are trimmed first
MIN_KEEP = 400            # never trim a source below this many words
N_CANDIDATES = 25

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string", "description": "What the sources say about the topic, in 3 to 5 sentences."},
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "body": {"type": "string", "description": "Two to four sentences."},
                    "sources": {"type": "array", "items": {"type": "string"},
                                "description": "Source labels such as S1 that support this theme."},
                },
                "required": ["heading", "body", "sources"],
                "additionalProperties": False,
            },
        },
        "key_quotes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Exact sentence(s) copied verbatim from one source."},
                    "source": {"type": "string", "description": "The source label, such as S2."},
                    "why": {"type": "string", "description": "Why this line matters, one sentence."},
                },
                "required": ["text", "source", "why"],
                "additionalProperties": False,
            },
        },
        "scriptures": {"type": "array", "items": {"type": "string"},
                       "description": "Scripture references that bear on the topic, such as Alma 32:21."},
        "ponder": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "kind": {"type": "string", "enum": ["opening", "discussion", "application"]},
                    "note": {"type": "string", "description": "What it is meant to surface, one sentence."},
                },
                "required": ["question", "kind", "note"],
                "additionalProperties": False,
            },
        },
        "further": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "Candidate id such as C3, exactly as given."},
                    "why": {"type": "string", "description": "One sentence on what it adds."},
                },
                "required": ["candidate_id", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "themes", "key_quotes", "scriptures", "ponder", "further"],
    "additionalProperties": False,
}

_INTRO = {
    "class": "You prepare a study summary on a topic for someone who will lead {class_name} discussion.",
    "sacrament": "You prepare a study summary on a topic for someone preparing a sacrament meeting talk.",
    "personal": "You prepare a study summary on a topic for someone studying on their own.",
}
_PONDER = {
    "class": "6 to 10 questions for {class_members}. Mix kinds: \"opening\" (draws people in, no wrong answers), "
             "\"discussion\" (probes the ideas, invites nuance), \"application\" (connects the teaching to their "
             "lives). {style} Avoid yes/no questions. Each has a short teacher note on what it is meant to surface.",
    "sacrament": "6 to 10 prompts that help the speaker build a sacrament meeting talk. Mix kinds: \"opening\" "
                 "(ways to begin), \"discussion\" (angles and ideas to develop), \"application\" (personal "
                 "experiences and invitations to close with). {style} Each has a short note for the speaker.",
    "personal": "6 to 10 reflection questions for one person. Mix kinds: \"opening\" (a first thought to sit "
                "with), \"discussion\" (probes the ideas), \"application\" (connects the teaching to their own "
                "life and next steps). {style} Each has a short note for the student.",
}

SYSTEM = """{intro}

You are given numbered sources (S1, S2, ...) in full: General Conference talks, Church manual pages, hymns and songs, scripture passages, and sometimes Josephus or the Apocrypha. Work only from those sources. Do not add doctrine, commentary or testimony of your own; the summary is a faithful synthesis of what the sources say about the topic. Josephus is a historian, not scripture: present it as background. The Apocrypha is not part of the standard works: label it as such.

Guidelines:
- overview: what the sources together say about the topic, in 3 to 5 sentences.
- themes: 3 to 6 themes that run through the sources, each with the labels of the sources that support it (use only the labels given).
- key_quotes: 4 to 8 sentences copied verbatim from a single source, with its label. Never paraphrase or splice; copy exactly.
- scriptures: up to 8 references that bear on the topic, taken from the sources or the scripture passages given.
- ponder: {ponder}
- further: up to 8 items chosen from the numbered candidates (ids such as C1), each with one sentence on what it adds. Use only the candidate ids given, exactly as written.

Instructions from the user, if any, can change emphasis, tone or length. They never allow invented quotations, labels or candidate ids."""


def audience_mode(audience: str) -> str:
    return audience if not is_class(audience) else "class"


def system_prompt(audience: str) -> str:
    mode = audience_mode(audience)
    ponder = _PONDER[mode].format(class_members=class_members(audience), style=question_style(audience))
    return SYSTEM.format(intro=_INTRO[mode].format(class_name=class_name(audience)), ponder=ponder)


# ---------------------------------------------------------------- gathering sources

def _words(text: str) -> int:
    return len(text.split())


def _talk_text(conn: sqlite3.Connection, ref: str) -> tuple[str, str] | None:
    t = conn.execute("SELECT t.title, t.speaker, c.label FROM talks t JOIN conferences c ON c.id=t.conference_id "
                     "WHERE t.id=?", (ref,)).fetchone()
    if not t:
        return None
    rows = conn.execute("SELECT text, num FROM paragraphs WHERE talk_id=? AND is_note=0 ORDER BY idx", (ref,)).fetchall()
    # The first rows are the byline and calling; keep them, they name the speaker.
    body = "\n\n".join((f"¶{r['num']} " if r["num"] else "") + r["text"] for r in rows)
    return f"{t['title']}, {t['speaker']}, {t['label']}", body


def _manual_text(conn: sqlite3.Connection, ref: str) -> tuple[str, str] | None:
    p = man.get_page(conn, ref)
    if not p:
        return None
    return f"{p['title']} ({p['manual_title']})", man.page_text(conn, p["id"])


def _scripture_text(conn: sqlite3.Connection, ref: str) -> tuple[str, str] | None:
    parsed = parse_ref(ref)
    if not parsed:
        return None
    book, chapter, vs, ve = parsed
    verses = get_verses(conn, book, chapter, vs, ve)
    if not verses:
        return None
    return format_ref(book, chapter, vs, ve), "\n".join(f"{v.verse} {v.text}" for v in verses)


def _josephus_text(conn: sqlite3.Connection, ref: str) -> tuple[str, str] | None:
    rows = jos.lookup(conn, ref)
    if not rows:
        return None
    return jos.range_label(rows), "\n\n".join(f"[{jos.row_label(r)}] {r['text']}" for r in rows)


_LOADERS = {"talk": _talk_text, "manual": _manual_text, "song": _manual_text,
            "scripture": _scripture_text, "apocrypha": _scripture_text, "josephus": _josephus_text}
_KIND_NAME = {"talk": "Conference talk", "manual": "Church manual page", "song": "Hymn or song",
              "scripture": "Scripture passage", "apocrypha": "Apocrypha passage (not scripture)",
              "josephus": "Josephus (historian, not scripture)"}


def trim_to_budget(texts: list[str], cap: int = MAX_WORDS) -> list[bool]:
    """Shrink the longest texts in place until the total fits about ``cap`` words (longest first, so short
    sources stay whole). Returns which texts were trimmed."""
    sizes = [_words(t) for t in texts]
    trimmed = [False] * len(texts)
    if sum(sizes) <= cap:
        return trimmed
    lo, hi = 0, max(sizes)
    while lo < hi:                      # the largest per-source limit whose total fits
        mid = (lo + hi + 1) // 2
        if sum(min(s, mid) for s in sizes) <= cap:
            lo = mid
        else:
            hi = mid - 1
    limit = max(lo, MIN_KEEP)
    for i, size in enumerate(sizes):
        if size > limit:
            texts[i] = " ".join(texts[i].split()[:limit]) + " […]"
            trimmed[i] = True
    return trimmed


def gather(conn: sqlite3.Connection, sources: list[dict], cap: int = MAX_WORDS) -> tuple[list[dict], list[dict]]:
    """Full text for each source, labeled S1, S2, ... in queue order.

    Returns ``(loaded, missing)``. A source that no longer resolves is reported in ``missing`` and skipped.
    Each loaded entry has label, kind, ref, title, text and trimmed."""
    loaded, missing = [], []
    for s in sources[:MAX_SOURCES]:
        res = _LOADERS[s["kind"]](conn, s["ref"]) if s.get("kind") in _LOADERS else None
        if res is None:
            missing.append(s)
            continue
        title, text = res
        loaded.append({"kind": s["kind"], "ref": s["ref"], "title": title, "text": text})
    texts = [x["text"] for x in loaded]
    flags = trim_to_budget(texts, cap)
    for i, (x, t, f) in enumerate(zip(loaded, texts, flags), 1):
        x.update(label=f"S{i}", text=t, trimmed=f)
    return loaded, missing


def candidates(conn: sqlite3.Connection, engine: SearchEngine, topic: str, exclude: set[tuple[str, str]],
               n: int = N_CANDIDATES) -> list[dict]:
    """Real further-study items for the topic (talks, manual pages, Josephus), not already queued."""
    from ..routers.talks import fetch_talks
    from ..suggest import fetch_pages
    out: list[dict] = []

    def add(kind: str, ref: str, title: str, snippet: str = "") -> None:
        if (kind, ref) not in exclude and not any(c["kind"] == kind and c["ref"] == ref for c in out):
            out.append({"kind": kind, "ref": ref, "title": title, "snippet": re.sub(r"</?mark>", "", snippet)})

    hits = engine.search(topic, "hybrid", 40)
    talks = fetch_talks(conn, [h.talk_id for h in hits])
    talk_items = [(h, talks[h.talk_id]) for h in hits if h.talk_id in talks and ("talk", h.talk_id) not in exclude]
    for h, t in talk_items[:12]:
        add("talk", t["id"], f"{t['title']}, {t['speaker']}, {t['conference']}", h.snippets[0] if h.snippets else "")
    mhits = engine.manual_search(topic, "hybrid", 20)
    pages = fetch_pages(conn, [int(h.talk_id) for h in mhits])
    songs = {s.key for s in man.SOURCES if s.number_label}
    for h in mhits:
        p = pages.get(int(h.talk_id))
        if p and p["manual_key"] not in songs:
            add("manual", p["uri"], f"{p['title']} ({p['manual']})", h.snippets[0] if h.snippets else "")
        if sum(1 for c in out if c["kind"] == "manual") >= 8:
            break
    jhits = engine.josephus_search(topic, "hybrid", 5)
    if jhits:
        rows = {r["id"]: r for r in conn.execute(
            "SELECT * FROM josephus WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps([int(h.talk_id) for h in jhits]),))}
        for h in jhits:
            r = rows.get(int(h.talk_id))
            if r:
                add("josephus", jos.row_label(r), f"{jos.row_label(r)} {r['chapter_title']}".strip(),
                    h.snippets[0] if h.snippets else "")
    out = out[:n]
    for i, c in enumerate(out, 1):
        c["id"] = f"C{i}"
    return out


def build_user_message(topic: str, modifier: str, loaded: list[dict], cands: list[dict]) -> str:
    parts = [f"Topic: {topic}"]
    trimmed = [x["label"] for x in loaded if x["trimmed"]]
    if trimmed:
        parts.append(f"Some sources were cut for length (marked […]): {', '.join(trimmed)}. Draw only on what is shown.")
    parts.append("--- SOURCES ---")
    for x in loaded:
        parts.append(f"[{x['label']}] {_KIND_NAME[x['kind']]}: {x['title']}\n{x['text']}")
    parts.append("--- CANDIDATES FOR FURTHER STUDY ---")
    parts.extend(f"[{c['id']}] {_KIND_NAME[c['kind']]}: {c['title']}"
                 + (f"\n  Matched: {c['snippet'][:300]}" if c["snippet"] else "") for c in cands)
    if modifier.strip():
        parts.append(f"--- Additional instructions from the user ---\n{modifier.strip()}")
    return "\n\n".join(parts)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[“”\"']", "", s.replace("’", "'"))).strip().lower()


def validate(data: dict, loaded: list[dict], cands: list[dict], conn: sqlite3.Connection) -> dict:
    """Keep only labels, scripture references and candidate ids that exist; flag quotes not found verbatim."""
    labels = {x["label"]: x for x in loaded}
    by_id = {c["id"]: c for c in cands}
    themes = []
    for t in data.get("themes", []):
        t["sources"] = [s for s in dict.fromkeys(str(x).strip().strip("[]") for x in t.get("sources", [])) if s in labels]
        themes.append(t)
    quotes = []
    for q in data.get("key_quotes", []):
        label = str(q.get("source", "")).strip().strip("[]")
        if label not in labels:
            continue
        q["source"] = label
        q["verified"] = bool(_norm(q.get("text", ""))) and _norm(q["text"]) in _norm(labels[label]["text"])
        quotes.append(q)
    refs = []
    for r in data.get("scriptures", []):
        parsed = parse_ref(str(r))
        if parsed and get_verses(conn, *parsed):
            f = format_ref(*parsed)
            if f not in refs:
                refs.append(f)
    further, seen = [], set()
    for f in data.get("further", []):
        cid = str(f.get("candidate_id", "")).strip().strip("[]")
        c = by_id.get(cid)
        if c and cid not in seen:
            seen.add(cid)
            further.append({"candidate_id": cid, "kind": c["kind"], "ref": c["ref"], "title": c["title"],
                            "why": str(f.get("why", "")).strip()})
    return {"overview": data.get("overview", ""), "themes": themes, "key_quotes": quotes, "scriptures": refs,
            "ponder": data.get("ponder", []), "further": further}


def generate_study(conn: sqlite3.Connection, engine: SearchEngine, uid: int, study: dict) -> dict:
    """Generate (or regenerate) the summary for ``study`` (a dict from ``study_to_dict``, owned by ``uid``)."""
    provider = get_provider(get_settings(conn))
    loaded, missing = gather(conn, study["sources"])
    if not loaded:
        raise ProviderError("None of the queued sources could be found. Edit the sources and try again.")
    exclude = {(s["kind"], s["ref"]) for s in study["sources"]}
    cands = candidates(conn, engine, study["topic"], exclude)
    msg = build_user_message(study["topic"], study["modifier"], loaded, cands)
    data = provider.generate_json(system_prompt(study["audience"]), msg, SUMMARY_SCHEMA)
    out = validate(data, loaded, cands, conn)
    out["source_labels"] = [{"label": x["label"], "kind": x["kind"], "ref": x["ref"], "title": x["title"],
                             "trimmed": x["trimmed"]} for x in loaded]
    out["missing"] = [{"kind": s["kind"], "ref": s["ref"], "title": s.get("title", "")} for s in missing]
    conn.execute("UPDATE studies SET summary_json=?, provider=?, model=?, updated_at=datetime('now') "
                 "WHERE id=? AND user_id=?",
                 (json.dumps(out, ensure_ascii=False), provider.name, provider.model, study["id"], uid))
    conn.commit()
    return study_to_dict(conn.execute("SELECT * FROM studies WHERE id=?", (study["id"],)).fetchone())


__all__ = ["SUMMARY_SCHEMA", "generate_study", "gather", "candidates", "validate", "ProviderError"]
