"""Topic suggestions: conference talks (and manual pages) for a topic and an audience.

The index ranks candidates (hybrid search, nudged by each talk's audience tags);
``refine`` optionally has the configured model pick the best of them and say why.
"""

from __future__ import annotations

import json
import re
import sqlite3

from .ai.base import Provider, ProviderError
from .ai.study import audience_mode
from .audience import class_members, audience_key, parse_key
from .citations import parse_ref
from .routers.talks import fetch_talks
from . import josephus as jos
from .manuals import SOURCES
from .scriptures import APOCRYPHA, format_ref, get_verses, search_verses
from .search import STOPWORDS, SearchEngine, fts_loose_query

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
            gender: str | None, limit: int = 20, manual_limit: int = 6, song_limit: int = 4) -> dict:
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

    # Lessons and manuals, and songs, searched separately so each list gets its own best matches.
    song_keys = [s.key for s in SOURCES if s.number_label]
    other_keys = [s.key for s in SOURCES if not s.number_label]

    def pages_for(keys: list[str], n: int) -> list[dict]:
        hits = engine.manual_search(topic, "hybrid", n, manual=keys, audience=a, gender=g)
        found = fetch_pages(conn, [int(h.talk_id) for h in hits])
        return [{**found[int(h.talk_id)], "snippet": h.snippets[0] if h.snippets else ""}
                for h in hits if int(h.talk_id) in found]

    pages = pages_for(other_keys, manual_limit)
    songs = pages_for(song_keys, song_limit)
    return {"topic": topic, "audience": key, "class": class_members(key), "talks": out, "manuals": pages,
            "songs": songs, "semantic_available": engine.semantic_available}


PASSAGE_SPAN = 12   # longest passage a verse-hit group may grow to


def group_verses(rows: list[dict], limit: int) -> list[dict]:
    """Verse hits to queueable passages: hits in one chapter become one range.

    ``rows`` come from ``search_verses`` (best first). A chapter's hits span the first to the last hit verse; a
    span wider than PASSAGE_SPAN shrinks to a window around the best hit."""
    chapters: dict[tuple[str, int], list[dict]] = {}
    for r in rows:
        chapters.setdefault((r["book"], r["chapter"]), []).append(r)
    out = []
    for (book, chapter), hits in chapters.items():
        best = max(hits, key=lambda h: h["score"])
        lo, hi = min(h["verse"] for h in hits), max(h["verse"] for h in hits)
        if hi - lo + 1 > PASSAGE_SPAN:
            lo, hi = max(1, best["verse"] - 3), best["verse"] + 3
            hits = [h for h in hits if lo <= h["verse"] <= hi]
        ref = f"{book} {chapter}:{lo}" + (f"\u2013{hi}" if hi != lo else "")
        out.append({"kind": "scripture", "ref": ref, "title": ref, "snippet": best["snippet"],
                    "verses": len(hits), "score": round(sum(h["score"] for h in hits), 4)})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


VERSE_HITS = 120   # verses read per search before they are grouped into passages


def weight_by_coverage(rows: list[dict], topic: str) -> None:
    """Scale each verse's score by how many of the topic's terms it contains, squared, then re-sort. bm25 on an
    OR query lets one rare word carry a verse ("seems" in "prayer when God seems silent"); a verse that holds
    two or three of the terms is the better match. Terms match on a five-letter prefix, a rough stem."""
    terms = {t.lower()[:5] for t in re.findall(r"[A-Za-z]+", topic) if t.lower() not in STOPWORDS and len(t) > 2}
    if len(terms) < 2:
        return
    for r in rows:
        words = {w.lower()[:5] for w in re.findall(r"[A-Za-z]+", r["text"])}
        r["score"] *= max(1, len(terms & words)) ** 2
    rows.sort(key=lambda r: -r["score"])


def _verse_group(conn: sqlite3.Connection, topic: str, apocrypha: bool, limit: int) -> list[dict]:
    """Passages for the topic. The search is loose (any term, stopwords dropped, ranked by bm25) because a
    topic is a few words, not a phrase one verse contains; chapters with several hits rise through the sum."""
    match = fts_loose_query(topic)
    if not match:
        return []
    try:
        rows = search_verses(conn, match, VERSE_HITS, apocrypha=apocrypha)
    except sqlite3.OperationalError:
        return []
    weight_by_coverage(rows, topic)
    items = group_verses(rows, limit)
    for it in items:
        it["kind"] = "apocrypha" if apocrypha else "scripture"
    return items


def _josephus_group(conn: sqlite3.Connection, engine: SearchEngine, topic: str, limit: int) -> list[dict]:
    hits = engine.josephus_search(topic, "hybrid", limit)
    ids = [int(h.talk_id) for h in hits]
    if not ids:
        return []
    rows = {r["id"]: r for r in conn.execute(
        "SELECT * FROM josephus WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(ids),))}
    out = []
    for h in hits:
        r = rows.get(int(h.talk_id))
        if r is None:
            continue
        lab = jos.row_label(r)
        out.append({"kind": "josephus", "ref": lab, "title": r["chapter_title"] or lab,
                    "subtitle": f"{lab} (Niese {jos.row_niese(r)})",
                    "snippet": h.snippets[0] if h.snippets else ""})
    return out


def topic_search(conn: sqlite3.Connection, engine: SearchEngine, topic: str, audience: str | None) -> dict:
    """Everything the topic page can queue, grouped by kind: talks, manual pages, songs, scripture passages,
    Josephus sections and Apocrypha passages. ``audience`` is a full audience key (see ``audience.py``)."""
    base = suggest(conn, engine, topic, audience, None, limit=20, manual_limit=8, song_limit=5)
    talks = [{**t, "kind": "talk", "ref": t["id"]} for t in base["talks"]]
    manuals = [{**m, "manual_kind": m["kind"], "kind": "manual", "ref": m["uri"]} for m in base["manuals"]]
    songs = [{**m, "manual_kind": m["kind"], "kind": "song", "ref": m["uri"]} for m in base["songs"]]
    return {"topic": topic, "audience": base["audience"], "talks": talks, "manuals": manuals, "songs": songs,
            "scriptures": _verse_group(conn, topic, False, 8),
            "josephus": _josephus_group(conn, engine, topic, 6),
            "apocrypha": _verse_group(conn, topic, True, 5),
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


def _talk_lines(conn: sqlite3.Connection, ids: list[str], talks: dict, meta: dict) -> list[str]:
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
    return lines


def refine(conn: sqlite3.Connection, provider: Provider, topic: str, audience: str | None,
           gender: str | None, talk_ids: list[str]) -> dict:
    key = audience_key(audience, gender)
    ids = list(dict.fromkeys(talk_ids))[:MAX_REFINE]
    talks = fetch_talks(conn, ids)
    meta = _calls(conn, ids)
    if not talks:
        raise ProviderError("No talks to choose from.")
    lines = _talk_lines(conn, ids, talks, meta)
    msg = f"Topic: {topic}\nClass: {class_members(key)}\n\nCandidates:\n" + "\n".join(lines)
    data = provider.generate_json(REFINE_SYSTEM, msg, REFINE_SCHEMA)
    picks, seen = [], set()
    for p in data.get("picks", []):
        tid = str(p.get("talk_id", "")).strip().strip("[]")
        if tid in talks and tid not in seen:
            seen.add(tid)
            picks.append({"talk_id": tid, "reason": str(p.get("reason", "")).strip()})
    return {"audience": key, "picks": picks[:10], "provider": provider.name, "model": provider.model}


# ---------------------------------------------------------------- refine any group

REFINE_GROUPS = ("talks", "manuals", "songs", "scriptures", "josephus", "apocrypha")
PASSAGE_GROUPS = ("scriptures", "apocrypha")
MAX_PICKS = 10
MAX_ADDITIONS = 5

_PICK = {
    "type": "object",
    "properties": {
        "ref": {"type": "string", "description": "Ref exactly as given in brackets."},
        "reason": {"type": "string", "description": "One sentence: why this fits the topic and the purpose."},
    },
    "required": ["ref", "reason"],
    "additionalProperties": False,
}
GROUP_SCHEMA = {
    "type": "object",
    "properties": {"picks": {"type": "array", "description": "Up to 10 candidates, best first.", "items": _PICK}},
    "required": ["picks"],
    "additionalProperties": False,
}
# Counts live in the prompt: structured outputs reject minItems/maxItems other than 0 or 1.
PASSAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": GROUP_SCHEMA["properties"]["picks"],
        "additions": {
            "type": "array",
            "description": "Passages that are not candidates but belong in this list. May be empty.",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "A scripture reference such as Alma 32:21-43."},
                    "reason": {"type": "string", "description": "One sentence: why this passage fits."},
                },
                "required": ["ref", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["picks", "additions"],
    "additionalProperties": False,
}

_GROUP_NOUN = {
    "talks": "General Conference talks",
    "manuals": "pages of Church manuals and lessons",
    "songs": "hymns and Children's Songbook songs",
    "scriptures": "passages of the standard works (Old and New Testaments, Book of Mormon, Doctrine and Covenants, "
                  "Pearl of Great Price)",
    "josephus": "sections of the works of Josephus, the first-century Jewish historian",
    "apocrypha": "passages of the Apocrypha (the books between the Old and New Testaments)",
}
_GROUP_NOTE = {
    "talks": "Favor talks whose central message is the topic over talks that only mention it.",
    "manuals": "Favor pages that teach the topic directly.",
    "songs": "Favor songs whose words speak to the topic.",
    "scriptures": "Favor passages that teach or illustrate the topic directly over passages that share a word with it.",
    "josephus": "Josephus is history, not scripture. Favor sections that give useful historical background for the "
                "topic, and do not present them as doctrine.",
    "apocrypha": "The Apocrypha is not part of the standard works. Favor passages that speak to the topic, and do "
                 "not present them as doctrine.",
}
_PURPOSE = {
    "class": "a teacher preparing a lesson for {class_members}",
    "sacrament": "someone preparing a sacrament meeting talk, so material a speaker can quote and build on",
    "personal": "someone studying on their own, so material that invites reflection",
}
_PASSAGE_EXTRA = (
    " The search may have missed good passages. You may also propose up to {n} passages that are not candidates, "
    "in \"additions\", each a real reference of at most {span} verses written like Alma 32:21-30 (book, chapter, "
    "verse range), and only passages you are certain exist and that you know say what the reason claims. Return "
    "none if unsure.")


def group_system(group: str, audience: str) -> str:
    mode = audience_mode(audience)
    purpose = _PURPOSE[mode].format(class_members=class_members(audience))
    s = (f"You help {purpose} choose source material on a topic, for a member of The Church of Jesus Christ of "
         f"Latter-day Saints.\n\nYou are given the topic, who the material is for, and candidate "
         f"{_GROUP_NOUN[group]} found by a search. Choose up to {MAX_PICKS} that would best serve, best first. "
         f"{_GROUP_NOTE[group]} Use only the candidates given in \"picks\", with refs exactly as written in "
         f"brackets. For each, write one plain sentence on why it fits. Do not invent details beyond what is shown.")
    if group in PASSAGE_GROUPS:
        s += _PASSAGE_EXTRA.format(n=MAX_ADDITIONS, span=PASSAGE_SPAN)
    return s


def _plain(text: str) -> str:
    return re.sub(r"</?mark>", "", text or "")


def _norm_ref(ref: str) -> str:
    return re.sub(r"\s+", " ", ref.replace("\u2013", "-").replace("\u2014", "-")).strip().lower()


def _candidate_lines(conn: sqlite3.Connection, group: str, items: list[dict]) -> list[str]:
    if group == "talks":
        ids = [i["ref"] for i in items]
        return _talk_lines(conn, ids, fetch_talks(conn, ids), _calls(conn, ids))
    lines = []
    for i in items:
        head = f"[{i['ref']}] {i['title']}" if i["title"] and i["title"] != i["ref"] else f"[{i['ref']}]"
        if i.get("subtitle"):
            head += f" ({i['subtitle']})"
        snip = _plain(i.get("snippet", ""))[:500]
        lines.append(head + (f"\n  Excerpt: {snip}" if snip else ""))
    return lines


def _passage(conn: sqlite3.Connection, ref: str, apocrypha: bool) -> dict | None:
    """A model-proposed passage as a result item, or None when it is not a real passage in the right volume."""
    p = parse_ref(ref)
    if not p:
        return None
    book, chapter, vs, ve = p
    row = conn.execute("SELECT volume FROM scriptures WHERE book=? AND chapter=? LIMIT 1", (book, chapter)).fetchone()
    if row is None or (row["volume"] == APOCRYPHA) != apocrypha:
        return None
    if vs is None:
        vs, ve = 1, PASSAGE_SPAN
    ve = vs if ve is None else max(ve, vs)
    ve = min(ve, vs + PASSAGE_SPAN - 1)
    verses = get_verses(conn, book, chapter, vs, ve)
    if not verses:
        return None
    lo, hi = verses[0].verse, verses[-1].verse
    out_ref = format_ref(book, chapter, lo, hi)
    return {"kind": "apocrypha" if apocrypha else "scripture", "ref": out_ref, "title": out_ref,
            "snippet": verses[0].text[:240], "verses": len(verses), "score": 0.0}


def refine_group(conn: sqlite3.Connection, provider: Provider, topic: str, audience: str | None, group: str,
                 items: list[dict]) -> dict:
    """Have the model pick the best of one group's results and say why. ``items`` are the group's current
    results as ``{ref, title, subtitle?, snippet?}``. Picks are validated against the candidate refs. For the
    scripture groups the model may also propose passages the search missed; those come back as ``additions``
    (result items with a ``reason``) after checking that they exist in the right volume."""
    if group not in REFINE_GROUPS:
        raise ProviderError(f"Unknown group {group!r}.")
    key = audience_key(audience, None)
    cands: dict[str, dict] = {}
    for i in items[:MAX_REFINE]:
        ref = str(i.get("ref", "")).strip()
        if ref and ref not in cands:
            cands[ref] = {"ref": ref, "title": str(i.get("title", "")).strip(), "subtitle": str(i.get("subtitle", "")).strip(),
                          "snippet": str(i.get("snippet", ""))}
    if group == "talks":    # only real talks go to the model
        real = fetch_talks(conn, list(cands))
        cands = {r: c for r, c in cands.items() if r in real}
    if not cands and group not in PASSAGE_GROUPS:
        raise ProviderError("Nothing to choose from.")
    lines = _candidate_lines(conn, group, list(cands.values()))
    msg = (f"Topic: {topic}\nFor: {_PURPOSE[audience_mode(key)].format(class_members=class_members(key))}\n\n"
           f"Candidates:\n" + ("\n".join(lines) if lines else "(none found by the search)"))
    schema = PASSAGE_SCHEMA if group in PASSAGE_GROUPS else GROUP_SCHEMA
    data = provider.generate_json(group_system(group, key), msg, schema)
    by_norm = {_norm_ref(r): r for r in cands}
    picks, seen = [], set()
    for p in data.get("picks", []):
        ref = by_norm.get(_norm_ref(str(p.get("ref", "")).strip().strip("[]")))
        if ref and ref not in seen:
            seen.add(ref)
            picks.append({"ref": ref, "reason": str(p.get("reason", "")).strip()})
    additions = []
    if group in PASSAGE_GROUPS:
        for a in data.get("additions", []):
            item = _passage(conn, str(a.get("ref", "")), group == "apocrypha")
            if item is None:
                continue
            existing = by_norm.get(_norm_ref(item["ref"]))
            if existing:        # the model proposed a passage the search already found
                if existing not in seen:
                    seen.add(existing)
                    picks.append({"ref": existing, "reason": str(a.get("reason", "")).strip()})
                continue
            if item["ref"] in seen:
                continue
            seen.add(item["ref"])
            additions.append({**item, "reason": str(a.get("reason", "")).strip()})
    return {"audience": key, "group": group, "picks": picks[:MAX_PICKS], "additions": additions[:MAX_ADDITIONS],
            "provider": provider.name, "model": provider.model}
