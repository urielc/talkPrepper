import json
import sqlite3

import pytest

from server import db as dbm
from server.indexer import (
    chunk_paragraphs, mark_notes, talk_id_from_url, parse_conference_url, _resolve_title,
    speaker_from_paragraphs,
)
from server.search import fts_query, fts_or_query, rrf_fuse, TalkHit


def test_ids_from_urls():
    assert parse_conference_url("https://x/study/general-conference/2026/04?lang=eng") == ("2026-04", 2026, 4)
    assert talk_id_from_url("https://x/study/general-conference/2026/04/46renlund?lang=eng") == "2026-04/46renlund"
    assert talk_id_from_url("https://x/study/general-conference/2026/04?lang=eng") is None


def test_mark_notes_block_at_end():
    paras = ["By Elder X", "Body one " * 20, "Body two " * 20, "Body three " * 20, "More body " * 20,
             "See Alma 32:21.", "Russell M. Nelson, “Think Celestial!,” Liahona, Nov. 2023, 117.", "Doctrine and Covenants 76:75."]
    flags = mark_notes(paras)
    assert flags == [False, False, False, False, False, True, True, True]


def test_mark_notes_requires_block():
    paras = ["Body " * 30, "Body " * 30, "See Alma 32:21."]
    # a single trailing citation-like paragraph is not a notes block
    assert mark_notes(paras) == [False, False, False]


def test_mark_notes_catches_unquoted_citation_forms():
    body = ["Body text. " * 20] * 6
    notes = [
        "Russell M. Nelson, “Faith and Families” (Brigham Young University fireside, Feb. 6, 2005), 3, speeches.byu.edu.",
        "Russell M. Nelson, “Open the Heavens Through Temple and Family History Work,” Ensign, Oct. 2017, 38.",
        "Doctrine and Covenants 138:57.",
    ]
    flags = mark_notes(body + notes)
    assert flags == [False] * 6 + [True] * 3


def test_mark_notes_ignores_closing_scripture_quotes():
    # Older talks end with scripture quotations and have no footnotes.
    paras = ["Body text. " * 20] * 5 + [
        "“By this shall all men know that ye are my disciples, if ye have love one to another.” (John 13:34–35.)",
        "In the name of Jesus Christ, amen. (See 3 Nephi 11:14.)",
    ]
    assert not any(mark_notes(paras))


def test_speaker_from_presented_by():
    assert speaker_from_paragraphs(["Presented by President D. Todd Christofferson", "..."]) == "President D. Todd Christofferson"
    assert speaker_from_paragraphs(["Something else"]) == ""


def test_chunking_groups_paragraphs():
    paras = [(i, ("word " * 60).strip()) for i in range(10)]   # 600 words
    chunks = chunk_paragraphs(paras)
    assert 2 <= len(chunks) <= 4
    assert chunks[0][0] == 0 and chunks[-1][1] == 9
    # contiguous, no gaps
    for (a, b, _), (c, d, _) in zip(chunks, chunks[1:]):
        assert c == b + 1


def test_resolve_title():
    cands = [("think celestial", "2023-10/x"), ("come join with us", "2013-10/y")]
    assert _resolve_title(cands, "Think Celestial!") == "2023-10/x"
    assert _resolve_title(cands, "Come, Join with Us") == "2013-10/y"
    assert _resolve_title(cands, "Nothing like it") is None


def test_fts_query_is_safe():
    assert fts_query('broken heart') == '"broken" "heart"'
    assert fts_query('“contrite spirit” AND (evil)') == '"contrite spirit" "AND" "evil"'
    assert fts_query("Nephi's") == '"Nephi\'\'s"'
    assert fts_or_query(["a", "", "b"]) == '"a" OR "b"'


def test_rrf_fuse_prefers_agreement():
    kw = [TalkHit("A", 10, ["ka"], {"keyword"}), TalkHit("B", 5, ["kb"], {"keyword"})]
    sem = [TalkHit("B", 0.9, ["sb"], {"semantic"}), TalkHit("C", 0.8, ["sc"], {"semantic"})]
    fused = rrf_fuse([kw, sem], 10)
    assert fused[0].talk_id == "B"
    assert fused[0].sources == {"keyword", "semantic"}
    assert fused[0].snippets == ["kb", "sb"]
    assert fused[0].score == 1.0


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.ensure_schema(c)
    c.execute("INSERT INTO conferences VALUES('2026-04', 2026, 4, 'April 2026', 'u')")
    c.execute("INSERT INTO talks VALUES('2026-04/a', '2026-04', 'Elder A', 'Talk A', 'http://a', 10, 0)")
    c.execute("INSERT INTO talks VALUES('2026-04/b', '2026-04', 'Elder B', 'Talk B', 'http://b', 10, 1)")
    c.execute("INSERT INTO paragraphs(talk_id, idx, text, is_note) VALUES('2026-04/a', 0, 'Faith is a principle of action.', 0)")
    c.execute("INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) VALUES('BoM','Alma','Alma',32,21,'And now as I said concerning faith')")
    c.commit()
    return c


def test_export_html_renders_notes_and_pins(conn):
    from server.routers.lessons import render_export
    conn.execute("INSERT INTO lessons(talk_id, notes_md) VALUES('2026-04/a', '# Outline\n\n- point **one**')")
    conn.execute("INSERT INTO pins(talk_id, kind, scripture_ref, text, note, ord) VALUES('2026-04/a','scripture','Alma 32:21','21 And now…','why',0)")
    conn.execute("INSERT INTO pins(talk_id, kind, ref_talk_id, ref_paragraph_id, text, ord) VALUES('2026-04/a','quote','2026-04/b',1,'A <quote>',1)")
    conn.execute("INSERT INTO pins(talk_id, kind, text, ord) VALUES('2026-04/a','note','free text',2)")
    conn.commit()
    html = render_export(conn, "2026-04/a")
    assert "<h1>Talk A</h1>" in html
    assert "<strong>one</strong>" in html
    assert "Alma 32:21" in html and "why" in html
    assert "A &lt;quote&gt;" in html          # escaped
    assert "Talk B" in html and "Elder B" in html
    assert "free text" in html
