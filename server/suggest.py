"""Topic suggestions: conference talks (and manual pages) for a topic and an audience.

The index ranks candidates (hybrid search, nudged by each talk's audience tags);
``refine`` optionally has the configured model pick the best of them and say why.
"""

from __future__ import annotations

import json
import sqlite3

from .ai.base import Provider, ProviderError
from .audience import class_members, audience_key, parse_key
from .routers.talks import fetch_talks
from .search import SearchEngine

BOOST = 1.15        # per matching audience tag
PENALTY = 0.85      # a talk tagged for the other gender (a priesthood or women's session talk)
CANDIDATES = 60
MAX_REFINE = 40


def _calls(conn: sqlite3.Connection, ids: list[str]) -> dict[str, sqlite3.Row]:
    if not ids:
        return {}
    return {r["id"]: r for r in conn.execute(
        "SELECT id, calling, audience_tags FROM talks WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(ids),))}


def audience_factor(tags: str, audience: str, gender: str | None) -> float:
    t = set(tags.split())
    f = 1.0
    if audience in ("children", "youth") and audience in t:
        f *= BOOST
    if gender:
        if gender in t:
            f *= BOOST
        elif ("male" if gender == "female" else "female") in t:
            f *= PENALTY
    return f


def page_to_dict(r: sqlite3.Row) -> dict:
    return {"uri": r["uri"], "title": r["title"], "manual": r["manual_title"], "manual_key": r["manual_key"],
            "kind": r["kind"], "audience": r["audience"].split(), "url": r["url"]}


def fetch_pages(conn: sqlite3.Connection, ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    return {r["id"]: page_to_dict(r) for r in conn.execute(
        "SELECT p.*, m.title AS manual_title, m.kind FROM manual_pages p JOIN manuals m ON m.key=p.manual_key "
        "WHERE p.id IN (SELECT value FROM json_each(?))", (json.dumps(ids),))}


def suggest(conn: sqlite3.Connection, engine: SearchEngine, topic: str, audience: str | None,
            gender: str | None, limit: int = 20, manual_limit: int = 6) -> dict:
    key = audience_key(audience, gender)
    a, g = parse_key(key)
    hits = engine.search(topic, "hybrid", CANDIDATES)
    meta = _calls(conn, [h.talk_id for h in hits])
    for h in hits:
        m = meta.get(h.talk_id)
        h.score *= audience_factor(m["audience_tags"] if m else "", a, g)
    hits.sort(key=lambda h: -h.score)
    hits = hits[:limit]
    talks = fetch_talks(conn, [h.talk_id for h in hits])
    out = []
    for h in hits:
        t = talks.get(h.talk_id)
        if not t:
            continue
        m = meta.get(h.talk_id)
        out.append({**t, "calling": m["calling"] if m else "", "audience_tags": (m["audience_tags"] if m else "").split(),
                    "score": round(h.score, 4), "snippet": h.snippets[0] if h.snippets else ""})

    pages = []
    mhits = engine.manual_search(topic, "hybrid", manual_limit, audience=a, gender=g)
    found = fetch_pages(conn, [int(h.talk_id) for h in mhits])
    for h in mhits:
        p = found.get(int(h.talk_id))
        if p:
            pages.append({**p, "snippet": h.snippets[0] if h.snippets else ""})
    return {"topic": topic, "audience": key, "class": class_members(key), "talks": out, "manuals": pages,
            "semantic_available": engine.semantic_available}


REFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "description": "Up to 10 talks, best first.",
            "items": {
                "type": "object",
                "properties": {
                    "talk_id": {"type": "string", "description": "Id exactly as given in brackets."},
                    "reason": {"type": "string", "description": "One sentence: why this talk suits this topic and class."},
                },
                "required": ["talk_id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["picks"],
    "additionalProperties": False,
}

REFINE_SYSTEM = """You help a teacher in The Church of Jesus Christ of Latter-day Saints choose one General Conference talk to build a lesson on.

You are given the topic, the class being taught, and candidate talks found by a search (title, speaker, conference, the speaker's calling, and a passage that matched). Choose up to 10 that would best carry a lesson on that topic for that class, best first. Favor talks whose central message is the topic over talks that only mention it, and talks whose examples and language suit the class. Use only the candidates given, with their ids exactly as written. For each, write one plain sentence on why it fits. Do not invent details about a talk beyond what is shown."""


def refine(conn: sqlite3.Connection, provider: Provider, topic: str, audience: str | None,
           gender: str | None, talk_ids: list[str]) -> dict:
    key = audience_key(audience, gender)
    ids = list(dict.fromkeys(talk_ids))[:MAX_REFINE]
    talks = fetch_talks(conn, ids)
    meta = _calls(conn, ids)
    if not talks:
        raise ProviderError("No talks to choose from.")
    lines = []
    for tid in ids:
        t = talks.get(tid)
        if not t:
            continue
        calling = meta[tid]["calling"] if tid in meta and meta[tid]["calling"] else ""
        first = conn.execute(
            "SELECT text FROM paragraphs WHERE talk_id=? AND is_note=0 AND idx>=2 ORDER BY idx LIMIT 2", (tid,)).fetchall()
        opening = " ".join(r["text"] for r in first)[:500]
        lines.append(f"[{tid}] “{t['title']}”, {t['speaker']}{', ' + calling if calling else ''}, {t['conference']}\n"
                     f"  Opening: {opening}")
    msg = f"Topic: {topic}\nClass: {class_members(key)}\n\nCandidates:\n" + "\n".join(lines)
    data = provider.generate_json(REFINE_SYSTEM, msg, REFINE_SCHEMA)
    picks, seen = [], set()
    for p in data.get("picks", []):
        tid = str(p.get("talk_id", "")).strip().strip("[]")
        if tid in talks and tid not in seen:
            seen.add(tid)
            picks.append({"talk_id": tid, "reason": str(p.get("reason", "")).strip()})
    return {"audience": key, "picks": picks[:10], "provider": provider.name, "model": provider.model}
