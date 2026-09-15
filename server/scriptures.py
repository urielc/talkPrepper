"""Standard works: book table, reference normalisation, DB loading and lookup.

The verse data comes from the public-domain beandog/lds-scriptures JSON export
(one flat record per verse). Book titles in that dataset are the canonical
names used throughout this app (``talks`` cite them in many spellings; see
``BOOK_ALIASES``).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx

from .config import SCRIPTURES_JSON, SCRIPTURES_URL

# (canonical title, dataset short title, volume, extra aliases used in talks)
BOOKS: list[tuple[str, str, str, tuple[str, ...]]] = [
    # Old Testament
    ("Genesis", "Gen.", "Old Testament", ()),
    ("Exodus", "Ex.", "Old Testament", ("Exod.",)),
    ("Leviticus", "Lev.", "Old Testament", ()),
    ("Numbers", "Num.", "Old Testament", ()),
    ("Deuteronomy", "Deut.", "Old Testament", ()),
    ("Joshua", "Josh.", "Old Testament", ()),
    ("Judges", "Judg.", "Old Testament", ()),
    ("Ruth", "Ruth", "Old Testament", ()),
    ("1 Samuel", "1 Sam.", "Old Testament", ()),
    ("2 Samuel", "2 Sam.", "Old Testament", ()),
    ("1 Kings", "1 Kgs.", "Old Testament", ()),
    ("2 Kings", "2 Kgs.", "Old Testament", ()),
    ("1 Chronicles", "1 Chr.", "Old Testament", ("1 Chron.",)),
    ("2 Chronicles", "2 Chr.", "Old Testament", ("2 Chron.",)),
    ("Ezra", "Ezra", "Old Testament", ()),
    ("Nehemiah", "Neh.", "Old Testament", ()),
    ("Esther", "Esth.", "Old Testament", ()),
    ("Job", "Job", "Old Testament", ()),
    ("Psalms", "Ps.", "Old Testament", ("Psalm", "Pss.")),
    ("Proverbs", "Prov.", "Old Testament", ()),
    ("Ecclesiastes", "Eccl.", "Old Testament", ()),
    ("Song of Solomon", "Song.", "Old Testament", ("Song of Sol.",)),
    ("Isaiah", "Isa.", "Old Testament", ()),
    ("Jeremiah", "Jer.", "Old Testament", ()),
    ("Lamentations", "Lam.", "Old Testament", ()),
    ("Ezekiel", "Ezek.", "Old Testament", ()),
    ("Daniel", "Dan.", "Old Testament", ()),
    ("Hosea", "Hosea", "Old Testament", ()),
    ("Joel", "Joel", "Old Testament", ()),
    ("Amos", "Amos", "Old Testament", ()),
    ("Obadiah", "Obad.", "Old Testament", ()),
    ("Jonah", "Jonah", "Old Testament", ()),
    ("Micah", "Micah", "Old Testament", ()),
    ("Nahum", "Nahum", "Old Testament", ()),
    ("Habakkuk", "Hab.", "Old Testament", ()),
    ("Zephaniah", "Zeph.", "Old Testament", ()),
    ("Haggai", "Hag.", "Old Testament", ()),
    ("Zechariah", "Zech.", "Old Testament", ()),
    ("Malachi", "Mal.", "Old Testament", ()),
    # New Testament
    ("Matthew", "Matt.", "New Testament", ()),
    ("Mark", "Mark", "New Testament", ()),
    ("Luke", "Luke", "New Testament", ()),
    ("John", "John", "New Testament", ()),
    ("Acts", "Acts", "New Testament", ()),
    ("Romans", "Rom.", "New Testament", ()),
    ("1 Corinthians", "1 Cor.", "New Testament", ()),
    ("2 Corinthians", "2 Cor.", "New Testament", ()),
    ("Galatians", "Gal.", "New Testament", ()),
    ("Ephesians", "Eph.", "New Testament", ()),
    ("Philippians", "Philip.", "New Testament", ("Phil.",)),
    ("Colossians", "Col.", "New Testament", ()),
    ("1 Thessalonians", "1 Thes.", "New Testament", ("1 Thess.",)),
    ("2 Thessalonians", "2 Thes.", "New Testament", ("2 Thess.",)),
    ("1 Timothy", "1 Tim.", "New Testament", ()),
    ("2 Timothy", "2 Tim.", "New Testament", ()),
    ("Titus", "Titus", "New Testament", ()),
    ("Philemon", "Philem.", "New Testament", ()),
    ("Hebrews", "Heb.", "New Testament", ()),
    ("James", "James", "New Testament", ()),
    ("1 Peter", "1 Pet.", "New Testament", ()),
    ("2 Peter", "2 Pet.", "New Testament", ()),
    ("1 John", "1 Jn.", "New Testament", ()),
    ("2 John", "2 Jn.", "New Testament", ()),
    ("3 John", "3 Jn.", "New Testament", ()),
    ("Jude", "Jude", "New Testament", ()),
    ("Revelation", "Rev.", "New Testament", ("Revelations",)),
    # Book of Mormon
    ("1 Nephi", "1 Ne.", "Book of Mormon", ()),
    ("2 Nephi", "2 Ne.", "Book of Mormon", ()),
    ("Jacob", "Jacob", "Book of Mormon", ()),
    ("Enos", "Enos", "Book of Mormon", ()),
    ("Jarom", "Jarom", "Book of Mormon", ()),
    ("Omni", "Omni", "Book of Mormon", ()),
    ("Words of Mormon", "W of M", "Book of Mormon", ()),
    ("Mosiah", "Mosiah", "Book of Mormon", ()),
    ("Alma", "Alma", "Book of Mormon", ()),
    ("Helaman", "Hel.", "Book of Mormon", ()),
    ("3 Nephi", "3 Ne.", "Book of Mormon", ()),
    ("4 Nephi", "4 Ne.", "Book of Mormon", ()),
    ("Mormon", "Morm.", "Book of Mormon", ()),
    ("Ether", "Ether", "Book of Mormon", ()),
    ("Moroni", "Moro.", "Book of Mormon", ()),
    # Doctrine and Covenants
    ("Doctrine and Covenants", "D&C", "Doctrine and Covenants", ("D & C", "D&amp;C")),
    # Pearl of Great Price
    ("Moses", "Moses", "Pearl of Great Price", ()),
    ("Abraham", "Abr.", "Pearl of Great Price", ()),
    ("Joseph Smith--Matthew", "JS-M", "Pearl of Great Price",
     ("Joseph Smith—Matthew", "Joseph Smith–Matthew", "Joseph Smith-Matthew", "JS—M", "JS–M")),
    ("Joseph Smith--History", "JS-H", "Pearl of Great Price",
     ("Joseph Smith—History", "Joseph Smith–History", "Joseph Smith-History", "JS—H", "JS–H")),
    ("Articles of Faith", "A of F", "Pearl of Great Price", ()),
]

# Display names: the dataset uses '--' where the Church uses an em dash.
DISPLAY_NAME = {
    "Joseph Smith--Matthew": "Joseph Smith—Matthew",
    "Joseph Smith--History": "Joseph Smith—History",
}

BOOK_ORDER = {title: i for i, (title, _, _, _) in enumerate(BOOKS)}
BOOK_VOLUME = {title: vol for title, _, vol, _ in BOOKS}
BOOK_SHORT = {title: short for title, short, _, _ in BOOKS}

BOOK_ALIASES: dict[str, str] = {}
for _title, _short, _vol, _extra in BOOKS:
    for alias in (_title, _short, *_extra, DISPLAY_NAME.get(_title, _title)):
        BOOK_ALIASES[alias.lower()] = _title


def canonical_book(name: str) -> str | None:
    """Map any accepted spelling/abbreviation to the canonical book title."""
    key = name.strip().lower()
    if key in BOOK_ALIASES:
        return BOOK_ALIASES[key]
    if key.endswith(".") and key[:-1] in BOOK_ALIASES:
        return BOOK_ALIASES[key[:-1]]
    if key + "." in BOOK_ALIASES:
        return BOOK_ALIASES[key + "."]
    return None


def display_book(book: str) -> str:
    return DISPLAY_NAME.get(book, book)


def format_ref(book: str, chapter: int, verse_start: int | None, verse_end: int | None) -> str:
    s = f"{display_book(book)} {chapter}"
    if verse_start is not None:
        s += f":{verse_start}"
        if verse_end is not None and verse_end != verse_start:
            s += f"–{verse_end}"
    return s


@dataclass
class Verse:
    book: str
    chapter: int
    verse: int
    text: str

    def to_dict(self) -> dict:
        return {
            "book": display_book(self.book),
            "chapter": self.chapter,
            "verse": self.verse,
            "text": self.text,
            "ref": format_ref(self.book, self.chapter, self.verse, None),
        }


# ---------------------------------------------------------------- download / load

def download_scriptures(dest: Path = SCRIPTURES_JSON, force: bool = False) -> Path:
    """Fetch the verse JSON if not already present. Validates before writing."""
    if dest.exists() and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        r = client.get(SCRIPTURES_URL)
        r.raise_for_status()
    data = json.loads(r.text)
    if not isinstance(data, list) or len(data) < 40000 or "scripture_text" not in data[0]:
        raise RuntimeError("Downloaded scripture file does not look like the expected verse list")
    dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return dest


def iter_verses(path: Path = SCRIPTURES_JSON) -> Iterable[dict]:
    with open(path, encoding="utf-8") as f:
        for rec in json.load(f):
            yield rec


def load_scriptures_into_db(conn: sqlite3.Connection, path: Path = SCRIPTURES_JSON) -> int:
    """(Re)populate the scriptures table and its FTS index. Returns verse count."""
    conn.execute("DELETE FROM scriptures")
    rows = [
        (rec["volume_title"], rec["book_title"], rec["book_short_title"],
         int(rec["chapter_number"]), int(rec["verse_number"]), rec["scripture_text"])
        for rec in iter_verses(path)
    ]
    conn.executemany(
        "INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) VALUES(?,?,?,?,?,?)",
        rows,
    )
    conn.execute("INSERT INTO scriptures_fts(scriptures_fts) VALUES('rebuild')")
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------- lookup

def get_verses(conn: sqlite3.Connection, book: str, chapter: int,
               verse_start: int | None = None, verse_end: int | None = None) -> list[Verse]:
    if verse_start is None:
        rows = conn.execute(
            "SELECT book, chapter, verse, text FROM scriptures WHERE book=? AND chapter=? ORDER BY verse",
            (book, chapter),
        ).fetchall()
    else:
        ve = verse_end if verse_end is not None else verse_start
        rows = conn.execute(
            "SELECT book, chapter, verse, text FROM scriptures "
            "WHERE book=? AND chapter=? AND verse BETWEEN ? AND ? ORDER BY verse",
            (book, chapter, verse_start, ve),
        ).fetchall()
    return [Verse(r["book"], r["chapter"], r["verse"], r["text"]) for r in rows]


def chapter_count(conn: sqlite3.Connection, book: str) -> int:
    row = conn.execute("SELECT MAX(chapter) FROM scriptures WHERE book=?", (book,)).fetchone()
    return int(row[0] or 0)


def search_verses(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict]:
    """Full-text search over verse text. Returns dicts with highlighted snippets."""
    rows = conn.execute(
        "SELECT s.book, s.chapter, s.verse, s.text, "
        "snippet(scriptures_fts, 0, '<mark>', '</mark>', '…', 24) AS snippet, "
        "bm25(scriptures_fts) AS score "
        "FROM scriptures_fts JOIN scriptures s ON s.id = scriptures_fts.rowid "
        "WHERE scriptures_fts MATCH ? ORDER BY score LIMIT ?",
        (query, limit),
    ).fetchall()
    return [
        {
            "ref": format_ref(r["book"], r["chapter"], r["verse"], None),
            "book": display_book(r["book"]),
            "chapter": r["chapter"],
            "verse": r["verse"],
            "text": r["text"],
            "snippet": r["snippet"],
            "score": -float(r["score"]),
        }
        for r in rows
    ]
