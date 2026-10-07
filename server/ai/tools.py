"""Tools the assistant can call. Executors reuse the search/scripture modules."""

from __future__ import annotations

import sqlite3

import json

from ..citations import parse_scripture_refs
from .. import josephus as jos
from ..routers.scriptures import parse_single_ref
from ..routers.talks import fetch_talks, talks_citing
from ..scriptures import get_verses, format_ref, search_verses, BOOK_VOLUME, APOCRYPHA
from ..search import fts_query
from ..search import SearchEngine
from .base import ToolSpec, ToolResult

TOOLS: list[ToolSpec] = [
    ToolSpec(
        "search_talks",
        "Search all General Conference talks (1971–present) for a topic, phrase or idea. "
        "Use mode 'keyword' for exact words/phrases (put phrases in double quotes), 'semantic' for "
        "concepts expressed in different words, or 'hybrid' (default) for both. Returns talk ids, "
        "titles, speakers, conferences and matching snippets.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic, phrase or question to search for"},
                "mode": {"type": "string", "enum": ["hybrid", "keyword", "semantic"], "default": "hybrid"},
                "year_from": {"type": "integer", "description": "Optional earliest conference year"},
                "year_to": {"type": "integer", "description": "Optional latest conference year"},
                "speaker": {"type": "string", "description": "Optional speaker name filter (substring)"},
                "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "get_talk",
        "Fetch a talk by id: title, speaker, conference, the scriptures it cites, and its text "
        "(full, or a paragraph range). Use this to read a talk found by search before quoting it.",
        {
            "type": "object",
            "properties": {
                "talk_id": {"type": "string", "description": "e.g. 2024-10/15renlund"},
                "paragraph_start": {"type": "integer", "description": "Optional first paragraph index (0-based)"},
                "paragraph_end": {"type": "integer", "description": "Optional last paragraph index (inclusive)"},
                "include_notes": {"type": "boolean", "default": False},
            },
            "required": ["talk_id"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "get_scripture",
        "Look up the text of a scripture passage from the standard works (KJV Bible, Book of Mormon, "
        "Doctrine and Covenants, Pearl of Great Price), or of the KJV Apocrypha. Accepts references like "
        "'Alma 41:14', '3 Nephi 11:8–17', 'D&C 76:75', 'Joseph Smith—History 1:17', 'Tobit 4:15', "
        "'Ecclesiasticus 44:1–15', or a whole chapter 'Isaiah 53'.",
        {
            "type": "object",
            "properties": {"ref": {"type": "string"}},
            "required": ["ref"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "search_apocrypha",
        "Keyword search of the King James Apocrypha: 1 and 2 Esdras, Tobit, Judith, Rest of Esther, Wisdom of "
        "Solomon, Ecclesiasticus (Sirach), Baruch (chapter 6 is the Epistle of Jeremy), Song of the Three "
        "Children, Susanna, Bel and the Dragon, Prayer of Manasses, 1 and 2 Maccabees. Returns matching verses. "
        "Use KJV wording; put phrases in double quotes. Read surrounding verses with get_scripture.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 12, "minimum": 1, "maximum": 30},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "talks_citing_scripture",
        "Find General Conference talks that cite a scripture passage (or any verse of a chapter).",
        {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Scripture reference, e.g. 'Alma 41:14' or 'Alma 41'"},
                "limit": {"type": "integer", "default": 12, "minimum": 1, "maximum": 40},
            },
            "required": ["ref"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "search_josephus",
        "Search the works of Flavius Josephus (first-century Jewish historian; William Whiston's translation): "
        "Antiquities of the Jews, The Wars of the Jews, Against Apion, and his Life. Useful for historical "
        "background on the Old and New Testaments: the Herods, Pilate, the high priests, Pharisees, Sadducees "
        "and Essenes, the temple, John the Baptist, James, the fall of Jerusalem. Modes as in search_talks. "
        "Returns Whiston references (e.g. Antiquities 18.5.2) with snippets.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic, name, phrase or question"},
                "mode": {"type": "string", "enum": ["hybrid", "keyword", "semantic"], "default": "hybrid"},
                "work": {"type": "string", "enum": ["antiquities", "war", "apion", "life"],
                         "description": "Optional: limit to one work"},
                "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "get_josephus",
        "Read a passage of Josephus by reference. Whiston numbering: 'Antiquities 18.3.3', 'Wars 2.8.14', "
        "'Antiquities 1 Preface 2', 'Against Apion 2.17', 'Life 2'; a whole chapter: 'Antiquities 18.5'. "
        "Niese numbering (book.paragraph, used by scholarly editions) also works: 'Antiquities 18.116'. "
        "Read a passage before quoting or describing it.",
        {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "context": {"type": "integer", "default": 0, "minimum": 0, "maximum": 3,
                            "description": "Sections to include before and after"},
                "include_notes": {"type": "boolean", "default": False,
                                  "description": "Add Whiston's own 18th-century footnotes"},
            },
            "required": ["ref"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "talks_citing_talk",
        "Find talks that cite a given talk in their footnotes, and the talks that talk cites.",
        {
            "type": "object",
            "properties": {"talk_id": {"type": "string"}},
            "required": ["talk_id"],
            "additionalProperties": False,
        },
    ),
]


def _talk_line(t: dict, extra: str = "") -> str:
    return f"- [[talk:{t['id']}]] “{t['title']}” — {t['speaker']}, {t.get('conference') or ''}{extra}"


def _talk_ref(t: dict) -> dict:
    return {"type": "talk", "id": t["id"], "title": t["title"], "speaker": t["speaker"],
            "conference": t.get("conference")}


class ToolContext:
    def __init__(self, conn: sqlite3.Connection, engine: SearchEngine, current_talk_id: str):
        self.conn = conn
        self.engine = engine
        self.current_talk_id = current_talk_id

    def execute(self, name: str, args: dict) -> ToolResult:
        try:
            fn = getattr(self, f"tool_{name}")
        except AttributeError:
            return ToolResult(f"Unknown tool {name}", summary=f"Unknown tool {name}")
        try:
            return fn(**args)
        except TypeError as e:
            return ToolResult(f"Bad arguments for {name}: {e}", summary=f"{name}: bad arguments")
        except Exception as e:
            return ToolResult(f"Error in {name}: {type(e).__name__}: {e}", summary=f"{name} failed")

    # ---------------------------------------------------------------- tools

    def tool_search_talks(self, query: str, mode: str = "hybrid", year_from: int | None = None,
                          year_to: int | None = None, speaker: str | None = None, limit: int = 8) -> ToolResult:
        years = (year_from or 1971, year_to or 2100) if (year_from or year_to) else None
        limit = max(1, min(int(limit or 8), 20))
        hits = self.engine.search(query, mode, limit, years, speaker)
        talks = fetch_talks(self.conn, [h.talk_id for h in hits])
        lines, refs = [], []
        for h in hits:
            t = talks.get(h.talk_id)
            if not t:
                continue
            snip = " | ".join(s.replace("<mark>", "").replace("</mark>", "") for s in h.snippets[:2])
            tag = " (the assigned talk)" if h.talk_id == self.current_talk_id else ""
            lines.append(_talk_line(t, tag) + (f"\n  snippet: {snip}" if snip else ""))
            refs.append(_talk_ref(t))
        text = f"Search “{query}” ({mode}): {len(lines)} talks\n" + "\n".join(lines) if lines else \
            f"No talks matched “{query}”. Try different words or mode='semantic'."
        return ToolResult(text, refs, summary=f"Searched talks for “{query}” ({len(lines)} results)")

    def tool_get_talk(self, talk_id: str, paragraph_start: int | None = None,
                      paragraph_end: int | None = None, include_notes: bool = False) -> ToolResult:
        t = fetch_talks(self.conn, [talk_id]).get(talk_id)
        if not t:
            return ToolResult(f"No talk with id {talk_id}", summary=f"Talk {talk_id} not found")
        paras = self.conn.execute(
            "SELECT idx, text, is_note FROM paragraphs WHERE talk_id=? ORDER BY idx", (talk_id,)).fetchall()
        sel = [p for p in paras if (include_notes or not p["is_note"])
               and (paragraph_start is None or p["idx"] >= paragraph_start)
               and (paragraph_end is None or p["idx"] <= paragraph_end)]
        refs_rows = self.conn.execute(
            "SELECT DISTINCT book, chapter, verse_start, verse_end FROM scripture_refs WHERE talk_id=?",
            (talk_id,)).fetchall()
        cited = sorted({format_ref(r["book"], r["chapter"], r["verse_start"], r["verse_end"]) for r in refs_rows})
        head = (f"[[talk:{t['id']}]] “{t['title']}” — {t['speaker']}, {t.get('conference')}\n"
                f"Scriptures cited: {', '.join(cited) or 'none detected'}\n"
                f"Paragraphs {sel[0]['idx'] if sel else 0}–{sel[-1]['idx'] if sel else 0} of {len(paras)}:\n\n")
        body = "\n\n".join(f"[{p['idx']}] {p['text']}" for p in sel)
        return ToolResult(head + body, [_talk_ref(t)], summary=f"Read “{t['title']}”")

    def tool_get_scripture(self, ref: str) -> ToolResult:
        book, chapter, vs, ve = parse_single_ref(ref)
        verses = get_verses(self.conn, book, chapter, vs, ve)
        label = format_ref(book, chapter, vs, ve)
        if not verses:
            return ToolResult(f"No verses found for {label}", summary=f"{label}: not found")
        note = " (Apocrypha: not part of the standard works)" if BOOK_VOLUME.get(book) == APOCRYPHA else ""
        text = f"[[scripture:{label}]]{note}\n" + "\n".join(f"{v.verse} {v.text}" for v in verses)
        return ToolResult(text, [{"type": "scripture", "ref": label}], summary=f"Looked up {label}")

    def tool_search_apocrypha(self, query: str, limit: int = 12) -> ToolResult:
        limit = max(1, min(int(limit or 12), 30))
        match = fts_query(query)
        rows = search_verses(self.conn, match, limit, apocrypha=True) if match else []
        lines = [f"- [[scripture:{r['ref']}]] {r['text']}" for r in rows]
        refs = [{"type": "scripture", "ref": r["ref"]} for r in rows]
        text = (f"Apocrypha search “{query}”: {len(rows)} verses\n" + "\n".join(lines)) if rows else \
            f"No Apocrypha verses matched “{query}”. Try fewer or different (KJV) words."
        return ToolResult(text, refs, summary=f"Searched the Apocrypha for “{query}” ({len(rows)} results)")

    def tool_talks_citing_scripture(self, ref: str, limit: int = 12) -> ToolResult:
        book, chapter, vs, ve = parse_single_ref(ref)
        label = format_ref(book, chapter, vs, ve)
        res = talks_citing(self.conn, book, chapter, vs, ve, limit=max(1, min(int(limit or 12), 40)))
        lines = [_talk_line(t, f" ({t['mentions']} mention{'s' if t['mentions'] != 1 else ''})"
                            + (" (the assigned talk)" if t["id"] == self.current_talk_id else ""))
                 for t in res["talks"]]
        text = (f"{res['total']} talks cite {label}" + (f" (showing {len(lines)})" if res['total'] > len(lines) else "")
                + ":\n" + "\n".join(lines)) if lines else f"No talks cite {label}."
        refs = [{"type": "scripture", "ref": label}] + [_talk_ref(t) for t in res["talks"]]
        return ToolResult(text, refs, summary=f"Found {res['total']} talks citing {label}")

    def tool_search_josephus(self, query: str, mode: str = "hybrid", work: str | None = None,
                             limit: int = 8) -> ToolResult:
        limit = max(1, min(int(limit or 8), 20))
        hits = self.engine.josephus_search(query, mode, limit, work)
        ids = [int(h.talk_id) for h in hits]
        rows = {r["id"]: r for r in self.conn.execute(
            f"SELECT * FROM josephus WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
        lines, refs = [], []
        for h in hits:
            r = rows.get(int(h.talk_id))
            if r is None:
                continue
            lab = jos.row_label(r)
            snip = " | ".join(x.replace("<mark>", "").replace("</mark>", "") for x in h.snippets[:2])
            title = f" — {r['chapter_title']}" if r["chapter_title"] else ""
            lines.append(f"- [[josephus:{lab}]] (Niese {jos.row_niese(r)}){title}\n  snippet: {snip}")
            refs.append({"type": "josephus", "ref": lab})
        text = (f"Josephus search “{query}” ({mode}): {len(lines)} passages\n" + "\n".join(lines)) if lines else \
            f"No Josephus passages matched “{query}”. Try other words (Whiston's English is archaic) or mode='semantic'."
        return ToolResult(text, refs, summary=f"Searched Josephus for “{query}” ({len(lines)} results)")

    def tool_get_josephus(self, ref: str, context: int = 0, include_notes: bool = False) -> ToolResult:
        rows = jos.lookup(self.conn, ref)
        if not rows:
            return ToolResult(f"No Josephus passage found for “{ref}”. Use Whiston form like 'Antiquities 18.3.3' "
                              "or search_josephus.", summary=f"{ref}: not found")
        context = max(0, min(int(context or 0), 3))
        before, after = [], []
        for _ in range(context):
            r = jos.neighbor(self.conn, before[0] if before else rows[0], -1)
            if r is not None:
                before.insert(0, r)
            r = jos.neighbor(self.conn, after[-1] if after else rows[-1], 1)
            if r is not None:
                after.append(r)
        work = jos.WORKS_BY_KEY[rows[0]["work"]]
        lab = jos.range_label(rows)
        ids = {r["id"] for r in rows}
        out = [f"[[josephus:{lab}]] {work.title}, Niese {jos.range_niese(rows)}"]
        if rows[0]["chapter_title"]:
            out.append(f"Chapter: {rows[0]['chapter_title']}")
        out.append("")
        for r in before + rows + after:
            tag = "" if r["id"] in ids else " (context)"
            out.append(f"[{jos.row_label(r)}]{tag} {r['text']}")
            if include_notes:
                for n in json.loads(r["notes"] or "[]"):
                    out.append(f"  Whiston's note: {n}")
            out.append("")
        return ToolResult("\n".join(out).strip(), [{"type": "josephus", "ref": lab}], summary=f"Read Josephus, {lab}")

    def tool_talks_citing_talk(self, talk_id: str) -> ToolResult:
        t = fetch_talks(self.conn, [talk_id]).get(talk_id)
        if not t:
            return ToolResult(f"No talk with id {talk_id}", summary=f"Talk {talk_id} not found")
        by = [r["talk_id"] for r in self.conn.execute(
            "SELECT DISTINCT talk_id FROM talk_refs WHERE cited_talk_id=?", (talk_id,))]
        cites = [r["cited_talk_id"] for r in self.conn.execute(
            "SELECT DISTINCT cited_talk_id FROM talk_refs WHERE talk_id=? AND cited_talk_id IS NOT NULL", (talk_id,))]
        talks = fetch_talks(self.conn, by + cites)
        out = [f"Talks citing “{t['title']}”: {len(by)}"]
        out += [_talk_line(talks[i]) for i in by if i in talks]
        out.append(f"\nTalks cited by “{t['title']}”: {len(cites)}")
        out += [_talk_line(talks[i]) for i in cites if i in talks]
        refs = [_talk_ref(talks[i]) for i in by + cites if i in talks]
        return ToolResult("\n".join(out), refs, summary=f"Citation links for “{t['title']}”")
