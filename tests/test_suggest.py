import json
import sqlite3

import pytest

from server import db as dbm
from server import suggest as sg
from server.ai import digest as dg
from server.ai.base import Provider
from server.ai.prompts import build_system
from server.audience import audience_key, class_name, parse_calling, talk_audience_tags
from server.search import TalkHit


# ---------------------------------------------------------------- audience

@pytest.mark.parametrize("audience,gender,key,name", [
    ("adults", "male", "adults-male", "an elders quorum"),
    ("adults", "female", "adults-female", "a Relief Society"),
    ("adults", "any", "adults", "an adult Sunday School class"),
    ("youth", "male", "youth-male", "an Aaronic Priesthood quorum"),
    ("youth", "female", "youth-female", "a Young Women class"),
    ("youth", None, "youth", "a youth Sunday School class"),
    ("children", "female", "children", "a Primary class"),
    ("nonsense", "male", "adults-male", "an elders quorum"),
])
def test_audience_key_and_class(audience, gender, key, name):
    assert audience_key(audience, gender) == key
    assert class_name(key) == name


def test_parse_calling():
    assert parse_calling(["By Sister J. Anette Dennis", "First Counselor in the Relief Society General Presidency",
                          "Only the Lord fully knows."]) == "First Counselor in the Relief Society General Presidency"
    assert parse_calling(["By Elder A", "Of the Quorum of the Twelve Apostles", "Text."]) == \
        "Of the Quorum of the Twelve Apostles"
    assert parse_calling(["By Elder A", "My dear brothers and sisters, I am grateful.", "Text."]) == ""


def test_talk_audience_tags():
    assert talk_audience_tags("A Child of God", "Sister C", "Primary General President", "Hello.") == ["children"]
    assert set(talk_audience_tags("Be Strong", "Sister Y", "Young Women General President", "x")) == {"youth", "female"}
    women = "My dear sisters, " + "we gather as sisters in the covenant. " * 10 + "word " * 300
    assert "female" in talk_audience_tags("Gather", "Elder Z", "Of the Seventy", women)
    priesthood = "Brethren, " + "brethren of the priesthood stand. " * 10 + "word " * 300
    assert "male" in talk_audience_tags("Stand", "Elder Z", "Of the Seventy", priesthood)
    # Session business names every auxiliary but is for no one.
    assert talk_audience_tags("The Sustaining of Church Officers", "P", "", "Primary Primary Primary Primary") == []


# ---------------------------------------------------------------- suggestions

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.ensure_schema(c)
    c.execute("INSERT INTO conferences VALUES('2026-10', 2026, 10, 'October 2026', 'u')")
    rows = [("2026-10/a", "Elder A", "Forgive Freely", "Of the Seventy", ""),
            ("2026-10/b", "Sister B", "Forgiveness for Young Women", "Young Women General President", "youth female"),
            ("2026-10/c", "Elder C", "Brethren, Forgive", "Of the Seventy", "male")]
    for i, (tid, sp, title, calling, tags) in enumerate(rows):
        c.execute("INSERT INTO talks(id, conference_id, speaker, title, url, word_count, ord, calling, audience_tags) "
                  "VALUES(?,?,?,?,?,?,?,?,?)", (tid, "2026-10", sp, title, f"http://{tid}", 100, i, calling, tags))
        for idx, text in enumerate([f"By {sp}", calling, f"{title}: a talk about forgiveness."]):
            c.execute("INSERT INTO paragraphs(talk_id, idx, text, is_note) VALUES(?,?,?,0)", (tid, idx, text))
    c.commit()
    return c


class FakeEngine:
    semantic_available = False

    def search(self, q, mode, limit, *a):
        return [TalkHit("2026-10/c", 1.0, ["<mark>forgive</mark> c"]), TalkHit("2026-10/a", 0.95, ["a"]),
                TalkHit("2026-10/b", 0.9, ["b"])]

    def manual_search(self, q, mode, limit, manual=None, audience=None, gender=None):
        self.manual_args = (audience, gender)
        self.manual_keys = getattr(self, "manual_keys", []) + [manual]
        return []


def test_suggest_boosts_audience(conn):
    eng = FakeEngine()
    plain = sg.suggest(conn, eng, "forgiveness", "adults", "any")
    assert [t["id"] for t in plain["talks"]] == ["2026-10/c", "2026-10/a", "2026-10/b"]
    women = sg.suggest(conn, eng, "forgiveness", "youth", "female")
    assert [t["id"] for t in women["talks"]][0] == "2026-10/b"       # youth + female boost
    assert women["talks"][-1]["id"] == "2026-10/c"                    # the priesthood talk drops
    assert women["audience"] == "youth-female" and eng.manual_args == ("youth", "female")
    lessons, songs = eng.manual_keys[-2:]          # searched separately
    assert "hymns" in songs and "childrens-songbook" in songs and "hymns" not in lessons and "cfm-ot-2026" in lessons
    t = women["talks"][0]
    assert t["title"] == "Forgiveness for Young Women" and t["conference"] == "October 2026"
    assert t["calling"] == "Young Women General President" and t["snippet"] == "b"


class RefineProvider(Provider):
    name = "fake"
    model = "fake-1"

    def __init__(self):
        self.calls = []

    def generate_json(self, system, user_message, schema):
        self.calls.append((system, user_message))
        return {"picks": [{"talk_id": "2026-10/b", "reason": "Speaks to young women."},
                          {"talk_id": "2026-10/zzz", "reason": "Made up."},
                          {"talk_id": "[2026-10/a]", "reason": "General."},
                          {"talk_id": "2026-10/b", "reason": "Duplicate."}]}


def test_refine_keeps_only_candidates(conn):
    p = RefineProvider()
    r = sg.refine(conn, p, "forgiveness", "youth", "female", ["2026-10/a", "2026-10/b"])
    assert r["picks"] == [{"talk_id": "2026-10/b", "reason": "Speaks to young women."},
                          {"talk_id": "2026-10/a", "reason": "General."}]
    system, msg = p.calls[0]
    assert "Young Women class" in msg and "[2026-10/b] “Forgiveness for Young Women”" in msg
    assert "2026-10/c" not in msg                                     # not a candidate


# ---------------------------------------------------------------- prompts follow the audience

def test_prompts_follow_audience():
    talk = {"id": "x", "title": "T", "speaker": "S", "conference": "C"}
    assert "lead an elders quorum discussion" in build_system(talk, [])
    assert "lead a Relief Society discussion" in build_system(talk, [], "adults-female")
    assert "for a Primary class of children" in dg.system_prompt("children")
    assert "for a quorum of adult men" in dg.system_prompt()


class DigestProvider(Provider):
    name, model = "fake", "fake-1"

    def __init__(self):
        self.systems = []

    def generate_json(self, system, user_message, schema):
        self.systems.append(system)
        return {"essence": "e", "main_points": [], "key_quotes": [], "questions": []}


def test_digest_cached_per_audience(conn, monkeypatch):
    fake = DigestProvider()
    monkeypatch.setattr(dg, "get_provider", lambda settings: fake)
    talk = {"id": "2026-10/a", "title": "T", "speaker": "S", "conference": "C"}
    dg.generate_digest(conn, talk, [], "adults-female")
    assert dg.load_digest(conn, "2026-10/a") is None                  # elders quorum digest not made
    assert dg.load_digest(conn, "2026-10/a", "adults-female")["essence"] == "e"
    assert "Relief Society" in fake.systems[0]


def test_migrates_old_digests_and_talks():
    from server.migrate import apply_schema
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE digests (talk_id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
                              json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO digests(talk_id, provider, model, json) VALUES('2026-10/a', 'p', 'm', '{}');
        CREATE TABLE talks (id TEXT PRIMARY KEY, conference_id TEXT NOT NULL, speaker TEXT NOT NULL DEFAULT '',
                            title TEXT NOT NULL DEFAULT '', url TEXT NOT NULL, word_count INTEGER NOT NULL DEFAULT 0,
                            ord INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE working_on (user_id INTEGER, talk_id TEXT NOT NULL, added_at TEXT, ord INTEGER NOT NULL DEFAULT 0,
                                 PRIMARY KEY (user_id, talk_id));
    """)
    steps = apply_schema(c)
    assert "digests: keyed by talk and audience" in steps and "talks: added calling" in steps
    assert dict(c.execute("SELECT talk_id, audience FROM digests").fetchone()) == \
        {"talk_id": "2026-10/a", "audience": "adults-male"}
    assert apply_schema(c) == []                                      # idempotent


# ---------------------------------------------------------------- API

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from server import db as dbm_
    monkeypatch.setattr(dbm_, "DB_PATH", tmp_path / "app.db")
    import server.main as main
    with TestClient(main.app) as c:
        conn = c.app.state.conn
        conn.execute("INSERT INTO conferences VALUES('2026-10', 2026, 10, 'October 2026', 'u')")
        conn.execute("INSERT INTO talks(id, conference_id, speaker, title, url, word_count, ord, audience_tags) "
                     "VALUES('2026-10/a', '2026-10', 'Elder A', 'Forgive Freely', 'http://a', 10, 0, '')")
        conn.execute("INSERT INTO paragraphs(talk_id, idx, text, is_note) VALUES('2026-10/a', 0, 'Forgiveness heals.', 0)")
        conn.execute("INSERT INTO paragraphs_fts(paragraphs_fts) VALUES('rebuild')")
        conn.commit()
        yield c


def _login(client):
    from server.auth import create_user
    create_user(client.app.state.conn, "s@example.com", password="correct horse battery")
    assert client.post("/api/auth/login", json={"email": "s@example.com",
                                                "password": "correct horse battery"}).status_code == 200


def test_suggest_api(client):
    assert client.post("/api/suggest", json={"topic": "forgiveness"}).status_code == 401
    _login(client)
    r = client.post("/api/suggest", json={"topic": "forgiveness", "audience": "adults", "gender": "female"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audience"] == "adults-female" and body["talks"][0]["id"] == "2026-10/a"
    assert body["talks"][0]["conference"] == "October 2026" and body["manuals"] == []
    assert client.post("/api/suggest", json={"topic": "x", "audience": "elders"}).status_code == 422


def test_lesson_audience_api(client):
    _login(client)
    r = client.put("/api/my-lessons", json={"talk_id": "2026-10/a", "audience": "youth-female"})
    assert r.status_code == 200 and r.json()[0]["audience"] == "youth-female"
    assert client.get("/api/talks/2026-10/a").json()["lesson"]["audience"] == "youth-female"
    r = client.put("/api/my-lessons/2026-10/a/audience", json={"audience": "children"})
    assert r.json() == {"audience": "children", "audience_label": "Primary class"}
    # Re-adding without an audience keeps the one set.
    client.put("/api/my-lessons", json={"talk_id": "2026-10/a"})
    assert client.get("/api/my-lessons").json()[0]["audience"] == "children"
    assert client.put("/api/my-lessons/2026-10/a/audience", json={"audience": "bogus"}).status_code == 422
