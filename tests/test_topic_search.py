import sqlite3

import pytest

from server import db as dbm
from server import suggest as sg
from server.search import TalkHit


class Engine:
    semantic_available = False

    def search(self, q, mode, limit, *a):
        return [TalkHit("2026-10/a", 1.0, ["<mark>faith</mark> a"])]

    def manual_search(self, q, mode, limit, manual=None, audience=None, gender=None):
        self.manual_args = (audience, gender)
        return []

    def josephus_search(self, q, mode="hybrid", limit=10, work=None):
        return [TalkHit("1", 1.0, ["the <mark>faith</mark> of the people"]), TalkHit("999", 0.5, [])]


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.ensure_schema(c)
    c.execute("INSERT INTO conferences VALUES('2026-10', 2026, 10, 'October 2026', 'u')")
    c.execute("INSERT INTO talks(id, conference_id, speaker, title, url, word_count, ord) "
              "VALUES('2026-10/a', '2026-10', 'Elder A', 'Faith in Trials', 'http://a', 100, 0)")
    for v, text in [(21, "faith is not to have a perfect knowledge"), (22, "other words"), (26, "faith grows like a seed"),
                    (27, "nothing here")]:
        c.execute("INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) VALUES('Book of Mormon','Alma','Alma',32,?,?)", (v, text))
    c.execute("INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) VALUES('Book of Mormon','Ether','Ether',12,6,'faith is things hoped for')")
    c.execute("INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) VALUES('Apocrypha','Wisdom of Solomon','Wisd.',3,1,'the faith of the righteous is in the hand of God')")
    c.execute("INSERT INTO scriptures_fts(scriptures_fts) VALUES('rebuild')")
    c.execute("INSERT INTO josephus(id, work, book, chapter, section, niese_start, niese_end, chapter_title, ord, text) "
              "VALUES(1, 'antiquities', 1, 1, 1, 1, 2, 'Of the creation', 1, 'the faith of the people')")
    c.commit()
    return c


def test_group_verses_makes_passages():
    rows = [{"book": "Alma", "chapter": 32, "verse": v, "snippet": f"s{v}", "score": s}
            for v, s in [(21, 3.0), (26, 2.0)]] + [{"book": "Ether", "chapter": 12, "verse": 6, "snippet": "e", "score": 9.0}]
    out = sg.group_verses(rows, 10)
    assert [o["ref"] for o in out] == ["Ether 12:6", "Alma 32:21–26"]      # 5 + 9 vs 9: Ether single verse ranks by score sum
    assert out[1]["verses"] == 2


def test_group_verses_wide_span_shrinks_to_best_hit():
    rows = [{"book": "Psalms", "chapter": 119, "verse": v, "snippet": "", "score": s} for v, s in [(2, 1.0), (60, 5.0), (150, 1.0)]]
    (p,) = sg.group_verses(rows, 5)
    assert p["ref"] == "Psalms 119:57–63"


def test_topic_search_groups(conn):
    eng = Engine()
    r = sg.topic_search(conn, eng, "faith", "sacrament")
    assert r["audience"] == "sacrament" and eng.manual_args == ("sacrament", None)
    assert [t["ref"] for t in r["talks"]] == ["2026-10/a"] and r["talks"][0]["kind"] == "talk"
    refs = [s["ref"] for s in r["scriptures"]]
    assert "Alma 32:21–26" in refs and "Ether 12:6" in refs
    assert all(s["kind"] == "scripture" for s in r["scriptures"])
    assert [a["ref"] for a in r["apocrypha"]] == ["Wisdom of Solomon 3:1"] and r["apocrypha"][0]["kind"] == "apocrypha"
    (j,) = r["josephus"]                                  # the unknown section id is dropped
    assert j["kind"] == "josephus" and j["ref"].startswith("Antiquities 1.1.1") and j["title"] == "Of the creation"
    assert r["manuals"] == [] and r["songs"] == []


def test_topic_search_blank_query_has_no_verses(conn):
    assert sg.topic_search(conn, Engine(), "?!", "adults-male")["scriptures"] == []


def test_topic_search_keeps_gender_in_key(conn):
    eng = Engine()
    assert sg.topic_search(conn, eng, "faith", "youth-female")["audience"] == "youth-female"
    assert eng.manual_args == ("youth", "female")


# ---------------------------------------------------------------- looser verse search

def test_loose_query_drops_stopwords_ors_terms_and_keeps_phrases():
    from server.search import fts_loose_query, fts_query
    assert fts_loose_query("faith in hard times") == '"faith" OR "hard"'
    assert fts_loose_query('prayer "seems silent"') == '"seems silent" OR "prayer"'
    assert fts_loose_query("the and of") == '"the" OR "and" OR "of"'       # nothing but stopwords: keep them
    assert fts_loose_query("?!") == "" and fts_query("faith in") == '"faith" "in"'


def test_loose_verse_search_finds_what_an_and_query_misses(conn):
    conn.execute("INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) VALUES('Book of Mormon','Mosiah',"
                 "'Mosiah',24,14,'I will ease the burdens that are put upon your shoulders, even while in hard bondage')")
    conn.execute("INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) VALUES('Apocrypha','Tobit',"
                 "'Tobit',13,6,'if ye turn to him, who knoweth whether he will accept you, in hard times')")
    conn.execute("INSERT INTO scriptures_fts(scriptures_fts) VALUES('rebuild')")
    from server.search import fts_query
    from server.scriptures import search_verses
    assert search_verses(conn, fts_query("faith in hard times"), 20) == []           # every word in one verse
    std = [p["ref"] for p in sg._verse_group(conn, "faith in hard times", False, 8)]
    assert "Alma 32:21–26" in std and "Mosiah 24:14" in std and "Ether 12:6" in std
    apo = [p["ref"] for p in sg._verse_group(conn, "faith in hard times", True, 5)]
    assert set(apo) == {"Wisdom of Solomon 3:1", "Tobit 13:6"}
    assert all(p["verses"] <= sg.PASSAGE_SPAN for p in sg._verse_group(conn, "faith", False, 8))


# ---------------------------------------------------------------- refine any group

from server.ai.base import Provider, ProviderError


class Fake(Provider):
    name = "fake"
    model = "fake-1"

    def __init__(self, data):
        self.data = data

    def generate_json(self, system, user_message, schema):
        self.system, self.msg, self.schema = system, user_message, schema
        return self.data


def _items(conn, group):
    return [{k: v for k, v in it.items() if k in ("ref", "title", "subtitle", "snippet")}
            for it in sg.topic_search(conn, Engine(), "faith", "sacrament")[group]]


def test_refine_group_validates_picks_against_candidates(conn):
    items = _items(conn, "josephus")
    ref = items[0]["ref"]
    p = Fake({"picks": [{"ref": ref, "reason": " Good background. "}, {"ref": ref, "reason": "dup"},
                        {"ref": "Antiquities 9.9.9", "reason": "invented"}]})
    r = sg.refine_group(conn, p, "faith", "adults-male", "josephus", items)
    assert r["picks"] == [{"ref": ref, "reason": "Good background."}] and r["additions"] == []
    assert "history, not scripture" in p.system and "additions" not in p.schema["properties"]
    assert "Excerpt: the faith of the people" in p.msg and "<mark>" not in p.msg


def test_refine_talks_group_uses_opening_text_and_drops_unknown_ids(conn):
    conn.execute("INSERT INTO paragraphs(talk_id, idx, text, is_note) VALUES('2026-10/a', 2, 'Opening words here', 0)")
    p = Fake({"picks": [{"ref": "2026-10/a", "reason": "Fits."}, {"ref": "2026-10/zzz", "reason": "no"}]})
    r = sg.refine_group(conn, p, "faith", "sacrament", "talks",
                        [{"ref": "2026-10/a", "title": "Faith in Trials"}, {"ref": "2026-10/zzz", "title": "Ghost"}])
    assert [x["ref"] for x in r["picks"]] == ["2026-10/a"]
    assert "Opening: Opening words here" in p.msg and "Ghost" not in p.msg
    assert "sacrament meeting talk" in p.system and "teacher" not in p.system


def test_refine_group_audience_wording(conn):
    items = _items(conn, "josephus")
    cls = Fake({"picks": []})
    sg.refine_group(conn, cls, "faith", "adults-female", "josephus", items)
    assert "teacher" in cls.system and "Relief Society" in cls.system
    per = Fake({"picks": []})
    sg.refine_group(conn, per, "faith", "personal", "josephus", items)
    assert "on their own" in per.system
    assert "—" not in cls.system + per.system


def test_refine_group_rejects_bad_input(conn):
    with pytest.raises(ProviderError):
        sg.refine_group(conn, Fake({"picks": []}), "faith", "personal", "videos", [])
    with pytest.raises(ProviderError):
        sg.refine_group(conn, Fake({"picks": []}), "faith", "personal", "songs", [])


def test_refine_scriptures_accepts_new_valid_passages_only(conn):
    items = _items(conn, "scriptures")
    p = Fake({"picks": [{"ref": "Ether 12:6", "reason": "Defines faith."}, {"ref": "Alma 99:1", "reason": "not a candidate"}],
              "additions": [
                  {"ref": "Alma 32:21-26", "reason": "Already found."},      # a candidate: becomes a pick
                  {"ref": "Alma 32:26", "reason": "The seed."},              # new
                  {"ref": "Alma 32:26", "reason": "Duplicate."},
                  {"ref": "Alma 99:1", "reason": "No such chapter."},
                  {"ref": "Alma 32:500", "reason": "No such verse."},
                  {"ref": "Wisdom of Solomon 3:1", "reason": "Wrong volume."},
                  {"ref": "not a ref", "reason": "Garbage."}]})
    r = sg.refine_group(conn, p, "faith", "adults-male", "scriptures", items)
    assert [x["ref"] for x in r["picks"]] == ["Ether 12:6", "Alma 32:21–26"]
    assert [a["ref"] for a in r["additions"]] == ["Alma 32:26"]
    a = r["additions"][0]
    assert a["kind"] == "scripture" and a["title"] == "Alma 32:26" and a["verses"] == 1 and a["reason"] == "The seed."
    assert a["snippet"] == "faith grows like a seed"
    assert "additions" in p.schema["properties"]
    assert "not part of the standard works" not in p.system


def test_refine_apocrypha_takes_only_apocrypha_passages(conn):
    conn.execute("INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) VALUES('Apocrypha','Tobit','Tobit',4,15,'Do that to no man which thou hatest')")
    items = _items(conn, "apocrypha")
    p = Fake({"picks": [], "additions": [{"ref": "Tobit 4:15", "reason": "Fits."}, {"ref": "Alma 32:26", "reason": "Wrong volume."}]})
    r = sg.refine_group(conn, p, "faith", "personal", "apocrypha", items)
    assert [a["ref"] for a in r["additions"]] == ["Tobit 4:15"] and r["additions"][0]["kind"] == "apocrypha"
    assert "not part of the standard works" in p.system


def test_refine_passage_is_capped(conn):
    for v in range(1, 31):
        conn.execute("INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) VALUES('Book of Mormon','1 Nephi','1 Ne.',3,?,?)",
                     (v, f"verse {v}"))
    p = Fake({"picks": [], "additions": [{"ref": "1 Nephi 3:5-30", "reason": "Long."}, {"ref": "1 Nephi 3", "reason": "Whole chapter."}]})
    r = sg.refine_group(conn, p, "obedience", "personal", "scriptures", [])
    assert [(a["ref"], a["verses"]) for a in r["additions"]] == [("1 Nephi 3:5–16", 12), ("1 Nephi 3:1–12", 12)]


def test_refine_endpoint_rate_limit_and_validation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import server.main as main
    import server.routers.suggest as sug
    from server.auth import create_user
    monkeypatch.setattr(dbm, "DB_PATH", tmp_path / "app.db")
    p = Fake({"picks": [], "additions": []})
    monkeypatch.setattr(sug, "get_provider", lambda settings: p)
    body = {"topic": "faith", "audience": "sacrament", "group": "scriptures", "items": []}
    with TestClient(main.app) as c:
        assert c.post("/api/topic-search/refine", json=body).status_code == 401
        create_user(c.app.state.conn, "a@example.com", is_admin=False, password="correct horse battery")
        c.post("/api/auth/login", json={"email": "a@example.com", "password": "correct horse battery"})
        ok = c.post("/api/topic-search/refine", json=body)
        assert ok.status_code == 200 and ok.json()["group"] == "scriptures" and ok.json()["additions"] == []
        assert c.post("/api/topic-search/refine", json={**body, "group": "videos"}).status_code == 422
        assert c.post("/api/topic-search/refine", json={**body, "audience": "bogus"}).status_code == 422
        too_many = [{"ref": str(i)} for i in range(sg.MAX_REFINE + 1)]
        assert c.post("/api/topic-search/refine", json={**body, "items": too_many}).status_code == 422
        assert c.post("/api/topic-search/refine", json={**body, "group": "songs", "items": []}).status_code == 400
