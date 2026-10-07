import sqlite3

import pytest

from server import db as dbm
from server import josephus as jos
from server.ai.tools import ToolContext
from server.apocrypha import convert_vpl
from server.cite_check import CitationChecker
from server.citations import parse_ref, parse_scripture_refs
from server.indexer import split_words

TEI_HEAD = '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div type="translation">'
TEI_TAIL = "</div></body></text></TEI>"


def sec(n: int, body: str) -> str:
    return f'<div type="textpart" subtype="section" n="{n}">{body}</div>'


# Antiquities book 18: preface-less, chapter 3 (titled), a section that starts mid-div,
# and a chapter milestone numbered out of sequence ("7" where 4 belongs).
ANTIQUITIES = TEI_HEAD + '<div type="textpart" subtype="book" n="18"><head>BOOK XVIII</head>' + "".join([
    sec(1, '<milestone n="1" unit="Whiston_chapter"/><head>HOW QUIRINIUS WAS SENT.</head>'
           '<milestone n="1" unit="Whiston_section"/><p>Now Cyrenius came.</p>'),
    sec(55, '<milestone n="3" unit="Whiston_chapter"/><head>SEDITION AGAINST PONTIUS PILATE.</head>'
            '<milestone n="1" unit="Whiston_section"/><p>But now Pilate removed the army.</p>'),
    sec(63, '<milestone n="3" unit="Whiston_section"/><p>Now there was about this time Jesus, a wise man.'
            '<note resp="editor">Whiston defends this passage.</note> He was a doer of wonderful works.</p>'),
    sec(64, '<p>And when Pilate had condemned him to the cross.</p>'),
    sec(65, '<milestone n="4" unit="Whiston_section"/><p>About the same time another sad calamity.</p>'
            '<milestone n="5" unit="Whiston_section"/><p>There was a man who was a Jew.</p>'),
    sec(85, '<milestone n="7" unit="Whiston_chapter"/><head>HOW THE SAMARITANS WERE PUNISHED.</head>'
            '<milestone n="1" unit="Whiston_section"/><p>But the nation of the Samaritans did not escape.</p>'),
    sec(90, '<milestone n="5" unit="Whiston_chapter"/><head>HEROD MAKES WAR WITH ARETAS.</head>'
            '<milestone n="1" unit="Whiston_section"/><p>About this time Aretas and Herod had a quarrel.</p>'),
]) + "</div>" + TEI_TAIL

WAR = TEI_HEAD + '<div type="textpart" subtype="book" n="2">' + sec(
    162, '<milestone n="8" unit="Whiston_chapter"/><head>THE THREE SECTS.</head>'
         '<milestone n="14" unit="Whiston_section"/><p>But then as to the two other orders, the Pharisees.</p>') + "</div>" + TEI_TAIL
APION = TEI_HEAD + '<div type="textpart" subtype="book" n="2">' + sec(
    1, '<milestone n="1" unit="Whiston_section"/><p>In the former book, most honored Epaphroditus.</p>') + "</div>" + TEI_TAIL
LIFE = TEI_HEAD + sec(1, '<milestone n="1" unit="Whiston_section"/><p>The family from which I am derived.</p>') + \
    sec(7, '<milestone n="2" unit="Whiston_section"/><p>Now my father Matthias was eminent.</p>') + TEI_TAIL


@pytest.fixture
def jdir(tmp_path):
    for key, text in {"antiquities": ANTIQUITIES, "war": WAR, "apion": APION, "life": LIFE}.items():
        (tmp_path / f"{key}.xml").write_text(text, encoding="utf-8")
    return tmp_path


@pytest.fixture
def conn(jdir):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.ensure_schema(c)
    jos.load_josephus_into_db(c, jdir)
    return c


def test_parse_sections_titles_notes(jdir):
    secs = jos.parse_work(jdir / "antiquities.xml", jos.WORKS_BY_KEY["antiquities"])
    labels = [jos.label(s.work, s.book, s.chapter, s.section) for s in secs]
    assert labels == ["Antiquities 18.1.1", "Antiquities 18.3.1", "Antiquities 18.3.3", "Antiquities 18.3.4",
                      "Antiquities 18.3.5", "Antiquities 18.4.1", "Antiquities 18.5.1"]
    testimonium = secs[2]
    assert testimonium.chapter_title == "Sedition Against Pontius Pilate"
    assert "Whiston defends" not in testimonium.text and "wonderful works" in testimonium.text
    assert testimonium.notes == ["Whiston defends this passage."]
    assert "Pilate had condemned him" in testimonium.text          # carried across the div


def test_niese_ranges(jdir):
    secs = jos.parse_work(jdir / "antiquities.xml", jos.WORKS_BY_KEY["antiquities"])
    by = {(s.chapter, s.section): (s.niese_start, s.niese_end) for s in secs}
    assert by[(3, 1)] == (55, 62)
    assert by[(3, 3)] == (63, 64)
    assert by[(3, 4)] == (65, 65)      # 3.5 starts inside the same div
    assert by[(3, 5)] == (65, 84)


@pytest.mark.parametrize("ref,expected", [
    ("Antiquities 18.3.3", "Antiquities 18.3.3"),
    ("Ant. 18.64", "Antiquities 18.3.3"),               # Niese
    ("Jewish Antiquities 18:3:3", "Antiquities 18.3.3"),
    ("Antiquities 18.3", "Antiquities 18.3.1–5"),        # Whiston chapter
    ("Antiquities 18.3.3-4", "Antiquities 18.3.3–4"),
    ("Wars 2.8.14", "Wars 2.8.14"),
    ("War 2.162", "Wars 2.8.14"),
    ("Against Apion 2.1", "Against Apion 2.1"),
    ("Life 2", "Life 2"),
    ("Life 7", "Life 2"),                                # no Whiston section 7, so Niese
])
def test_lookup(conn, ref, expected):
    assert jos.range_label(jos.lookup(conn, ref)) == expected


@pytest.mark.parametrize("ref", ["Josephus 1.1", "Antiquities 99.1.1", "Life", "Antiquities"])
def test_lookup_misses(conn, ref):
    assert jos.lookup(conn, ref) == []


def test_citation_check(conn):
    checker = CitationChecker(conn)
    assert checker.check("josephus", "Ant. 18.63") == {"ok": True, "label": "Antiquities 18.3.3"}
    assert checker.check("josephus", "Antiquities 18.9.9")["ok"] is False


class _Engine:
    def josephus_search(self, q, mode, limit, work):
        from server.search import TalkHit
        return [TalkHit("3", 1.0, ["about this time <mark>Jesus</mark>"], {"keyword"})]


def test_tools(conn):
    ctx = ToolContext(conn, _Engine(), "2024-10/1x")
    r = ctx.execute("get_josephus", {"ref": "Antiquities 18.3.3", "context": 1, "include_notes": True})
    assert r.text.startswith("[[josephus:Antiquities 18.3.3]] Antiquities of the Jews, Niese 18.63–64")
    assert "[Antiquities 18.3.1] (context)" in r.text and "Whiston's note: Whiston defends" in r.text
    assert r.refs == [{"type": "josephus", "ref": "Antiquities 18.3.3"}]
    r = ctx.execute("search_josephus", {"query": "Jesus"})
    assert "[[josephus:Antiquities 18.3.3]] (Niese 18.63–64)" in r.text


def test_split_words_long_sections():
    text = " ".join(f"Sentence number {i} has five words." for i in range(200))   # ~1,200 words
    pieces = split_words(text)
    assert len(pieces) > 3
    assert all(len(p.split()) <= 320 for p in pieces)
    assert " ".join(pieces) == text


# ---------------------------------------------------------------- Apocrypha

def test_apocrypha_conversion():
    vpl = ("GEN 1:1 In the beginning.\nTOB 4:15 Do that to no man which thou hatest.\n"
           "SIR 44:1 Let us now praise famous men, and our [fathers] that begat us.\nMAT 1:1 The book.\n")
    v = convert_vpl(vpl)
    assert [(x["book_title"], x["chapter_number"], x["verse_number"]) for x in v] == [
        ("Tobit", 4, 15), ("Ecclesiasticus", 44, 1)]
    assert v[1]["volume_title"] == "Apocrypha" and "our fathers that" in v[1]["scripture_text"]


def test_apocrypha_references():
    assert parse_ref("Sirach 44:1-15") == ("Ecclesiasticus", 44, 1, 15)
    assert parse_ref("1 Macc. 2:50") == ("1 Maccabees", 2, 50, None)
    assert parse_ref("Prayer of Manasseh 1:12") == ("Prayer of Manasses", 1, 12, None)
    assert parse_ref("Rest of Esther 13:9") == ("Rest of Esther", 13, 9, None)
    assert parse_ref("Esther 4:14") == ("Esther", 4, 14, None)
    assert parse_ref("Ecclesiastes 3:1") == ("Ecclesiastes", 3, 1, None)
    # Common words are not book names in running talk text.
    refs = parse_scripture_refs("He gained wisdom 3 years later; see Tobit 4:15.")
    assert [(r.book, r.chapter, r.verse_start) for r in refs] == [("Tobit", 4, 15)]
