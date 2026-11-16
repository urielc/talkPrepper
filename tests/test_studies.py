"""Topic studies: source gathering, summary generation with a fake provider, and the studies router."""

from __future__ import annotations

import json
import sqlite3

import pytest

from server import db as dbm
from server.ai import study as sty
from server.ai.base import Provider, ProviderError
from server.search import TalkHit

TALK_TEXT = "Faith is a principle of action and of power. " * 3


class FakeEngine:
    semantic_available = False

    def search(self, q, mode, limit, *a):
        return [TalkHit("2026-10/a", 1.0, ["<mark>faith</mark> a"]), TalkHit("2026-10/b", 0.8, ["b"])]

    def manual_search(self, q, mode, limit, manual=None, audience=None, gender=None):
        return [TalkHit("1", 1.0, ["manual snippet"])]

    def josephus_search(self, q, mode="hybrid", limit=10, work=None):
        return []

    def related_to_text(self, query, exclude=None, limit=20):
        self.related_args = (query, exclude)
        return [h for h in self.search(query, "hybrid", limit) if h.talk_id not in (exclude or [])]


class FakeProvider(Provider):
    name = "fake"
    model = "fake-1"

    def __init__(self, data=None):
        self.calls = []
        self.data = data

    def generate_json(self, system, user_message, schema):
        self.calls.append((system, user_message, schema))
        if self.data is not None:
            return self.data
        return {
            "overview": "Faith leads to action.",
            "themes": [{"heading": "Faith and works", "body": "Both matter.", "sources": ["S1", "S9", "[S2]"]}],
            "key_quotes": [
                {"text": "Faith is a principle of action and of power.", "source": "S1", "why": "Thesis."},
                {"text": "Made up words nobody said.", "source": "S1", "why": "Fabricated."},
                {"text": "Orphan quote.", "source": "S7", "why": "Bad label."}],
            "scriptures": ["Alma 32:21", "Alma 99:99", "not a ref"],
            "ponder": [{"question": "Where do you act on faith?", "kind": "application", "note": "Personal."}],
            "further": [{"candidate_id": "C1", "why": "Related talk."}, {"candidate_id": "C99", "why": "Invented."},
                        {"candidate_id": "[C1]", "why": "Duplicate."}],
        }


def seed(c: sqlite3.Connection) -> None:
    c.execute("INSERT INTO conferences VALUES('2026-10', 2026, 10, 'October 2026', 'u')")
    for i, (tid, title) in enumerate([("2026-10/a", "Faith in Trials"), ("2026-10/b", "More Faith")]):
        c.execute("INSERT INTO talks(id, conference_id, speaker, title, url, word_count, ord) "
                  "VALUES(?, '2026-10', 'Elder A', ?, 'http://a', 100, ?)", (tid, title, i))
        c.execute("INSERT INTO paragraphs(talk_id, idx, text, is_note, num) VALUES(?, 0, 'By Elder A', 0, NULL)", (tid,))
        c.execute("INSERT INTO paragraphs(talk_id, idx, text, is_note, num) VALUES(?, 1, ?, 0, 1)", (tid, TALK_TEXT))
        c.execute("INSERT INTO paragraphs(talk_id, idx, text, is_note, num) VALUES(?, 2, 'A footnote.', 1, NULL)", (tid,))
    c.execute("INSERT INTO scriptures(volume, book, book_short, chapter, verse, text) "
              "VALUES('Book of Mormon','Alma','Alma',32,21,'faith is not to have a perfect knowledge')")
    c.execute("INSERT INTO manuals(key, title, kind, audience, ord) VALUES('gt', 'Gospel Topics', 'Gospel Topics', 'adults', 0)")
    c.execute("INSERT INTO manual_pages(id, uri, manual_key, title, audience, ord, url, word_count) "
              "VALUES(1, '/manual/gt/faith', 'gt', 'Faith', 'adults', 0, 'http://m', 10)")
    c.execute("INSERT INTO manual_paragraphs(page_id, idx, text, heading) VALUES(1, 0, 'Faith', 1)")
    c.execute("INSERT INTO manual_paragraphs(page_id, idx, text, heading) VALUES(1, 1, 'Faith is trust in God.', 0)")
    c.commit()


SOURCES = [{"kind": "talk", "ref": "2026-10/a", "title": "Faith in Trials"},
           {"kind": "manual", "ref": "/manual/gt/faith", "title": "Faith"},
           {"kind": "scripture", "ref": "Alma 32:21", "title": "Alma 32:21"},
           {"kind": "talk", "ref": "2000-01/gone", "title": "Deleted talk"}]


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.ensure_schema(c)
    seed(c)
    return c


# ---------------------------------------------------------------- unit

def test_gather_labels_skips_missing_and_numbers_paragraphs(conn):
    loaded, missing = sty.gather(conn, SOURCES)
    assert [x["label"] for x in loaded] == ["S1", "S2", "S3"]
    assert [m["ref"] for m in missing] == ["2000-01/gone"]
    assert "¶1 Faith is a principle" in loaded[0]["text"] and "footnote" not in loaded[0]["text"]
    assert loaded[1]["text"].startswith("# Faith") and loaded[2]["text"].startswith("21 faith")


def test_trim_longest_first_and_cap():
    texts = ["a " * 5000, "b " * 100, "c " * 3000]
    flags = sty.trim_to_budget(texts, 4000)
    assert sum(len(t.split()) for t in texts) <= 4000 + len(texts)       # the "[…]" marker adds a word each
    assert flags == [True, False, True]                                   # longest first
    assert not flags[1] and texts[1] == "b " * 100


def test_candidates_exclude_queued_and_get_ids(conn):
    out = sty.candidates(conn, FakeEngine(), "faith", {("talk", "2026-10/a")})
    assert [(c["id"], c["kind"], c["ref"]) for c in out] == [("C1", "talk", "2026-10/b"), ("C2", "manual", "/manual/gt/faith")]


def make_study(conn, audience="adults-male", modifier="", sources=SOURCES, uid=1):
    cur = conn.execute("INSERT INTO studies(user_id, topic, audience, modifier, sources_json) VALUES(?,?,?,?,?)",
                       (uid, "faith", audience, modifier, json.dumps(sources)))
    conn.commit()
    return {"id": cur.lastrowid, "topic": "faith", "audience": audience, "modifier": modifier, "sources": sources}


def test_generate_validates_and_stores(conn, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(sty, "get_provider", lambda settings: fake)
    s = make_study(conn, modifier="Keep it short.")
    out = sty.generate_study(conn, FakeEngine(), 1, s)["summary"]
    system, user, schema = fake.calls[0]
    assert schema is sty.SUMMARY_SCHEMA and "elders quorum" in system
    assert "[S1] Conference talk: Faith in Trials" in user and "[C1]" in user and "Elder A" in user
    assert "Additional instructions from the user" in user and "Keep it short." in user
    assert "2026-10/a" not in user.split("CANDIDATES")[1]                 # queued talks are not suggested
    assert out["themes"][0]["sources"] == ["S1", "S2"]                    # S9 dropped, [S2] unwrapped
    assert [(q["source"], q["verified"]) for q in out["key_quotes"]] == [("S1", True), ("S1", False)]
    assert out["scriptures"] == ["Alma 32:21"]
    assert [(f["candidate_id"], f["ref"]) for f in out["further"]] == [("C1", "2026-10/b")]
    assert [x["label"] for x in out["source_labels"]] == ["S1", "S2", "S3"]
    assert out["missing"][0]["ref"] == "2000-01/gone"
    assert out["provider"] == "fake"
    again = conn.execute("SELECT summary_json, model FROM studies WHERE id=?", (s["id"],)).fetchone()
    assert json.loads(again["summary_json"])["overview"] == "Faith leads to action." and again["model"] == "fake-1"


@pytest.mark.parametrize("audience,needle,absent", [
    ("sacrament", "sacrament meeting talk", "teacher note"),
    ("personal", "studying on their own", "teacher note"),
    ("youth-female", "Young Women class", "sacrament"),
])
def test_system_prompt_by_audience(audience, needle, absent):
    p = sty.system_prompt(audience)
    assert needle in p and absent not in p and "{" not in p and "—" not in p


def test_schema_is_strict():
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False and set(node["required"]) == set(node["properties"])
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)
    check(sty.SUMMARY_SCHEMA)


def test_no_sources_found_is_an_error(conn, monkeypatch):
    monkeypatch.setattr(sty, "get_provider", lambda settings: FakeProvider())
    s = make_study(conn, sources=[{"kind": "talk", "ref": "nope", "title": "x"}])
    with pytest.raises(ProviderError):
        sty.generate_study(conn, FakeEngine(), 1, s)


# ---------------------------------------------------------------- router

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(dbm, "DB_PATH", tmp_path / "app.db")
    import server.main as main
    with TestClient(main.app) as c:
        seed(c.app.state.conn)
        c.app.state.engine = FakeEngine()
        yield c


def login(client, email):
    from server.auth import create_user
    create_user(client.app.state.conn, email, is_admin=False, password="correct horse battery")
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"email": email, "password": "correct horse battery"})
    assert r.status_code == 200, r.text


BODY = {"topic": "faith in hard times", "audience": "sacrament", "sources": SOURCES[:3], "modifier": "Short."}


def test_requires_login(client):
    assert client.post("/api/studies", json=BODY).status_code == 401
    assert client.post("/api/topic-search", json={"topic": "faith"}).status_code == 401


def test_create_get_patch_delete(client, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(sty, "get_provider", lambda settings: fake)
    login(client, "a@example.com")
    r = client.post("/api/studies", json=BODY)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["key"] == f"study:{s['id']}" and s["error"] is None and s["audience"] == "sacrament"
    assert s["summary"]["overview"] == "Faith leads to action." and "sacrament meeting talk" in fake.calls[0][0]
    wo = client.app.state.conn.execute("SELECT audience FROM working_on WHERE talk_id=?", (s["key"],)).fetchone()
    assert wo["audience"] == "sacrament"
    assert client.get(f"/api/studies/{s['id']}").json()["topic"] == "faith in hard times"

    p = client.patch(f"/api/studies/{s['id']}", json={"modifier": "Longer.", "audience": "personal",
                                                      "sources": SOURCES[:2]}).json()
    assert p["modifier"] == "Longer." and p["audience"] == "personal" and len(p["sources"]) == 2
    assert p["summary"] is not None                                  # kept until regenerated
    g = client.post(f"/api/studies/{s['id']}/generate")
    assert g.status_code == 200 and "Longer." in fake.calls[-1][1] and "studying on their own" in fake.calls[-1][0]

    # lesson rows keyed by the study go with it
    conn = client.app.state.conn
    conn.execute("INSERT INTO lessons(user_id, talk_id) VALUES(1, ?)", (s["key"],))
    conn.execute("INSERT INTO pins(user_id, talk_id, kind, text) VALUES(1, ?, 'note', 'x')", (s["key"],))
    conn.commit()
    assert client.delete(f"/api/studies/{s['id']}").json() == {"ok": True}
    assert client.get(f"/api/studies/{s['id']}").status_code == 404
    for t in ("lessons", "pins", "working_on"):
        assert conn.execute(f"SELECT COUNT(*) FROM {t} WHERE talk_id=?", (s["key"],)).fetchone()[0] == 0


def test_owner_only(client, monkeypatch):
    monkeypatch.setattr(sty, "get_provider", lambda settings: FakeProvider())
    login(client, "a@example.com")
    sid = client.post("/api/studies", json=BODY).json()["id"]
    login(client, "b@example.com")
    assert client.get(f"/api/studies/{sid}").status_code == 404
    assert client.patch(f"/api/studies/{sid}", json={"modifier": "x"}).status_code == 404
    assert client.post(f"/api/studies/{sid}/generate").status_code == 404
    assert client.delete(f"/api/studies/{sid}").status_code == 404
    assert client.get(f"/api/studies/{sid}/related").status_code == 404
    assert client.get(f"/api/studies/{sid}/scriptures").status_code == 404


def test_validation(client):
    login(client, "a@example.com")
    assert client.post("/api/studies", json={**BODY, "audience": "bogus"}).status_code == 422
    assert client.post("/api/studies", json={**BODY, "sources": []}).status_code == 422
    too_many = [{"kind": "scripture", "ref": f"Alma {i}:1", "title": "x"} for i in range(1, 14)]
    assert client.post("/api/studies", json={**BODY, "sources": too_many}).status_code == 422
    assert client.post("/api/studies", json={**BODY, "sources": [{"kind": "video", "ref": "x"}]}).status_code == 422
    assert client.post("/api/topic-search", json={"topic": "faith", "audience": "bogus"}).status_code == 422


def test_ai_failure_keeps_the_study(client, monkeypatch):
    def boom(settings):
        raise ProviderError("No AI provider set up.")
    monkeypatch.setattr(sty, "get_provider", boom)
    login(client, "a@example.com")
    s = client.post("/api/studies", json=BODY).json()
    assert s["error"] == "No AI provider set up." and s["summary"] is None
    assert client.post(f"/api/studies/{s['id']}/generate").status_code == 400
    assert client.get(f"/api/studies/{s['id']}").status_code == 200


def test_related_and_scriptures(client, monkeypatch):
    monkeypatch.setattr(sty, "get_provider", lambda settings: FakeProvider())
    conn = client.app.state.conn
    conn.execute("INSERT INTO scripture_refs(talk_id, paragraph_id, book, chapter, verse_start, verse_end, raw, char_start, char_end) "
                 "VALUES('2026-10/b', 1, 'Alma', 32, 21, 21, 'Alma 32:21', 0, 5)")
    conn.commit()
    login(client, "a@example.com")
    sid = client.post("/api/studies", json=BODY).json()["id"]
    rel = client.get(f"/api/studies/{sid}/related").json()
    assert [r["talk_id"] for r in rel["results"]] == ["2026-10/b"]      # the queued talk is excluded
    assert "faith in hard times" in client.app.state.engine.related_args[0]
    assert "Faith and works" in client.app.state.engine.related_args[0]  # theme headings join the query
    sc = client.get(f"/api/studies/{sid}/scriptures").json()
    assert [g["ref"] for g in sc] == ["Alma 32:21"] and [t["id"] for t in sc[0]["talks"]] == ["2026-10/b"]


# ---------------------------------------------------------------- lesson plumbing with a study key

def _study(client, monkeypatch, body=BODY):
    monkeypatch.setattr(sty, "get_provider", lambda settings: FakeProvider())
    return client.post("/api/studies", json=body).json()


def test_my_lessons_lists_studies_with_talks(client, monkeypatch):
    login(client, "a@example.com")
    s = _study(client, monkeypatch)
    client.put("/api/my-lessons", json={"talk_id": "2026-10/a"})
    lessons = client.get("/api/my-lessons").json()
    assert [(m["kind"], m["lesson_id"]) for m in lessons] == [("study", s["key"]), ("talk", "2026-10/a")]
    st_ = lessons[0]
    assert st_["talk"] is None and st_["study"] == {"id": s["id"], "topic": "faith in hard times", "source_count": 3}
    assert st_["has_digest"] is True and st_["audience"] == "sacrament"
    assert lessons[1]["study"] is None and lessons[1]["talk"]["title"] == "Faith in Trials"
    # a study's audience is changed through the same endpoint a talk lesson uses
    r = client.put(f"/api/my-lessons/{s['key']}/audience", json={"audience": "personal"})
    assert r.json()["audience"] == "personal"
    assert client.get(f"/api/studies/{s['id']}").json()["audience"] == "personal"
    # removing a study from my lessons only takes it off the list
    after = client.delete(f"/api/my-lessons/{s['key']}").json()
    assert [m["lesson_id"] for m in after] == ["2026-10/a"]
    assert client.get(f"/api/studies/{s['id']}").status_code == 200


def test_remove_keeps_study_notes_and_pins_then_add_back_and_delete(client, monkeypatch):
    login(client, "a@example.com")
    s = _study(client, monkeypatch)
    key = s["key"]
    client.put(f"/api/lessons/{key}", json={"notes_md": "keep me"})
    client.post(f"/api/lessons/{key}/pins", json={"kind": "note", "text": "pinned"})
    listed = client.get("/api/studies").json()
    assert [(x["id"], x["in_my_lessons"], x["has_summary"], x["source_count"]) for x in listed] == [(s["id"], True, True, 3)]
    assert set(listed[0]) == {"id", "key", "topic", "audience", "audience_label", "source_count", "has_summary",
                              "in_my_lessons", "updated_at"}

    assert client.delete(f"/api/my-lessons/{key}").json() == []
    (row,) = client.get("/api/studies").json()
    assert row["in_my_lessons"] is False
    assert client.get(f"/api/studies/{s['id']}").json()["summary"] is not None
    kept = client.get(f"/api/lessons/{key}").json()
    assert kept["notes_md"] == "keep me" and kept["pins"][0]["text"] == "pinned"

    added = client.put("/api/my-lessons", json={"talk_id": key}).json()
    assert [m["lesson_id"] for m in added] == [key] and added[0]["audience"] == "sacrament"
    assert client.get("/api/studies").json()[0]["in_my_lessons"] is True

    client.delete(f"/api/my-lessons/{key}")
    login(client, "b@example.com")
    assert client.get("/api/studies").json() == []
    assert client.put("/api/my-lessons", json={"talk_id": key}).status_code == 404
    assert client.put("/api/my-lessons", json={"talk_id": "study:9999"}).status_code == 404
    assert client.delete(f"/api/studies/{s['id']}").status_code == 404
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "a@example.com", "password": "correct horse battery"})
    assert client.delete(f"/api/studies/{s['id']}").json() == {"ok": True}
    assert client.get("/api/studies").json() == []
    assert client.get(f"/api/lessons/{key}").json()["notes_md"] == ""


def test_notes_pins_export_with_a_study_key(client, monkeypatch):
    login(client, "a@example.com")
    s = _study(client, monkeypatch)
    key = s["key"]
    assert client.put(f"/api/lessons/{key}", json={"notes_md": "My **study** notes"}).json()["notes_md"]
    pins = client.post(f"/api/lessons/{key}/pins", json={"kind": "note", "text": "Where do you act?", "note": "ponder"}).json()
    assert pins[0]["text"] == "Where do you act?"
    assert client.post(f"/api/lessons/{key}/pins", json={"kind": "scripture", "scripture_ref": "Alma 32:21"}).status_code == 200
    html = client.get(f"/api/lessons/{key}/export.html").text
    assert "faith in hard times" in html and "Faith leads to action." in html and "Faith and works" in html
    assert "Prompts for your talk" in html and "Where do you act?" in html and "My <strong>study</strong> notes" in html
    assert "Alma 32:21" in html
    only = client.get(f"/api/lessons/{key}/export.html?sections=notes").text
    assert "Faith leads to action." not in only and "My <strong>study</strong> notes" in only


def test_other_users_cannot_use_a_study_key(client, monkeypatch):
    login(client, "a@example.com")
    key = _study(client, monkeypatch)["key"]
    login(client, "b@example.com")
    assert client.put(f"/api/lessons/{key}", json={"notes_md": "x"}).status_code == 404
    assert client.post(f"/api/lessons/{key}/pins", json={"kind": "note", "text": "x"}).status_code == 404
    assert client.get(f"/api/lessons/{key}/export.html").status_code == 404
    assert client.post(f"/api/lessons/{key}/email", json={"to": ["x@example.com"]}).status_code == 404
    assert client.put(f"/api/my-lessons/{key}/audience", json={"audience": "adults"}).status_code == 404
    assert client.post("/api/lessons/study:9999/pins", json={"kind": "note", "text": "x"}).status_code == 404
    import server.routers.chat as chat_router
    monkeypatch.setattr(chat_router, "get_provider", lambda settings: FakeProvider())
    assert client.post("/api/chat", json={"talk_id": key, "message": "hi"}).status_code == 404


def test_export_of_a_talk_uses_the_lesson_audience(client):
    login(client, "a@example.com")
    client.put("/api/my-lessons", json={"talk_id": "2026-10/a", "audience": "sacrament"})
    conn = client.app.state.conn
    conn.execute("INSERT INTO digests(talk_id, audience, provider, model, json) VALUES('2026-10/a','sacrament','f','f',?)",
                 (json.dumps({"essence": "Sacrament essence", "main_points": [], "key_quotes": [],
                              "questions": [{"question": "Q?", "kind": "opening", "note": "n"}]}),))
    conn.commit()
    html = client.get("/api/lessons/2026-10/a/export.html").text
    assert "Sacrament essence" in html and "Prompts for your talk" in html


def test_chat_on_a_study(client, monkeypatch):
    import server.routers.chat as chat_router
    from server.ai.base import ChatEvent
    seen = {}

    class ChatFake(Provider):
        name = "fake"
        model = "fake-1"

        def stream(self, system, history, user_message, tools, execute):
            seen["system"] = system
            yield ChatEvent("text_delta", {"text": "Hello"})

    login(client, "a@example.com")
    s = _study(client, monkeypatch)
    monkeypatch.setattr(chat_router, "get_provider", lambda settings: ChatFake())
    r = client.post("/api/chat", json={"talk_id": s["key"], "message": "What next?"})
    assert r.status_code == 200 and "event: done" in r.text
    sysmsg = seen["system"]
    assert "Topic: faith in hard times" in sysmsg and "The user's instructions for the summary: Short." in sysmsg
    assert "S1. talk: Faith in Trials [[talk:2026-10/a]]" in sysmsg and "[[manual:/manual/gt/faith]]" in sysmsg
    assert "Overview: Faith leads to action." in sysmsg and "sacrament meeting talk" in sysmsg
    assert "assigned" not in sysmsg and "get_manual_page" in sysmsg
    sess = client.get(f"/api/chat/sessions?talk_id={s['key']}").json()
    assert len(sess) == 1


def test_refine_accepts_a_full_audience_key(client, monkeypatch):
    import server.routers.suggest as sug

    class Refine(Provider):
        name = "fake"
        model = "fake-1"

        def generate_json(self, system, user_message, schema):
            self.msg = user_message
            return {"picks": [{"talk_id": "2026-10/a", "reason": "Fits."}]}

    p = Refine()
    monkeypatch.setattr(sug, "get_provider", lambda settings: p)
    login(client, "a@example.com")
    ok = client.post("/api/suggest/refine", json={"topic": "faith", "audience": "sacrament", "talk_ids": ["2026-10/a"]})
    assert ok.status_code == 200 and ok.json()["audience"] == "sacrament" and "sacrament meeting" in p.msg
    old = client.post("/api/suggest/refine", json={"topic": "faith", "audience": "youth", "gender": "female", "talk_ids": ["2026-10/a"]})
    assert old.json()["audience"] == "youth-female"
    bad = client.post("/api/suggest/refine", json={"topic": "faith", "audience": "bogus", "talk_ids": ["2026-10/a"]})
    assert bad.status_code == 422
