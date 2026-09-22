"""Accounts, sessions, per-user scoping and the schema migration.

Uses FastAPI's TestClient against a temporary data directory so the real
data/app.db is never touched.
"""

import sqlite3

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """Point the app at a throwaway database without reloading modules."""
    from server import db as dbm
    monkeypatch.setattr(dbm, "DB_PATH", tmp_path / "app.db")
    import server.main as main
    return main


@pytest.fixture
def client(app_env):
    from fastapi.testclient import TestClient
    with TestClient(app_env.app) as c:
        conn = c.app.state.conn
        # a tiny talk index so talk-scoped endpoints have something to point at
        conn.execute("INSERT INTO conferences VALUES('2026-04', 2026, 4, 'April 2026', 'u')")
        conn.execute("INSERT INTO talks VALUES('2026-04/a', '2026-04', 'Elder A', 'Talk A', 'http://a', 10, 0)")
        conn.execute("INSERT INTO paragraphs(talk_id, idx, text, is_note) VALUES('2026-04/a', 0, 'Body.', 0)")
        conn.commit()
        yield c


def make_user(client, email, password="correct horse battery", admin=False):
    from server.auth import create_user
    create_user(client.app.state.conn, email, is_admin=admin, password=password)


def login(client, email, password="correct horse battery"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def test_login_logout_and_me(client):
    make_user(client, "uri@example.com", admin=True)
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "uri@example.com", "password": "wrong password!"}).status_code == 401
    me = login(client, "uri@example.com")
    assert me["email"] == "uri@example.com" and me["is_admin"] is True
    assert client.get("/api/auth/me").json()["email"] == "uri@example.com"
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_protected_endpoints_require_login(client):
    for path in ("/api/conferences", "/api/talks/2026-04/a", "/api/lessons", "/api/my-lessons", "/api/settings"):
        assert client.get(path).status_code == 401, path
    assert client.get("/api/health").status_code == 200


def test_admin_only(client):
    make_user(client, "teacher@example.com")
    login(client, "teacher@example.com")
    assert client.get("/api/settings").status_code == 403
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/admin/index/status").status_code == 403
    assert client.get("/api/conferences").status_code == 200


def test_scoping_between_users(client):
    make_user(client, "a@example.com")
    make_user(client, "b@example.com")
    login(client, "a@example.com")
    client.put("/api/lessons/2026-04/a", json={"notes_md": "A's notes"})
    pins = client.post("/api/lessons/2026-04/a/pins", json={"kind": "note", "text": "A's pin"}).json()
    assert len(pins) == 1
    client.put("/api/my-lessons", json={"talk_id": "2026-04/a"})
    assert [m["talk"]["id"] for m in client.get("/api/my-lessons").json()] == ["2026-04/a"]
    client.post("/api/auth/logout")

    login(client, "b@example.com")
    l = client.get("/api/lessons/2026-04/a").json()
    assert l["notes_md"] == "" and l["pins"] == []
    assert client.get("/api/my-lessons").json() == []
    # B cannot touch A's pin even by id
    assert client.delete(f"/api/lessons/2026-04/a/pins/{pins[0]['id']}").status_code == 200
    client.post("/api/auth/logout")
    login(client, "a@example.com")
    assert len(client.get("/api/lessons/2026-04/a").json()["pins"]) == 1


def test_hide_from_other_talks_list(client):
    make_user(client, "a@example.com")
    make_user(client, "b@example.com")
    login(client, "b@example.com")
    client.put("/api/lessons/2026-04/a", json={"notes_md": "B's notes"})
    client.post("/api/auth/logout")

    login(client, "a@example.com")
    listed = lambda: [r["talk"]["id"] for r in client.get("/api/lessons").json()]
    # whitespace left behind after clearing notes does not count as notes
    client.put("/api/lessons/2026-04/a", json={"notes_md": "\n\n  "})
    assert listed() == []

    client.put("/api/lessons/2026-04/a", json={"notes_md": "kept"})
    assert listed() == ["2026-04/a"]
    assert client.post("/api/lessons/2026-04/a/hide").status_code == 200
    assert listed() == []
    assert client.get("/api/lessons/2026-04/a").json()["notes_md"] == "kept"  # nothing deleted
    client.put("/api/lessons/2026-04/a", json={"notes_md": "  "})
    assert listed() == []  # blank edits keep it hidden
    client.post("/api/lessons/2026-04/a/pins", json={"kind": "note", "text": "new"})
    assert listed() == ["2026-04/a"]  # new content brings it back
    client.post("/api/lessons/2026-04/a/hide")
    client.put("/api/lessons/2026-04/a", json={"notes_md": "more"})
    assert listed() == ["2026-04/a"]
    client.post("/api/auth/logout")

    login(client, "b@example.com")  # A's hide is A's alone
    assert [r["talk"]["id"] for r in client.get("/api/lessons").json()] == ["2026-04/a"]


def test_migration_adds_hidden_at(tmp_path):
    from server import db as dbm
    from server.migrate import apply_schema
    conn = dbm.connect(tmp_path / "old.db")
    conn.executescript("""
        CREATE TABLE lessons(user_id INTEGER, talk_id TEXT NOT NULL, notes_md TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, talk_id));
        INSERT INTO lessons(user_id, talk_id, notes_md) VALUES(1, '2026-04/a', 'x');
    """)
    assert "lessons: added hidden_at" in apply_schema(conn)
    assert conn.execute("SELECT hidden_at FROM lessons").fetchone()["hidden_at"] is None
    assert "lessons: added hidden_at" not in apply_schema(conn)


def test_invite_flow(client):
    make_user(client, "admin@example.com", admin=True)
    login(client, "admin@example.com")
    r = client.post("/api/users", json={"email": "new@example.com", "name": "New Teacher"})
    assert r.status_code == 200
    body = r.json()
    assert body["emailed"] is False and "set-password?token=" in body["link"]   # no mail configured in tests
    token = body["link"].split("token=")[1]
    client.post("/api/auth/logout")
    weak = client.post("/api/auth/set-password", json={"token": token, "password": "short"})
    assert weak.status_code == 400
    ok = client.post("/api/auth/set-password", json={"token": token, "password": "a long enough password"})
    assert ok.status_code == 200 and ok.json()["email"] == "new@example.com"
    assert client.get("/api/auth/me").status_code == 200
    # token is single use
    again = client.post("/api/auth/set-password", json={"token": token, "password": "another long password"})
    assert again.status_code == 400


def test_disabled_user_cannot_login(client):
    make_user(client, "admin@example.com", admin=True)
    make_user(client, "t@example.com")
    login(client, "admin@example.com")
    users = client.get("/api/users").json()
    tid = next(u["id"] for u in users if u["email"] == "t@example.com")
    client.patch(f"/api/users/{tid}", json={"disabled": True})
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "t@example.com", "password": "correct horse battery"}).status_code == 401


def test_migration_from_single_user_db(tmp_path):
    """An old-style database (no user_id anywhere, current_talk_id in settings) becomes the first user's data."""
    from server import db as dbm
    from server.migrate import apply_schema, create_admin
    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path)); conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE lessons(talk_id TEXT PRIMARY KEY, notes_md TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE pins(id INTEGER PRIMARY KEY, talk_id TEXT NOT NULL, kind TEXT NOT NULL, ref_talk_id TEXT,
            ref_paragraph_id INTEGER, scripture_ref TEXT, text TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
            ord INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE chat_sessions(id INTEGER PRIMARY KEY, talk_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO settings VALUES('current_talk_id', '2025-10/x');
        INSERT INTO lessons(talk_id, notes_md) VALUES('2025-10/x', 'old notes');
        INSERT INTO pins(talk_id, kind, text) VALUES('2025-10/x', 'note', 'old pin');
        INSERT INTO chat_sessions(talk_id, title) VALUES('2025-10/x', 'old chat');
    """)
    conn.commit()
    steps = apply_schema(conn)
    assert any("lessons" in s for s in steps) and any("current_talk_id" in s for s in steps)
    user, token = create_admin(conn, "uri@example.com", password="a long enough password")
    uid = user["id"]
    assert conn.execute("SELECT user_id, notes_md FROM lessons").fetchone()[:] == (uid, "old notes")
    assert conn.execute("SELECT user_id FROM pins").fetchone()[0] == uid
    assert conn.execute("SELECT user_id FROM chat_sessions").fetchone()[0] == uid
    assert conn.execute("SELECT user_id, talk_id FROM working_on").fetchone()[:] == (uid, "2025-10/x")
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE key='current_talk_id'").fetchone()[0] == 0
    assert token is None
    # running it again is a no-op
    assert apply_schema(conn) == []
