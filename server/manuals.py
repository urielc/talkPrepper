"""Church teaching material: lesson manuals, youth lessons, self-reliance, family history,
Gospel Topics and Teachings of Presidents of the Church.

Pages come from the Gospel Library content API (the JSON behind
churchofjesuschrist.org/study), one request per second. Each manual's root URI
returns its table of contents as HTML links; each page returns its body as HTML,
which is reduced here to headings and paragraphs. Raw API responses are cached in
``data/manuals/raw/`` so a re-run only fetches what is new, and the parsed result
is written to ``data/manuals/manuals.json`` for the indexer.

The Church's terms of use allow personal, noncommercial use. The app keeps every
page behind its login.

A page is identified by its Gospel Library URI without ``/study`` (e.g.
``/manual/come-follow-me-for-home-and-church-old-testament-2026/46``). A Come,
Follow Me lesson is stored as two pages: the lesson itself and its "Ideas for
Teaching Children" section, whose id ends in ``#children``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from .config import MANUALS_DIR, MANUALS_JSON

API = "https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/content"
SITE = "https://www.churchofjesuschrist.org/study"
USER_AGENT = "Mozilla/5.0 (compatible; lesson-prep/1.0)"
DELAY_S = 1.0
ATTRIBUTION = "© by Intellectual Reserve, Inc. From churchofjesuschrist.org, for personal, noncommercial use."

CHILDREN_SUFFIX = "#children"

# Audience tags: children, youth, adults, plus female / male when a page is for one group.
AUDIENCES = ("children", "youth", "adults")
GENDERS = ("female", "male")


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    kind: str                      # shown as a badge: "Come, Follow Me", "Youth lessons", …
    roots: tuple[str, ...]         # table-of-contents URIs
    audience: tuple[str, ...]
    include: str = ""              # regex a page URI must match
    min_pages: int = 1             # sanity check for the download


def _ftsoy_roots(year: int = 2026) -> tuple[str, ...]:
    today = dt.date.today()
    last = today.month if today.year == year else 12
    return tuple(f"/ftsoy/{year}/{m:02d}" for m in range(1, last + 1))


SOURCES: list[Source] = [
    Source("cfm-ot-2026", "Come, Follow Me—For Home and Church: Old Testament 2026", "Come, Follow Me",
           ("/manual/come-follow-me-for-home-and-church-old-testament-2026",), ("children", "youth", "adults"),
           min_pages=60),
    Source("fsy-lessons", "For the Strength of Youth: Sunday lessons", "Youth lessons",
           _ftsoy_roots(), ("youth",), include=r"/fsy-lessons/(?!00-intro)", min_pages=6),
    Source("fsy-guide", "For the Strength of Youth: A Guide for Making Choices", "Youth",
           ("/manual/for-the-strength-of-youth",), ("youth",), min_pages=8),
    Source("sr-finances", "Personal Finances for Self-Reliance", "Self-reliance",
           ("/manual/personal-finances-for-self-reliance",), ("adults",), min_pages=40),
    Source("sr-job", "Find a Better Job for Self-Reliance", "Self-reliance",
           ("/manual/find-a-better-job-for-self-reliance",), ("adults",), min_pages=40),
    Source("sr-business", "Starting and Growing My Business for Self-Reliance", "Self-reliance",
           ("/manual/starting-and-growing-my-business-for-self-reliance",), ("adults",), min_pages=40),
    Source("sr-resilience", "Finding Strength in the Lord: Emotional Resilience", "Self-reliance",
           ("/manual/emotional-resilience-for-self-reliance",), ("youth", "adults"), min_pages=30),
    Source("family-history", "Member's Guide to Temple and Family History Work", "Family history",
           ("/manual/members-guide-to-temple-and-family-history-work",), ("youth", "adults"), min_pages=8),
    Source("gospel-topics", "Gospel Topics", "Gospel Topics",
           ("/manual/gospel-topics",), ("youth", "adults"), min_pages=200),
    Source("teachings-nelson", "Teachings of Presidents of the Church: Russell M. Nelson", "Teachings",
           ("/manual/teachings-of-presidents-of-the-church-russell-m-nelson",), ("adults",), min_pages=20),
    Source("teachings-monson", "Teachings of Presidents of the Church: Thomas S. Monson", "Teachings",
           ("/manual/teachings-of-presidents-of-the-church-thomas-s-monson",), ("adults",), min_pages=20),
    Source("teachings-hinckley", "Teachings of Presidents of the Church: Gordon B. Hinckley", "Teachings",
           ("/manual/teachings-of-presidents-of-the-church-gordon-b-hinckley",), ("adults",), min_pages=20),
]
SOURCES_BY_KEY = {s.key: s for s in SOURCES}

# Front and back matter, not teaching content: title and publication pages, lists of
# images, indexes, completion certificates and facilitator instructions.
_SKIP_SLUG = re.compile(
    r"/(?:copyright[^/]*|title-page|contents|front-matter|notes|bibliography|(?:\d+-)?index|list-of-visuals|"
    r"publication-information|letter-of-completion|for-facilitators|evaluating-my-efforts)$")
MIN_WORDS = 40


# ---------------------------------------------------------------- URIs

def page_uri(href: str) -> str | None:
    """'/study/manual/x/1?lang=eng#p3' -> '/manual/x/1'."""
    path = urlsplit(href).path
    if not path.startswith("/study/"):
        return None
    return path[len("/study"):].rstrip("/") or None


def church_url(page_id: str) -> str:
    base = page_id.split("#", 1)[0]
    return f"{SITE}{base}?lang=eng"


def audience_for(source: Source, page_id: str) -> list[str]:
    """Audience tags of one page: the source's, narrowed for pages meant for one group."""
    if page_id.endswith(CHILDREN_SUFFIX):
        return ["children"]
    tags = list(source.audience)
    if source.key == "cfm-ot-2026":
        if re.search(r"/5[45]-appendix-[bc]$", page_id):
            return ["children"]            # Primary and singing-time appendixes
        if page_id.endswith("/56-appendix-d"):
            return ["youth"]               # quorum and class meeting agenda
        tags = ["youth", "adults"]          # the children's ideas are their own page
    if re.search(r"/04a-", page_id):
        tags.append("female")              # fourth Sunday: Young Women
    elif re.search(r"/04b-", page_id):
        tags.append("male")                # fourth Sunday: Aaronic Priesthood quorums
    return tags


# ---------------------------------------------------------------- fetching

class Fetcher:
    """Content API client with a raw-response cache and a polite delay."""

    def __init__(self, cache_dir: Path = MANUALS_DIR / "raw", refresh: bool = False,
                 client: httpx.Client | None = None, delay: float = DELAY_S):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.client = client or httpx.Client(follow_redirects=True, timeout=60,
                                             headers={"User-Agent": USER_AGENT})
        self.delay = delay
        self._last = 0.0
        self.fetched = 0

    def _path(self, uri: str) -> Path:
        return self.cache_dir / (hashlib.sha256(uri.encode()).hexdigest()[:24] + ".json")

    def get(self, uri: str, cache: bool = True) -> dict | None:
        p = self._path(uri)
        if cache and not self.refresh and p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = self.client.get(API, params={"lang": "eng", "uri": uri})
        self.fetched += 1
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or "content" not in data:
            return None
        if cache:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data


# ---------------------------------------------------------------- parsing

def toc_entries(body_html: str) -> list[tuple[str, str]]:
    """(page uri, title) for each page link in a table of contents, in order, deduped."""
    soup = BeautifulSoup(body_html, "html.parser")
    out, seen = [], set()
    for a in soup.select("a[href]"):
        uri = page_uri(a["href"])
        if not uri or uri in seen:
            continue
        seen.add(uri)
        t = a.select_one("p.title")
        out.append((uri, _clean(t.get_text(" ") if t else a.get_text(" "))))
    return out


_SKIP_CLASSES = {"reference", "short-reference", "title-number", "kicker-image"}
_BLOCKS = ("h1", "h2", "h3", "h4", "h5", "p", "li")


def _clean(s: str) -> str:
    s = " ".join(s.replace("\xa0", " ").split())
    s = re.sub(r"\s+([.,;:!?’”)\]])", r"\1", s)
    return re.sub(r"([“‘(\[])\s+", r"\1", s)


def page_blocks(body_html: str) -> list[dict]:
    """Headings and paragraphs of a page body in document order.

    Each block is {"text": str, "h": heading level or 0}. Figures, footnote markers
    and the citation lines at the top of every page are dropped; a list item that
    wraps paragraphs yields the paragraphs, not a duplicate of their text."""
    soup = BeautifulSoup(body_html, "html.parser")
    for el in soup.select("figure, sup.marker, nav, script, style, img, video, audio"):
        el.decompose()
    out: list[dict] = []
    for el in soup.find_all(_BLOCKS):
        if not isinstance(el, Tag):
            continue
        if _SKIP_CLASSES & set(el.get("class") or []):
            continue
        if el.name == "li" and el.find(["p", "li"]):
            continue
        if el.name == "p" and el.find_parent(["h1", "h2", "h3", "h4", "h5"]):
            continue
        text = _clean(el.get_text(" "))
        if not text:
            continue
        level = int(el.name[1]) if el.name[0] == "h" else 0
        if out and out[-1]["text"] == text:
            continue
        out.append({"text": text, "h": level})
    return out


def split_children(blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split a Come, Follow Me lesson at its "Ideas for Teaching Children" heading."""
    for i, b in enumerate(blocks):
        if b["h"] and b["text"].lower().startswith("ideas for teaching children"):
            return blocks[:i], blocks[i:]
    return blocks, []


_TIME_NOTE = re.compile(r"\s*[—–-]\s*Maximum Time:.*$", re.IGNORECASE)


def page_title(uri: str, title: str, toc_titles: dict[str, str]) -> str:
    """A title that makes sense out of context.

    Self-reliance workbooks nest generic sections ("Learn—Maximum Time: 45 Minutes")
    under each chapter, so a nested page is prefixed with its chapter's title; and a
    Gospel Topics study guide shares its topic's title."""
    title = _TIME_NOTE.sub("", title)
    parent = uri.rsplit("/", 1)[0]
    if parent in toc_titles:
        title = f"{_TIME_NOTE.sub('', toc_titles[parent])}: {title}"
    if uri.endswith("-study-guide") and "study guide" not in title.lower():
        title += " (study guide)"
    return title


def word_count(blocks: list[dict]) -> int:
    return sum(len(b["text"].split()) for b in blocks if not b["h"])


def is_outline(blocks: list[dict]) -> bool:
    """A chapter landing page that only lists its sections ("My Foundation Principle",
    "Business Principles, Skills, and Habits"): short, with no sentence of prose."""
    paras = [b["text"] for b in blocks if not b["h"]]
    return word_count(blocks) < 100 and all(len(p.split()) <= 12 for p in paras)


def body_hash(blocks: list[dict]) -> str:
    return hashlib.sha256("\n".join(b["text"] for b in blocks if not b["h"]).encode()).hexdigest()


# ---------------------------------------------------------------- download

ProgressCb = Callable[[str, int, int], None]


def download_manuals(dest: Path = MANUALS_JSON, only: list[str] | None = None, refresh: bool = False,
                     fetcher: Fetcher | None = None, progress: ProgressCb | None = None) -> dict:
    """Fetch every source (or ``only`` those keys), parse, validate and write the JSON.

    Sources not in ``only`` keep their pages from the existing file."""
    fetcher = fetcher or Fetcher(refresh=refresh)
    existing: dict = {}
    if dest.exists():
        existing = {m["key"]: m for m in json.loads(dest.read_text(encoding="utf-8"))["manuals"]}
    manuals = []
    for src in SOURCES:
        if only and src.key not in only:
            if src.key in existing:
                manuals.append(existing[src.key])
            continue
        manuals.append(fetch_source(src, fetcher, progress))
    dedupe_pages(manuals)
    data = {"fetched_at": dt.datetime.now().isoformat(timespec="seconds"), "manuals": manuals}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def dedupe_pages(manuals: list[dict]) -> None:
    """Drop a page whose text already appeared earlier (the self-reliance workbooks
    each reprint the same First Presidency message)."""
    seen: set[str] = set()
    for m in manuals:
        kept = []
        for p in m["pages"]:
            h = body_hash(p["blocks"])
            if h not in seen:
                seen.add(h)
                kept.append(p)
        m["pages"] = kept


def fetch_source(src: Source, fetcher: Fetcher, progress: ProgressCb | None = None) -> dict:
    entries: list[tuple[str, str]] = []
    for root in src.roots:
        # Tables of contents change (new magazine issues), so they are never cached.
        toc = fetcher.get(root, cache=False)
        if toc is None:
            continue
        for uri, title in toc_entries(toc["content"].get("body", "")):
            if not uri.startswith(root + "/") or _SKIP_SLUG.search(uri):
                continue
            if src.include and not re.search(src.include, uri):
                continue
            entries.append((uri, title))
    toc_titles = dict(entries)
    pages = []
    for i, (uri, toc_title) in enumerate(entries):
        if progress:
            progress(src.key, i + 1, len(entries))
        data = fetcher.get(uri)
        if data is None:
            continue
        title = page_title(uri, _clean((data.get("meta") or {}).get("title") or toc_title), toc_titles)
        blocks = page_blocks((data.get("content") or {}).get("body", ""))
        main, children = split_children(blocks) if src.key == "cfm-ot-2026" else (blocks, [])
        for pid, ptitle, pblocks in ((uri, title, main), (uri + CHILDREN_SUFFIX, f"{title}: Ideas for Teaching Children", children)):
            if word_count(pblocks) < MIN_WORDS or is_outline(pblocks):
                continue
            pages.append({"id": pid, "title": ptitle, "audience": audience_for(src, pid), "blocks": pblocks})
    if len({p["id"].split("#")[0] for p in pages}) < src.min_pages:
        raise RuntimeError(f"{src.key}: only {len(pages)} pages fetched (expected at least {src.min_pages})")
    return {"key": src.key, "title": src.title, "kind": src.kind, "audience": list(src.audience), "pages": pages}


# ---------------------------------------------------------------- database

def load_manuals_into_db(conn: sqlite3.Connection, path: Path = MANUALS_JSON) -> int:
    """Insert manuals, pages and paragraphs (tables already created). Returns page count."""
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for mo, m in enumerate(data["manuals"]):
        conn.execute("INSERT INTO manuals(key, title, kind, audience, ord) VALUES(?,?,?,?,?)",
                     (m["key"], m["title"], m["kind"], " ".join(m["audience"]), mo))
        for po, p in enumerate(m["pages"]):
            cur = conn.execute(
                "INSERT INTO manual_pages(uri, manual_key, title, audience, ord, url, word_count) VALUES(?,?,?,?,?,?,?)",
                (p["id"], m["key"], p["title"], " ".join(p["audience"]), po, church_url(p["id"]),
                 word_count(p["blocks"])))
            conn.executemany("INSERT INTO manual_paragraphs(page_id, idx, text, heading) VALUES(?,?,?,?)",
                             [(cur.lastrowid, i, b["text"], b["h"]) for i, b in enumerate(p["blocks"])])
            n += 1
    conn.execute("INSERT INTO manual_fts(manual_fts) VALUES('rebuild')")
    conn.commit()
    return n


def get_page(conn: sqlite3.Connection, ref: str) -> sqlite3.Row | None:
    """A page by URI. Accepts a full churchofjesuschrist.org URL or a /study path too."""
    ref = ref.strip()
    if ref.startswith("http"):
        parts = urlsplit(ref)
        ref = parts.path + (f"#{parts.fragment}" if parts.fragment == "children" else "")
    if ref.startswith("/study/"):
        ref = ref[len("/study"):]
    return conn.execute(
        "SELECT p.*, m.title AS manual_title, m.kind FROM manual_pages p JOIN manuals m ON m.key=p.manual_key "
        "WHERE p.uri=?", (ref,)).fetchone()


def page_paragraphs(conn: sqlite3.Connection, page_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT idx, text, heading FROM manual_paragraphs WHERE page_id=? ORDER BY idx",
                        (page_id,)).fetchall()


def neighbor(conn: sqlite3.Connection, page: sqlite3.Row, step: int) -> sqlite3.Row | None:
    if step < 0:
        return conn.execute("SELECT uri, title FROM manual_pages WHERE manual_key=? AND ord<? ORDER BY ord DESC LIMIT 1",
                            (page["manual_key"], page["ord"])).fetchone()
    return conn.execute("SELECT uri, title FROM manual_pages WHERE manual_key=? AND ord>? ORDER BY ord LIMIT 1",
                        (page["manual_key"], page["ord"])).fetchone()


def page_text(conn: sqlite3.Connection, page_id: int) -> str:
    """Plain text with headings marked, for the model."""
    lines = []
    for r in page_paragraphs(conn, page_id):
        lines.append(("#" * min(r["heading"], 4) + " " + r["text"]) if r["heading"] else r["text"])
    return "\n\n".join(lines)


def matches_audience(tags: str, audience: str | None, gender: str | None) -> bool:
    """Whether a page tagged ``tags`` suits the chosen audience and gender."""
    t = set(tags.split())
    if audience and audience in AUDIENCES and audience not in t:
        return False
    if gender in GENDERS:
        other = "male" if gender == "female" else "female"
        if other in t:
            return False
    return True
