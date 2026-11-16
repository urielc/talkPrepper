"""Paragraph kinds from the scraper, numbering rule, index columns and migration. No network."""

import json
import sqlite3

import pytest

from scrape_conference_talks import ConferenceTalkScraper, report_paragraph_changes
from server import db as dbm, indexer, migrate
from server.indexer import paragraph_numbers
from server.ai.prompts import build_system

NEW_STYLE = """
<html><body><h1>Title</h1><div class="body">
<header><p class="author-name" id="p_aaaaa">By Elder Example</p>
<p class="author-role" id="p_bbbbb">Of the Quorum of the Twelve Apostles</p></header>
<p class="kicker" id="p_ccccc">An italic introduction to the talk.</p>
<p id="p_ddddd">My dear brothers and sisters, hello.</p>
<h2>A heading</h2>
<p id="p_eeeee">Second body paragraph here.</p>
<blockquote><p id="p_fffff">A quoted paragraph from someone.</p></blockquote>
<p class="mystery" id="p_ggggg">Third body paragraph with odd class.</p>
<footer class="notes"><ol><li id="note1"><p>Note one text goes here.</p></li></ol></footer>
</div></body></html>
"""

OLD_STYLE = """
<html><body><h1>Old</h1><div class="body">
<p class="author-name" id="p1">By Elder Old</p>
<p class="author-role" id="p32">Of the Seventy</p>
<p id="p2">First old body paragraph.</p>
<p id="p3">Second old body paragraph.</p>
</div></body></html>
"""


def test_new_style_kinds():
    ConferenceTalkScraper.unknown_classes.clear()
    d = ConferenceTalkScraper().extract_talk_content(NEW_STYLE)
    assert d["paragraphs"] == [
        "By Elder Example", "Of the Quorum of the Twelve Apostles", "An italic introduction to the talk.",
        "My dear brothers and sisters, hello.", "Second body paragraph here.",
        "A quoted paragraph from someone.", "Third body paragraph with odd class.",
    ]
    assert d["para_kinds"] == ["author", "role", "kicker", "body", "body", "quote", "body"]
    assert len(d["para_kinds"]) == len(d["paragraphs"]) == len(d["note_refs"])
    assert d["notes"] and "mystery" in ConferenceTalkScraper.unknown_classes
    assert paragraph_numbers(d["para_kinds"]) == [None, None, None, 1, 2, 3, 4]


def test_old_style_kinds():
    d = ConferenceTalkScraper().extract_talk_content(OLD_STYLE)
    assert d["paragraphs"][:2] == ["By Elder Old", "Of the Seventy"]
    assert d["para_kinds"] == ["author", "role", "body", "body"]
    assert paragraph_numbers(d["para_kinds"]) == [None, None, 1, 2]


def test_refresh_report(capsys):
    old = [{"url": "u1", "paragraphs": ["a", "b"]}, {"url": "u2", "paragraphs": ["x"]}]
    new = [{"url": "u1", "paragraphs": ["a", "c", "d"]}, {"url": "u2", "paragraphs": ["x"]}]
    assert report_paragraph_changes(old, new) == 1
    out = capsys.readouterr().out
    assert "u1 old=2 new=3 first differing index=1" in out and "1 of 2" in out


def test_migration_adds_columns():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.ensure_schema(c)
    c.execute("DROP TABLE paragraphs_fts")
    c.execute("DROP TABLE paragraphs")
    c.execute("CREATE TABLE paragraphs (id INTEGER PRIMARY KEY, talk_id TEXT NOT NULL, idx INTEGER NOT NULL, "
              "text TEXT NOT NULL, is_note INTEGER NOT NULL DEFAULT 0, marker INTEGER, note_refs TEXT)")
    done = migrate.apply_schema(c)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(paragraphs)")}
    assert {"num", "kind"} <= cols
    assert "paragraphs: added num" in done


def test_build_system_marks_numbers():
    talk = {"title": "T", "speaker": "S", "id": "x", "scriptures": []}
    paras = [{"text": "By S", "num": None, "is_note": False}, {"text": "Hello there.", "num": 1, "is_note": False}]
    s = build_system(talk, paras)
    assert "¶1 Hello there." in s and "By S" in s and "¶N" in s
    assert "¶N" not in build_system(talk, [{"text": "Plain text here."}])


def test_indexer_stores_num_and_kind(tmp_path, monkeypatch):
    talks = {"conferences": {"https://x/study/general-conference/2026/04?lang=eng": {"talks": [
        {"url": "https://x/study/general-conference/2026/04/01a?lang=eng", "speaker": "Elder A", "title": "A",
         "paragraphs": ["By Elder A", "First body paragraph.", "Second body paragraph."],
         "para_kinds": ["author", "body", "body"], "note_refs": [[], [], []],
         "notes": [{"n": 1, "text": "A note."}]},
        {"url": "https://x/study/general-conference/2026/04/02b?lang=eng", "speaker": "Elder B", "title": "B",
         "paragraphs": ["By Elder B", "Only body paragraph."], "note_refs": [[], []], "notes": []},
    ]}}}
    path = tmp_path / "talks.json"
    path.write_text(json.dumps(talks))
    for name in ("download_scriptures", "download_josephus"):
        monkeypatch.setattr(indexer, name, lambda *a, **k: None)
    monkeypatch.setattr(indexer, "load_scriptures_into_db", lambda *a, **k: 0)
    monkeypatch.setattr(indexer, "have_josephus", lambda: True)
    monkeypatch.setattr(indexer, "load_josephus_into_db", lambda *a, **k: 0)
    monkeypatch.setattr(indexer, "load_manuals_into_db", lambda *a, **k: 0)
    monkeypatch.setattr(indexer, "CHUNKS_NPY", tmp_path / "none.npy")
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.ensure_schema(c)
    indexer.build_index(c, talks_json=path, scriptures_json=tmp_path / "s.json", skip_embeddings=True)
    rows = lambda t: [(r["num"], r["kind"]) for r in c.execute(
        "SELECT num, kind FROM paragraphs WHERE talk_id=? ORDER BY idx", (t,))]
    assert rows("2026-04/01a") == [(None, "author"), (1, "body"), (2, "body"), (None, None)]
    assert rows("2026-04/02b") == [(None, None), (None, None)]


def test_poem_lines_are_verse():
    html = ('<html><body><h1>T</h1><div class="body"><p>Body paragraph one.</p>'
            '<div class="poetry"><div class="stanza"><p class="line">First line of the poem,</p>'
            '<p class="line">second line of the poem.</p></div></div></div></body></html>')
    d = ConferenceTalkScraper().extract_talk_content(html)
    assert d["para_kinds"] == ["body", "verse", "verse"]
    assert paragraph_numbers(d["para_kinds"]) == [1, 2, 3]
