"""The works of Flavius Josephus: download, parsing, DB loading, references and lookup.

The text is William Whiston's 1737 translation (public domain) as encoded by the
Perseus Digital Library (TEI XML, CC BY-SA 4.0), fetched from the
PerseusDL/canonical-greekLit repository. Perseus marks both citation systems:

* Niese numbering (``Antiquities 18.63``): ``<div subtype="book|section" n=…>``.
  A section div's ``n`` is where it starts; it runs to the next div's ``n`` - 1.
* Whiston numbering (``Antiquities 18.3.3``): ``<milestone unit="Whiston_chapter">``
  and ``<milestone unit="Whiston_section">``, which can fall mid-div.

One stored row is one Whiston section, the unit most popular editions (and most
Church materials) cite, with the Niese range it covers kept alongside.
"""

from __future__ import annotations

import json
import re
import sqlite3
import xml.etree.ElementTree as ET  # types only; parsing goes through defusedxml
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from defusedxml import ElementTree as DET

from .config import JOSEPHUS_DIR

PERSEUS_BASE = "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/master/data/tlg0526"
TEI = "{http://www.tei-c.org/ns/1.0}"

ATTRIBUTION = ("Translated by William Whiston (1737). Text from the Perseus Digital Library, "
               "Tufts University, CC BY-SA 4.0.")


@dataclass(frozen=True)
class Work:
    key: str
    title: str          # full title
    short: str          # used in citations: "Antiquities 18.3.3"
    perseus: str        # tlg0526.<id>
    books: bool         # divided into books
    chapters: bool      # Whiston chapters inside books
    aliases: tuple[str, ...]


WORKS: list[Work] = [
    Work("antiquities", "Antiquities of the Jews", "Antiquities", "tlg001", True, True,
         ("antiquities", "antiquities of the jews", "jewish antiquities", "ant", "antiq", "aj", "a.j")),
    Work("war", "The Wars of the Jews", "Wars", "tlg004", True, True,
         ("wars", "war", "wars of the jews", "jewish war", "the jewish war", "the wars of the jews",
          "bj", "b.j", "j.w", "jw")),
    Work("apion", "Against Apion", "Against Apion", "tlg003", True, False,
         ("against apion", "apion", "contra apionem", "ag. ap", "ag ap", "c. ap", "c ap", "ap")),
    Work("life", "The Life of Flavius Josephus", "Life", "tlg002", False, False,
         ("life", "life of josephus", "the life of flavius josephus", "life of flavius josephus",
          "vita", "autobiography")),
]
WORKS_BY_KEY = {w.key: w for w in WORKS}
_ALIASES = sorted(((a, w) for w in WORKS for a in w.aliases), key=lambda x: -len(x[0]))


def xml_path(work: Work, data_dir: Path = JOSEPHUS_DIR) -> Path:
    return data_dir / f"{work.key}.xml"


def download_josephus(data_dir: Path = JOSEPHUS_DIR, force: bool = False) -> list[Path]:
    """Fetch the four TEI files if not already present. Validates before writing."""
    data_dir.mkdir(parents=True, exist_ok=True)
    out = []
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for w in WORKS:
            dest = xml_path(w, data_dir)
            out.append(dest)
            if dest.exists() and not force:
                continue
            r = client.get(f"{PERSEUS_BASE}/{w.perseus}/tlg0526.{w.perseus}.perseus-eng2.xml")
            r.raise_for_status()
            if "Whiston_section" not in r.text or "William Whiston" not in r.text:
                raise RuntimeError(f"Downloaded {w.title} does not look like the Perseus Whiston TEI file")
            dest.write_text(r.text, encoding="utf-8")
    return out


def have_josephus(data_dir: Path = JOSEPHUS_DIR) -> bool:
    return all(xml_path(w, data_dir).exists() for w in WORKS)


# ---------------------------------------------------------------- parsing

@dataclass
class Section:
    work: str
    book: int            # 0 for Life
    chapter: int         # Whiston chapter; 0 = preface, or no chapters (Apion, Life)
    section: int         # Whiston section
    niese_start: int
    niese_end: int
    chapter_title: str = ""
    paragraphs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    run: int = field(default=0, repr=False)   # which chapter milestone opened it

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


def _clean(s: str) -> str:
    return " ".join(s.split())


def _int(n: str | None, default: int = 0) -> int:
    m = re.match(r"\d+", n or "")
    return int(m.group()) if m else default


class _Parser:
    """Walks the TEI body in document order, cutting text at Whiston milestones."""

    def __init__(self, work: Work):
        self.work = work
        self.out: list[Section] = []
        self.book = 0
        self.chapter = 0
        self.chapter_title = ""
        self.want_title = False   # the next <head> names the chapter just opened
        self.niese = 0            # Niese section div we are in
        self.divs: dict[int, list[int]] = {}   # book -> Niese div starts in order
        self.last_div: dict[int, int] = {}     # id(Section) -> last Niese div it reached
        self.cur: Section | None = None
        self.para: list[str] = []
        self.run = 0

    def _flush_para(self) -> None:
        text = _clean("".join(self.para))
        self.para = []
        if text and self.cur is not None:
            self.cur.paragraphs.append(text)

    def _text(self, s: str | None) -> None:
        if s:
            self.para.append(s)
            # A section reaches a div only once it has text there: a milestone that
            # opens a div belongs to the section it starts, not the one before.
            if self.cur is not None and s.strip():
                self.last_div[id(self.cur)] = self.niese

    def walk(self, el: ET.Element) -> None:
        tag = el.tag.replace(TEI, "")
        if tag == "note":
            note = _clean("".join(el.itertext()))
            if note and self.cur is not None:
                self.cur.notes.append(note)
            self._text(el.tail)
            return
        if tag == "milestone":
            unit, n = el.get("unit"), el.get("n") or ""
            if unit == "Whiston_chapter":
                self._flush_para()
                preface = n.startswith("pr")
                self.chapter = 0 if preface else _int(n)
                self.chapter_title = "Preface" if preface else ""
                self.want_title = not preface
                self.run += 1
            elif unit == "Whiston_section":
                self._flush_para()
                self.cur = Section(self.work.key, self.book, self.chapter, _int(n, 1),
                                   self.niese, self.niese, self.chapter_title, run=self.run)
                self.last_div[id(self.cur)] = self.niese
                self.out.append(self.cur)
            self._text(el.tail)
            return
        if tag == "head":
            # Book heads are skipped; a head right after a chapter milestone titles it.
            if self.want_title:
                self.chapter_title = _chapter_title(_clean("".join(_itertext_no_notes(el))))
                self.want_title = False
                if self.cur is not None and self.cur.chapter == self.chapter and not self.cur.paragraphs:
                    self.cur.chapter_title = self.chapter_title
            self._text(el.tail)
            return
        if tag == "lb":
            self.para.append(" ")
            self._text(el.tail)
            return
        if tag == "div":
            sub = el.get("subtype")
            if sub == "book":
                self._flush_para()
                self.book = _int(el.get("n"))
                self.chapter, self.chapter_title, self.want_title = 0, "", False
                self.cur = None
            elif sub == "section":
                self.niese = _int(el.get("n"))
                self.divs.setdefault(self.book, []).append(self.niese)
        if tag == "p":
            self._flush_para()
        self._text(el.text)
        for child in el:
            self.walk(child)
        if tag == "p":
            self._flush_para()
        self._text(el.tail)

    def finish(self) -> list[Section]:
        self._flush_para()
        if self.work.chapters:
            _repair_chapters(self.out)
        # A Niese div runs until the next div starts. A section ends where the next
        # one starts: in a fresh div (end = that div - 1) or mid-div (they share it).
        for i, s in enumerate(self.out):
            last = self.last_div[id(s)]
            nxt = self.out[i + 1] if i + 1 < len(self.out) else None
            if nxt is not None and nxt.book == s.book and nxt.niese_start == last:
                s.niese_end = last
            else:
                later = [d for d in self.divs.get(s.book, []) if d > last]
                s.niese_end = later[0] - 1 if later else last
            s.niese_end = max(s.niese_end, s.niese_start)
        return [s for s in self.out if s.paragraphs]


def _itertext_no_notes(el: ET.Element):
    if el.tag.replace(TEI, "") == "note":
        return
    if el.text:
        yield el.text
    for c in el:
        yield from _itertext_no_notes(c)
        if c.tail:
            yield c.tail


def _repair_chapters(secs: list[Section]) -> None:
    """Fix chapter milestones the source numbers out of sequence. In Antiquities 5 a
    chapter 7 is tagged 8 (so 8 appears twice) and in Antiquities 13 a chapter 4 is
    tagged 7. A run whose number breaks the sequence, when the run after it carries
    on from the expected number (or repeats it), takes the expected number."""
    runs: list[tuple[int, int, int]] = []          # (book, run, chapter) in order
    for s in secs:
        if not runs or runs[-1][1] != s.run:
            runs.append((s.book, s.run, s.chapter))
    fixed: dict[int, int] = {}
    for i in range(1, len(runs)):
        book, run, ch = runs[i]
        pbook, _prun, pch = runs[i - 1]
        pch = fixed.get(runs[i - 1][1], pch)
        if book != pbook or ch == pch + 1 or pch == 0 and ch == 1:
            continue
        nxt = runs[i + 1] if i + 1 < len(runs) and runs[i + 1][0] == book else None
        if nxt is not None and (nxt[2] == pch + 2 or nxt[2] == ch):
            fixed[run] = pch + 1
    for s in secs:
        if s.run in fixed:
            s.chapter = fixed[s.run]


_SMALL = {"a", "an", "the", "and", "or", "nor", "but", "of", "in", "on", "to", "by", "for", "at",
          "from", "with", "as", "into", "upon", "unto"}


def _chapter_title(head: str) -> str:
    """Perseus heads are in capitals; title-case them (proper nouns survive that)."""
    t = head.strip().rstrip(".")
    if not t.isupper():
        return t
    words = t.lower().split()
    return " ".join(w if i and w in _SMALL else w[:1].upper() + w[1:] for i, w in enumerate(words))


def parse_work(path: Path, work: Work) -> list[Section]:
    root = DET.parse(path).getroot()
    body = root.find(f".//{TEI}body")
    if body is None:
        raise ValueError(f"{path}: no TEI body")
    p = _Parser(work)
    p.walk(body)
    return p.finish()


# ---------------------------------------------------------------- DB

def load_josephus_into_db(conn: sqlite3.Connection, data_dir: Path = JOSEPHUS_DIR) -> int:
    """(Re)populate the josephus table and its FTS index. Returns section count."""
    conn.execute("DELETE FROM josephus")
    rows = []
    ord_ = 0
    for w in WORKS:
        for s in parse_work(xml_path(w, data_dir), w):
            rows.append((w.key, s.book, s.chapter, s.section, s.niese_start, s.niese_end,
                         s.chapter_title, ord_, s.text, json.dumps(s.notes, ensure_ascii=False)))
            ord_ += 1
    conn.executemany(
        "INSERT INTO josephus(work, book, chapter, section, niese_start, niese_end, chapter_title, ord, text, notes) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("INSERT INTO josephus_fts(josephus_fts) VALUES('rebuild')")
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------- references

def label(work: str, book: int, chapter: int, section: int) -> str:
    """Canonical Whiston citation, e.g. 'Antiquities 18.3.3', 'Against Apion 2.17', 'Life 2'."""
    w = WORKS_BY_KEY[work]
    if not w.books:
        return f"{w.short} {section}"
    if not w.chapters:
        return f"{w.short} {book}.{section}"
    if chapter == 0:
        return f"{w.short} {book} Preface {section}"
    return f"{w.short} {book}.{chapter}.{section}"


def niese_label(book: int, start: int, end: int, books: bool = True) -> str:
    rng = f"{start}–{end}" if end > start else str(start)
    return f"{book}.{rng}" if books else rng


@dataclass
class Ref:
    work: Work
    nums: list[int]          # as written, without the range end
    end: int | None = None   # range end of the last number
    preface: bool = False


def parse_josephus_ref(text: str) -> Ref | None:
    s = text.replace("§", " ").strip()
    low = s.lower()
    work = None
    for alias, w in _ALIASES:
        if low.startswith(alias) and (len(low) == len(alias) or not low[len(alias)].isalpha()):
            work, s = w, s[len(alias):]
            break
    if work is None:
        return None
    s = s.lstrip(" .,")
    m = re.fullmatch(
        r"(?:(?P<book>\d+)\s*[.:,]?\s*)?(?P<pref>(?:preface|pref|pr)\b\.?\s*[.:,]?\s*)?"
        r"(?P<rest>\d+(?:\s*[.:,]\s*\d+)*)?(?:\s*[–—-]\s*(?P<end>\d+))?\s*", s, re.I)
    if not m or not (m.group("book") or m.group("rest")):
        return None
    nums = []
    if m.group("book"):
        nums.append(int(m.group("book")))
    if m.group("rest"):
        nums += [int(x) for x in re.split(r"\s*[.:,]\s*", m.group("rest").strip())]
    preface = bool(m.group("pref"))
    end = int(m.group("end")) if m.group("end") else None
    return Ref(work, nums, end, preface)


_COLS = "id, work, book, chapter, section, niese_start, niese_end, chapter_title, ord, text, notes"


def _rows(conn: sqlite3.Connection, where: str, args: tuple) -> list[sqlite3.Row]:
    # ``where`` is always one of the literal clauses in ``resolve``; values are bound.
    return conn.execute(f"SELECT {_COLS} FROM josephus WHERE {where} ORDER BY ord", args).fetchall()


def resolve(conn: sqlite3.Connection, ref: Ref, max_sections: int = 40) -> list[sqlite3.Row]:
    """Rows for a reference. Whiston numbering is preferred; Niese is used when the
    numbers only make sense that way (e.g. 'Antiquities 18.63', 'Life 400')."""
    w, n = ref.work, ref.nums
    k = w.key
    rows: list[sqlite3.Row] = []

    def whiston(book: int, chapter: int, sec: int | None) -> list[sqlite3.Row]:
        if sec is None:
            return _rows(conn, "work=? AND book=? AND chapter=?", (k, book, chapter))
        hi = ref.end if ref.end is not None and ref.end >= sec else sec
        return _rows(conn, "work=? AND book=? AND chapter=? AND section BETWEEN ? AND ?",
                     (k, book, chapter, sec, hi))

    def niese(book: int, start: int) -> list[sqlite3.Row]:
        hi = ref.end if ref.end is not None and ref.end >= start else start
        return _rows(conn, "work=? AND book=? AND niese_end>=? AND niese_start<=?", (k, book, start, hi))

    if w.chapters:
        if ref.preface:
            if len(n) == 2:
                rows = whiston(n[0], 0, n[1])
            elif len(n) == 1:
                rows = whiston(n[0], 0, None)
        elif len(n) == 3:
            rows = whiston(n[0], n[1], n[2])
        elif len(n) == 2:
            rows = whiston(n[0], n[1], None) if ref.end is None else []
            if not rows:
                rows = niese(n[0], n[1])
    elif w.books:
        if len(n) == 2:
            rows = whiston(n[0], 0, n[1]) or niese(n[0], n[1])
    else:
        if len(n) == 1:
            rows = whiston(0, 0, n[0]) or niese(0, n[0])
    return rows[:max_sections]


def lookup(conn: sqlite3.Connection, text: str, max_sections: int = 40) -> list[sqlite3.Row]:
    ref = parse_josephus_ref(text)
    return resolve(conn, ref, max_sections) if ref else []


def row_label(r: sqlite3.Row | dict) -> str:
    return label(r["work"], r["book"], r["chapter"], r["section"])


def row_niese(r: sqlite3.Row | dict) -> str:
    return niese_label(r["book"], r["niese_start"], r["niese_end"], WORKS_BY_KEY[r["work"]].books)


def range_label(rows: list) -> str:
    """'Antiquities 18.3.3', or 'Antiquities 18.3.1–4' for a run in one chapter."""
    if not rows:
        return ""
    a, b = rows[0], rows[-1]
    if len(rows) == 1:
        return row_label(a)
    if (a["work"], a["book"], a["chapter"]) == (b["work"], b["book"], b["chapter"]):
        return f"{row_label(a)}–{b['section']}"
    return f"{row_label(a)} – {row_label(b)}"


def range_niese(rows: list) -> str:
    if not rows:
        return ""
    a, b = rows[0], rows[-1]
    books = WORKS_BY_KEY[a["work"]].books
    if a["book"] == b["book"]:
        return niese_label(a["book"], a["niese_start"], b["niese_end"], books)
    return f"{row_niese(a)} – {row_niese(b)}"


def neighbor(conn: sqlite3.Connection, row, step: int) -> sqlite3.Row | None:
    """The section before (step -1) or after (+1) ``row`` in the same work."""
    if step < 0:
        return conn.execute("SELECT " + _COLS + " FROM josephus WHERE work=? AND ord<? ORDER BY ord DESC LIMIT 1",
                            (row["work"], row["ord"])).fetchone()
    return conn.execute("SELECT " + _COLS + " FROM josephus WHERE work=? AND ord>? ORDER BY ord LIMIT 1",
                        (row["work"], row["ord"])).fetchone()
