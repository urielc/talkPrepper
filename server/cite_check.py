"""Check the assistant's citations against the library.

The model is told to cite only what it read or what a tool returned, but nothing
enforces that: a ``[[talk:2019-04/22smith]]`` naming no real talk renders exactly
like a good one. These checks answer "does this thing exist here", so the UI can
mark what does not.

A talk id must be a row in ``talks``. A scripture only has to resolve to real
verses — the whole canon is on disk, so a passage the model recalled without
calling a tool is still verifiable, and is allowed.
"""

from __future__ import annotations

import re
import sqlite3

from .citations import parse_ref
from .scriptures import format_ref, verses_exist

# Same shape the client parses in web/src/utils/markdown.ts.
CITE_RE = re.compile(r"\[\[(talk|scripture):([^\]]+)\]\]")

# Longest citation worth holding a partial match open for.
MAX_CITE = 200


def cite_key(kind: str, value: str) -> str:
    return f"{kind}:{value}"


class CitationChecker:
    """Existence checks, memoised for the life of one request."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._cache: dict[tuple[str, str], dict] = {}

    def check(self, kind: str, value: str) -> dict:
        key = (kind, value.strip())
        hit = self._cache.get(key)
        if hit is None:
            hit = self._cache[key] = self._check(kind, key[1])
        return hit

    def _check(self, kind: str, value: str) -> dict:
        if kind == "talk":
            row = self.conn.execute("SELECT title FROM talks WHERE id=?", (value,)).fetchone()
            return {"ok": row is not None, "label": row["title"] if row else None}
        if kind == "scripture":
            parsed = parse_ref(value)
            if parsed is None:
                return {"ok": False, "label": None}
            book, chapter, vs, ve = parsed
            if not verses_exist(self.conn, book, chapter, vs, ve):
                return {"ok": False, "label": None}
            return {"ok": True, "label": format_ref(book, chapter, vs, ve)}
        return {"ok": False, "label": None}


def scan(text: str, checker: CitationChecker) -> dict[str, dict]:
    """Every citation in a finished piece of text, keyed 'kind:value'."""
    return {cite_key(m.group(1), m.group(2).strip()): checker.check(m.group(1), m.group(2))
            for m in CITE_RE.finditer(text)}


class StreamScanner:
    """Finds citations in text that arrives a few characters at a time.

    ``feed`` returns one entry per citation the moment it is complete, and never
    twice. A token split across deltas is held back: scanning resumes at the last
    unclosed ``[[`` so the rest of it is seen when it arrives.
    """

    def __init__(self, checker: CitationChecker):
        self.checker = checker
        self.buf = ""
        self.pos = 0          # everything before this has been scanned
        self.seen: set[str] = set()

    def feed(self, text: str) -> list[dict]:
        self.buf += text
        out = []
        end = len(self.buf)
        for m in CITE_RE.finditer(self.buf, self.pos):
            kind, value = m.group(1), m.group(2).strip()
            key = cite_key(kind, value)
            self.pos = m.end()
            if key in self.seen:
                continue
            self.seen.add(key)
            out.append({"key": key, "kind": kind, "value": value, **self.checker.check(kind, value)})
        # A citation still arriving must be rescanned once the rest of it lands, so
        # the checkpoint backs up to the last "[" — even a lone one, which may be the
        # first half of a "[[" whose second half is still in flight. Looking no
        # further back than MAX_CITE keeps an ordinary "[" in the prose (a Markdown
        # link, say) from pinning the scan to the start of the message.
        tail = self.buf.rfind("[", max(self.pos, end - MAX_CITE))
        if tail == -1:
            self.pos = end
        else:
            while tail > self.pos and self.buf[tail - 1] == "[":
                tail -= 1
            self.pos = tail
        return out
