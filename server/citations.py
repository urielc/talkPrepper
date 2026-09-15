"""Parsers for citations found in talk text.

* ``parse_scripture_refs``: scripture references such as ``Alma 41:14``,
  ``3 Nephi 11:8–17; 27:20``, ``Matthew 5:3, 5, 7–9``, ``Doctrine and
  Covenants 76:75; 58:27``, ``Joseph Smith—History 1:17``, ``John 3`` and
  ``see also verses 16–21`` (attached to the previous book/chapter).
* ``parse_talk_citations``: footnote citations of other conference talks such
  as ``Russell M. Nelson, “Think Celestial!,” Liahona, Nov. 2023, 117.``
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .scriptures import BOOK_ALIASES, canonical_book

DASH = "[-–—]"
NUM = r"\d{1,3}"
# one verse or a range: 7, 7–9
VERSE_ITEM = rf"{NUM}(?:\s*{DASH}\s*{NUM})?"
# a list of verse items: 3, 5, 7–9
VERSE_LIST = rf"{VERSE_ITEM}(?:\s*,\s*{VERSE_ITEM})*"

# Longest aliases first so "1 Nephi" wins over "Nephi"-like prefixes and
# "Joseph Smith—History" over "Joseph Smith".
_ALIASES_SORTED = sorted(BOOK_ALIASES.keys(), key=len, reverse=True)
_BOOK_RE = "|".join(re.escape(a) for a in _ALIASES_SORTED)

# Book + chapter, optional verses. Chapter/verse separator may carry spaces
# around the colon in badly extracted text.
REF_RE = re.compile(
    rf"(?<![A-Za-z])(?P<book>{_BOOK_RE})\.?\s+(?P<chapter>{NUM})"
    rf"(?:\s*:\s*(?P<verses>{VERSE_LIST}))?(?![\d:])",
    re.IGNORECASE,
)
# Continuation after a full reference: "; 27:20" or "; 27:24–31" (same book)
CHAIN_CHAPTER_RE = re.compile(rf"\s*;\s*(?P<chapter>{NUM})\s*:\s*(?P<verses>{VERSE_LIST})(?![\d:])")
# "see also verses 16–21" / "verse 5" attaching to the last (book, chapter)
VERSES_RE = re.compile(rf"\bverses?\s+(?P<verses>{VERSE_LIST})(?![\d:])", re.IGNORECASE)
JST_RE = re.compile(r"(?:Joseph Smith Translation|JST)\s*,?\s*$", re.IGNORECASE)
BOOK_OF_RE = re.compile(r"\b(?:book|Book)\s+of\s*$")


@dataclass
class ScriptureRef:
    book: str            # canonical title, e.g. 'Alma'
    chapter: int
    verse_start: int | None
    verse_end: int | None
    raw: str
    start: int           # char offsets in the source text
    end: int

    def to_dict(self) -> dict:
        from .scriptures import format_ref, display_book
        return {
            "book": display_book(self.book),
            "chapter": self.chapter,
            "verse_start": self.verse_start,
            "verse_end": self.verse_end,
            "ref": format_ref(self.book, self.chapter, self.verse_start, self.verse_end),
            "raw": self.raw,
            "start": self.start,
            "end": self.end,
        }


def _split_verses(verses: str) -> list[tuple[int, int | None]]:
    out = []
    for item in re.split(r"\s*,\s*", verses.strip()):
        m = re.fullmatch(rf"({NUM})(?:\s*{DASH}\s*({NUM}))?", item)
        if not m:
            continue
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else None
        if b is not None and b < a:
            b = None
        out.append((a, b))
    return out


def _emit(refs: list[ScriptureRef], text: str, book: str, chapter: int,
          verses: str | None, start: int, end: int) -> None:
    if verses is None:
        refs.append(ScriptureRef(book, chapter, None, None, text[start:end], start, end))
        return
    for a, b in _split_verses(verses):
        refs.append(ScriptureRef(book, chapter, a, b, text[start:end], start, end))


def parse_scripture_refs(text: str) -> list[ScriptureRef]:
    refs: list[ScriptureRef] = []
    last: tuple[str, int] | None = None   # (book, chapter) for "verses …" continuation
    pos = 0
    n = len(text)
    while pos < n:
        m = REF_RE.search(text, pos)
        v = VERSES_RE.search(text, pos)
        # Handle a bare "verses 16–21" that comes before the next full ref.
        if v and (not m or v.start() < m.start()):
            if last is not None:
                _emit(refs, text, last[0], last[1], v.group("verses"), v.start(), v.end())
            pos = v.end()
            continue
        if not m:
            break
        book = canonical_book(m.group("book"))
        if book is None:
            pos = m.end()
            continue
        before = text[max(0, m.start() - 40):m.start()]
        # Skip "Joseph Smith Translation, Matthew 7:1–2" (not in the dataset)
        # and "Book of Mormon" followed by a number that isn't a reference.
        if JST_RE.search(before) or (book == "Mormon" and BOOK_OF_RE.search(before)):
            pos = m.end()
            continue
        chapter = int(m.group("chapter"))
        verses = m.group("verses")
        # Chapter-only mention: require the book to be plausible as a bare
        # reference (avoid "Job 3" in prose like "his job 3 years").
        if verses is None and m.group("book").lower() in _PROSE_RISKY:
            pos = m.end()
            continue
        _emit(refs, text, book, chapter, verses, m.start(), m.end())
        last = (book, chapter)
        pos = m.end()
        # Chained chapters of the same book: "; 27:20; 28:1–3"
        while True:
            c = CHAIN_CHAPTER_RE.match(text, pos)
            if not c:
                break
            # If a new book name starts right after the semicolon, stop chaining.
            nxt = REF_RE.match(text, pos + len(c.group(0)) - len(c.group(0).lstrip(" ;")))
            if nxt and nxt.start() == c.start("chapter"):
                break
            ch = int(c.group("chapter"))
            _emit(refs, text, book, ch, c.group("verses"), c.start("chapter"), c.end())
            last = (book, ch)
            pos = c.end()
    return refs


# Book names that are also ordinary words / common nouns; only accept them
# when a verse is present.
_PROSE_RISKY = {"job", "acts", "numbers", "judges", "mark", "james", "john", "jude",
                "ruth", "amos", "joel", "jonah", "micah", "nahum", "hosea", "esther",
                "ezra", "titus", "philemon", "enos", "jarom", "omni", "ether", "moses",
                "abraham", "jacob", "mormon", "alma", "helaman", "mosiah", "moroni",
                "luke", "genesis", "exodus", "revelation", "revelations", "psalm", "psalms",
                "song.", "ps.", "prov.", "eccl.", "lam.", "dan.", "gen.", "ex.", "lev.",
                "num.", "deut.", "josh.", "judg.", "matt.", "rom.", "gal.", "eph.", "col.",
                "heb.", "rev.", "hel.", "morm.", "moro.", "abr.", "isa.", "jer.", "ezek."}


# ---------------------------------------------------------------- talk citations

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_RE = r"(?P<month>Jan|Feb|Mar|Apr|May|June?|July?|Aug|Sept?|Oct|Nov|Dec)\.?"
TALK_CITE_RE = re.compile(
    r"[“\"](?P<title>[^”\"]{3,160}?)[,.]?[”\"]\s*,?\s*(?:in\s+)?"
    r"(?P<pub>Ensign or Liahona|Liahona|Ensign|Conference Report|general conference|"
    r"Improvement Era|New Era|Ensign\s+or\s+Liahona)\b[^“”\"]{0,60}?"
    rf"{MONTH_RE}\s+(?P<year>19\d\d|20\d\d)",
    re.IGNORECASE,
)
# "in Conference Report, Apr. 1965, 12" without a quoted title
CONF_REPORT_RE = re.compile(
    rf"\bConference Report,\s*{MONTH_RE}\s+(?P<year>19\d\d|20\d\d)", re.IGNORECASE
)


@dataclass
class TalkCitation:
    title: str | None
    year: int
    month: int | None            # publication month (May/Nov for Liahona)
    conference_month: int | None  # 4 or 10 when the citation points at a conference
    raw: str
    start: int
    end: int


def _conference_month(pub: str, month: int | None) -> int | None:
    if month in (4, 5):
        return 4
    if month in (10, 11):
        return 10
    return None


def parse_talk_citations(text: str) -> list[TalkCitation]:
    out: list[TalkCitation] = []
    for m in TALK_CITE_RE.finditer(text):
        month = MONTHS.get(m.group("month").lower().rstrip("."))
        out.append(TalkCitation(
            title=m.group("title").strip(),
            year=int(m.group("year")),
            month=month,
            conference_month=_conference_month(m.group("pub"), month),
            raw=m.group(0), start=m.start(), end=m.end(),
        ))
    if not out:
        for m in CONF_REPORT_RE.finditer(text):
            month = MONTHS.get(m.group("month").lower().rstrip("."))
            out.append(TalkCitation(None, int(m.group("year")), month,
                                    _conference_month("Conference Report", month),
                                    m.group(0), m.start(), m.end()))
    return out


def normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[“”\"'‘’.,:;!?()\[\]—–-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()
