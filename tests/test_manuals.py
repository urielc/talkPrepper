import json
import sqlite3

import pytest

from server import db as dbm
from server import manuals as man
from server.ai.tools import ToolContext
from server.cite_check import CitationChecker
from server.search import TalkHit

CFM = "/manual/come-follow-me-for-home-and-church-old-testament-2026"

TOC = f"""<header><h1 class="title">Come, Follow Me</h1></header>
<nav class="manifest"><ul class="doc-map">
<li><a href="/study{CFM}/001-conversion?lang=eng" class="list-tile"><p class="title">Conversion Is Our Goal</p></a></li>
<li><a href="/study{CFM}/46?lang=eng" class="list-tile"><p class="title">November 9–15</p><p class="subtitle">Daniel 1–7</p></a></li>
<li><a href="/study{CFM}/46?lang=eng#p3" class="list-tile"><p class="title">dup</p></a></li>
<li><a href="/study{CFM}/copyright?lang=eng"><p class="title">Copyright</p></a></li>
<li><a href="/study/manual/elsewhere/1?lang=eng"><p class="title">Not this manual</p></a></li>
</ul></nav>"""

WORDS = " ".join(["faith"] * 45)
LESSON = f"""<p class="reference">“November 9–15,” Come, Follow Me (2026)</p>
<header><figure><img src="x"><figcaption>Daniel</figcaption></figure><h1>Daniel 1–7</h1></header>
<p>Most likely no one will throw you into a fiery furnace. {WORDS}<sup class="marker">1</sup> .</p>
<p>See “ Daniel” in the Bible Dictionary .</p>
<h2>Ideas for Learning at Home and at Church</h2>
<ul><li><p>When have you felt pressured?</p></li><li>How has the Lord blessed you?</li></ul>
<h2>Ideas for Teaching Children</h2>
<h3>Jesus will help me do what is right.</h3>
<p>Children could act out the story of Daniel. {WORDS}</p>"""

INTRO = f"<h1>Conversion Is Our Goal</h1><p>The aim of all gospel learning is conversion. {WORDS}</p>"


def test_toc_entries():
    assert man.toc_entries(TOC) == [
        (f"{CFM}/001-conversion", "Conversion Is Our Goal"),
        (f"{CFM}/46", "November 9–15"),
        (f"{CFM}/copyright", "Copyright"),
        ("/manual/elsewhere/1", "Not this manual"),
    ]


def test_page_blocks():
    blocks = man.page_blocks(LESSON)
    texts = [b["text"] for b in blocks]
    assert texts[0] == "Daniel 1–7" and blocks[0]["h"] == 1          # citation line and figure dropped
    assert texts[1].startswith("Most likely") and texts[1].endswith("faith.")   # marker gone, spacing fixed
    assert 'See “Daniel” in the Bible Dictionary.' in texts
    assert texts.count("When have you felt pressured?") == 1 and "How has the Lord blessed you?" in texts
    main, kids = man.split_children(blocks)
    assert kids[0]["text"] == "Ideas for Teaching Children" and main[-1]["text"] == "How has the Lord blessed you?"


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, uri, cache=True):
        self.calls.append(uri)
        body = self.pages.get(uri)
        return None if body is None else {"meta": {"title": uri.rsplit("/", 1)[-1]}, "content": {"body": body}}


@pytest.fixture
def manuals_json(tmp_path, monkeypatch):
    src = man.Source("cfm-ot-2026", "Come, Follow Me—For Home and Church: Old Testament 2026", "Come, Follow Me",
                     (CFM,), ("children", "youth", "adults"))
    fsy = man.Source("fsy-lessons", "For the Strength of Youth: Sunday lessons", "Youth lessons",
                     ("/ftsoy/2026/11",), ("youth",), include=r"/fsy-lessons/(?!00-intro)")
    monkeypatch.setattr(man, "SOURCES", [src, fsy])
    ftoc = ('<a href="/study/ftsoy/2026/11/fsy-lessons/00-intro?lang=eng">Intro</a>'
            '<a href="/study/ftsoy/2026/11/fsy-lessons/04a-fourth-sunday?lang=eng">YW</a>'
            '<a href="/study/ftsoy/2026/11/fsy-lessons/04b-fourth-sunday?lang=eng">AP</a>'
            '<a href="/study/ftsoy/2026/11/01-story?lang=eng">Story</a>')
    fetcher = FakeFetcher({
        CFM: TOC, f"{CFM}/001-conversion": INTRO, f"{CFM}/46": LESSON, f"{CFM}/copyright": INTRO,
        "/ftsoy/2026/11": ftoc,
        "/ftsoy/2026/11/fsy-lessons/04a-fourth-sunday": f"<h1>Daughters of God</h1><p>{WORDS}</p>",
        "/ftsoy/2026/11/fsy-lessons/04b-fourth-sunday": f"<h1>Priesthood duty</h1><p>{WORDS}</p>",
    })
    dest = tmp_path / "manuals.json"
    man.download_manuals(dest, fetcher=fetcher)
    assert f"{CFM}/copyright" not in fetcher.calls and "/ftsoy/2026/11/01-story" not in fetcher.calls
    return dest


def test_download_and_audience(manuals_json):
    data = json.loads(manuals_json.read_text())
    pages = {p["id"]: p for m in data["manuals"] for p in m["pages"]}
    assert set(pages) == {f"{CFM}/001-conversion", f"{CFM}/46", f"{CFM}/46#children",
                          "/ftsoy/2026/11/fsy-lessons/04a-fourth-sunday", "/ftsoy/2026/11/fsy-lessons/04b-fourth-sunday"}
    assert pages[f"{CFM}/46#children"]["audience"] == ["children"]
    assert pages[f"{CFM}/46"]["audience"] == ["youth", "adults"]
    assert pages["/ftsoy/2026/11/fsy-lessons/04a-fourth-sunday"]["audience"] == ["youth", "female"]
    assert pages["/ftsoy/2026/11/fsy-lessons/04b-fourth-sunday"]["audience"] == ["youth", "male"]


def test_download_validates_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(man, "SOURCES", [man.Source("x", "X", "X", ("/manual/x",), ("adults",), min_pages=5)])
    with pytest.raises(RuntimeError, match="only 0 pages"):
        man.download_manuals(tmp_path / "m.json", fetcher=FakeFetcher({"/manual/x": ""}))


@pytest.fixture
def conn(manuals_json):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.ensure_schema(c)
    assert man.load_manuals_into_db(c, manuals_json) == 5
    return c


def test_lookup_and_neighbors(conn):
    p = man.get_page(conn, f"https://www.churchofjesuschrist.org/study{CFM}/46?lang=eng")
    assert p["manual_title"].startswith("Come, Follow Me") and p["url"].endswith(f"{CFM}/46?lang=eng")
    kids = man.get_page(conn, f"{CFM}/46#children")
    assert kids["url"] == p["url"]
    assert man.neighbor(conn, p, 1)["uri"] == f"{CFM}/46#children"
    assert man.neighbor(conn, p, -1)["uri"] == f"{CFM}/001-conversion"
    assert "## Ideas for Teaching Children" in man.page_text(conn, kids["id"])
    assert man.get_page(conn, "/manual/nope") is None


def test_matches_audience():
    assert man.matches_audience("youth female", "youth", "female")
    assert not man.matches_audience("youth male", "youth", "female")
    assert not man.matches_audience("adults", "children", None)
    assert man.matches_audience("youth adults", None, "male")


def test_manual_keyword_search(conn):
    from server.search import SearchEngine
    eng = SearchEngine(conn)
    hits = eng.manual_keyword("fiery furnace")
    assert [conn.execute("SELECT uri FROM manual_pages WHERE id=?", (int(h.talk_id),)).fetchone()[0] for h in hits] \
        == [f"{CFM}/46"]
    allowed = eng._allowed_pages(None, "children", None)
    assert [int(x) for x in allowed] == [man.get_page(conn, f"{CFM}/46#children")["id"]]


def test_citation_check(conn):
    checker = CitationChecker(conn)
    assert checker.check("manual", f"{CFM}/46") == {"ok": True, "label": "46"}
    assert checker.check("manual", "/manual/made-up/1")["ok"] is False


class _Engine:
    def __init__(self, conn):
        self.conn = conn

    def manual_search(self, q, mode, limit, manual=None, audience=None, gender=None):
        pid = man.get_page(self.conn, f"{CFM}/46#children")["id"]
        return [TalkHit(str(pid), 1.0, ["act out <mark>Daniel</mark>"], {"keyword"})]


def test_tools(conn):
    ctx = ToolContext(conn, _Engine(conn), "2026-10/a")
    r = ctx.execute("search_manuals", {"query": "Daniel", "audience": "children"})
    assert f"[[manual:{CFM}/46#children]]" in r.text and "(for: children)" in r.text
    assert r.refs[0]["type"] == "manual"
    r = ctx.execute("get_manual_page", {"uri": f"{CFM}/46"})
    assert r.text.startswith(f"[[manual:{CFM}/46]]") and "fiery furnace" in r.text
    assert "not found" in ctx.execute("get_manual_page", {"uri": "/manual/nope"}).summary


def test_page_title_in_context():
    toc = {"/manual/pf/8-debt": "8: Getting out of Debt"}
    assert man.page_title("/manual/pf/8-debt/learn", "Learn—Maximum Time: 45 Minutes", toc) == "8: Getting out of Debt: Learn"
    assert man.page_title("/manual/gospel-topics/forgiveness-study-guide", "Forgiveness", {}) == "Forgiveness (study guide)"
    assert man.page_title("/manual/gospel-topics/forgiveness", "Forgiveness", {}) == "Forgiveness"
