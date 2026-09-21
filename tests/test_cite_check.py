import sqlite3

import pytest

from server import db as dbm
from server.cite_check import CitationChecker, StreamScanner, scan


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.ensure_schema(c)
    c.execute("INSERT INTO conferences VALUES('2026-04', 2026, 4, 'April 2026', 'u')")
    c.execute("INSERT INTO talks VALUES('2026-04/a', '2026-04', 'Elder A', 'Talk A', 'http://a', 10, 0)")
    for v, t in ((21, "And now as I said concerning faith"), (22, "And now behold, I say unto you")):
        c.execute("INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) "
                  "VALUES('BoM','Alma','Alma',32,?,?)", (v, t))
    c.commit()
    return c


# --------------------------------------------------------------- talk ids

def test_real_talk_id_passes_with_its_title(conn):
    assert CitationChecker(conn).check("talk", "2026-04/a") == {"ok": True, "label": "Talk A"}


def test_fabricated_talk_id_fails(conn):
    assert CitationChecker(conn).check("talk", "2019-04/22smith")["ok"] is False


# ------------------------------------------------------------- scriptures

def test_real_verses_pass_and_come_back_canonicalised(conn):
    c = CitationChecker(conn)
    assert c.check("scripture", "Alma 32:21") == {"ok": True, "label": "Alma 32:21"}
    assert c.check("scripture", "Alma 32:21-22")["label"] == "Alma 32:21–22"


def test_whole_chapter_passes_when_any_verse_exists(conn):
    assert CitationChecker(conn).check("scripture", "Alma 32")["ok"] is True


@pytest.mark.parametrize("ref", [
    "Alma 99:1",        # parses, but no such chapter
    "Alma 32:99",       # parses, but no such verse
    "Hezekiah 3:4",     # no such book
    "not a reference",  # does not parse at all
])
def test_unreal_references_fail(conn, ref):
    assert CitationChecker(conn).check("scripture", ref)["ok"] is False


def test_a_scripture_needs_no_tool_call_only_existence(conn):
    """The canon is complete on disk, so a recalled verse is as good as a looked-up one."""
    assert CitationChecker(conn).check("scripture", "Alma 32:22")["ok"] is True


# ------------------------------------------------------------------ cache

def test_repeat_checks_hit_the_cache(conn):
    c = CitationChecker(conn)
    c.check("talk", "2026-04/a")
    conn.execute("DELETE FROM talks")  # a second query would now miss
    assert c.check("talk", "2026-04/a")["ok"] is True


# ------------------------------------------------------------ whole text

def test_scan_keys_every_citation(conn):
    text = "See [[talk:2026-04/a]] and [[scripture:Alma 32:21]], but not [[talk:2019-04/22smith]]."
    got = scan(text, CitationChecker(conn))
    assert got["talk:2026-04/a"]["ok"] is True
    assert got["scripture:Alma 32:21"]["ok"] is True
    assert got["talk:2019-04/22smith"]["ok"] is False


# -------------------------------------------------------------- streaming

def feed_all(scanner, chunks):
    return [r for chunk in chunks for r in scanner.feed(chunk)]


def test_citation_split_across_deltas_reports_once_when_complete(conn):
    s = StreamScanner(CitationChecker(conn))
    assert s.feed("as taught in [[talk:2026") == []
    assert s.feed("-04/a") == []
    out = s.feed("]] and so on")
    assert [r["key"] for r in out] == ["talk:2026-04/a"]
    assert out[0]["ok"] is True


def test_unclosed_bracket_never_reports(conn):
    s = StreamScanner(CitationChecker(conn))
    assert feed_all(s, ["text [[talk:2026-04/a", " still going"]) == []


def test_two_citations_in_one_delta_report_in_order(conn):
    s = StreamScanner(CitationChecker(conn))
    out = s.feed("[[scripture:Alma 32:21]] then [[talk:2026-04/a]]")
    assert [r["key"] for r in out] == ["scripture:Alma 32:21", "talk:2026-04/a"]


def test_the_same_citation_twice_reports_once(conn):
    s = StreamScanner(CitationChecker(conn))
    out = feed_all(s, ["[[talk:2026-04/a]] ", "and again [[talk:2026-04/a]]"])
    assert [r["key"] for r in out] == ["talk:2026-04/a"]


def test_streamed_one_character_at_a_time(conn):
    s = StreamScanner(CitationChecker(conn))
    text = "x [[talk:2026-04/a]] y [[scripture:Hezekiah 3:4]] z"
    out = feed_all(s, list(text))
    assert [(r["key"], r["ok"]) for r in out] == [
        ("talk:2026-04/a", True),
        ("scripture:Hezekiah 3:4", False),
    ]
