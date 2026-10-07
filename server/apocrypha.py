"""The Apocrypha (KJV, 1769 text): book table, download and conversion.

The verses come from eBible.org's public-domain "King James Version + Apocrypha"
verse-per-line export. They are stored in the ``scriptures`` table under the
volume "Apocrypha", so lookups, the scripture panel and [[scripture:…]] citations
work for them unchanged. Doctrine and Covenants 91 is the Church's guidance on
reading them.

Fifteen books by the usual count. As in the KJV, the Epistle of Jeremy is Baruch
chapter 6, so fourteen book names appear here.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import httpx

from .config import APOCRYPHA_JSON

APOCRYPHA_URL = "https://ebible.org/Scriptures/eng-kjv_vpl.zip"
VOLUME = "Apocrypha"

# (eBible code, canonical title, short title, extra aliases). Bare common words
# ("Wisdom") are left out of the aliases: the talk parser matches them case-insensitively.
BOOKS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("1ES", "1 Esdras", "1 Esd.", ()),
    ("4ES", "2 Esdras", "2 Esd.", ()),
    ("TOB", "Tobit", "Tob.", ()),
    ("JDT", "Judith", "Jdt.", ()),
    ("ESG", "Rest of Esther", "Rest of Esth.", ("Additions to Esther", "The Rest of Esther", "Esther (Greek)")),
    ("WIS", "Wisdom of Solomon", "Wisd. of Sol.", ("Wis.", "Wisd.", "Book of Wisdom")),
    ("SIR", "Ecclesiasticus", "Ecclus.", ("Sirach", "Sir.", "Ben Sira", "Wisdom of Sirach")),
    ("BAR", "Baruch", "Bar.", ()),
    ("PRA", "Song of the Three Children", "Song of Three",
     ("Song of the Three Holy Children", "Prayer of Azariah", "Song of the Three Young Men")),
    ("SUS", "Susanna", "Sus.", ()),
    ("BEL", "Bel and the Dragon", "Bel", ()),
    ("PRM", "Prayer of Manasses", "Pr. of Man.", ("Prayer of Manasseh",)),
    ("1MA", "1 Maccabees", "1 Macc.", ("1 Mac.",)),
    ("2MA", "2 Maccabees", "2 Macc.", ("2 Mac.",)),
]
_BY_CODE = {code: (title, short) for code, title, short, _ in BOOKS}

_LINE_RE = re.compile(r"^(\w{3}) (\d+):(\d+) (.*)$")


def convert_vpl(text: str) -> list[dict]:
    """Apocrypha verses from an eBible VPL text, as records shaped like the
    standard-works JSON (so one loader handles both)."""
    out = []
    for line in text.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m or m.group(1) not in _BY_CODE:
            continue
        title, short = _BY_CODE[m.group(1)]
        # Brackets mark the translators' supplied words (italics in print).
        verse = re.sub(r"\[([^\]]*)\]", r"\1", m.group(4)).strip()
        out.append({"volume_title": VOLUME, "book_title": title, "book_short_title": short,
                    "chapter_number": int(m.group(2)), "verse_number": int(m.group(3)),
                    "scripture_text": verse})
    return out


def download_apocrypha(dest: Path = APOCRYPHA_JSON, force: bool = False) -> Path:
    """Fetch the eBible archive, keep only the Apocrypha, validate, write JSON."""
    if dest.exists() and not force:
        return dest
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        r = client.get(APOCRYPHA_URL)
        r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = next((n for n in z.namelist() if n.endswith("_vpl.txt")), None)
        if name is None:
            raise RuntimeError("eBible archive has no _vpl.txt file")
        text = z.read(name).decode("utf-8-sig")
    verses = convert_vpl(text)
    books = {v["book_title"] for v in verses}
    if len(books) != len(BOOKS) or len(verses) < 5000:
        raise RuntimeError(f"Apocrypha download looks wrong: {len(books)} books, {len(verses)} verses")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(verses, ensure_ascii=False), encoding="utf-8")
    return dest
