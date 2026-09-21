"""Regression tests for the 2026-09-21 security remediation.

Reuses the ``client``/``app_env`` fixture pattern from ``tests/test_auth.py``.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

from server.config import WEB_DIST


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    from server import db as dbm
    monkeypatch.setattr(dbm, "DB_PATH", tmp_path / "app.db")
    import server.main as main
    return main


@pytest.fixture
def client(app_env):
    from fastapi.testclient import TestClient
    with TestClient(app_env.app) as c:
        conn = c.app.state.conn
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


# ---------------------------------------------------------------- F-09 / F-10 / F-11

def test_forgot_does_not_cancel_a_pending_invite(client, monkeypatch):
    import server.routers.auth as auth_router
    monkeypatch.setattr(auth_router, "send_html", lambda *a, **k: {"provider": "stub"})
    make_user(client, "admin-f09@example.com", admin=True)
    login(client, "admin-f09@example.com")
    from server.settings import set_settings
    set_settings(client.app.state.conn, {
        "email_from": "a@b.com", "email_provider": "postmark", "postmark_server_token": "tok"})
    r = client.post("/api/users", json={"email": "invitee@example.com", "name": "Invitee"})
    original_token = r.json()["link"].split("token=")[1]
    client.post("/api/auth/logout")

    # An invited-but-not-yet-set-up user has no password; "forgot" for them
    # must not replace (and thereby invalidate) the pending invite — with email
    # configured (email_ready True) the old code would call issue_invite here.
    r = client.post("/api/auth/forgot", json={"email": "invitee@example.com"})
    assert r.status_code == 200

    ok = client.post("/api/auth/set-password",
                     json={"token": original_token, "password": "a long enough password"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["email"] == "invitee@example.com"


def test_failed_login_logs_event_without_the_email(client, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="lp.security"):
        r = client.post("/api/auth/login", json={"email": "someone@example.com", "password": "wrong password!"})
    assert r.status_code == 401
    records = [rec.getMessage() for rec in caplog.records if rec.name == "lp.security"]
    assert any(m.startswith("login.fail") for m in records)
    assert not any("someone@example.com" in m for m in records)


def test_login_runs_verify_password_even_for_unknown_email(client, monkeypatch):
    import server.routers.auth as auth_router
    calls = []
    real_verify = auth_router.verify_password

    def spy(password, password_hash):
        calls.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(auth_router, "verify_password", spy)
    r = client.post("/api/auth/login", json={"email": "nobody-at-all@example.com", "password": "whatever12"})
    assert r.status_code == 401
    assert len(calls) == 1
    assert calls[0] is not None  # the dummy hash, not None short-circuited


# ---------------------------------------------------------------- F-01

def _is_index_html(body: bytes) -> bool:
    return b"<div id=\"app\">" in body or b"<div id='app'>" in body


def _raw_get(app, path: str) -> tuple[int, bytes]:
    """Send a GET with a literal, unnormalised ``path`` straight through the ASGI
    app, bypassing httpx/TestClient's client-side URL normalisation of ``..``
    segments (uvicorn itself does not normalise dot segments, so this mirrors
    what a real request delivers as ``scope["path"]``)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
        "scheme": "http",
    }
    result: dict = {}
    body_chunks: list[bytes] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            result["status"] = message["status"]
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b""))

    asyncio.run(app(scope, receive, send))
    return result["status"], b"".join(body_chunks)


@pytest.mark.skipif(not WEB_DIST.exists(), reason="requires web/dist (npm run build)")
def test_path_traversal_dotdot_returns_index(client):
    status, body = _raw_get(client.app, "/../../requirements.txt")
    assert status == 200
    assert _is_index_html(body)
    assert b"fastapi" not in body.lower()


@pytest.mark.skipif(not WEB_DIST.exists(), reason="requires web/dist (npm run build)")
def test_path_traversal_encoded_dotdot_returns_index(client):
    # httpx/TestClient keeps a percent-encoded "%2f" as-is (it does not decode
    # it into "/" before sending), so this one reaches the app through the
    # ordinary client and still exercises the vulnerable decoded path.
    r = client.get("/..%2f..%2frequirements.txt")
    assert r.status_code == 200
    assert _is_index_html(r.content)
    assert b"fastapi" not in r.content.lower()


@pytest.mark.skipif(not WEB_DIST.exists(), reason="requires web/dist (npm run build)")
def test_path_traversal_via_assets_prefix_not_served(client):
    # The /assets StaticFiles mount already has its own containment check
    # (verified in the review); this just guards against a regression there.
    status, body = _raw_get(client.app, "/assets/../../requirements.txt")
    assert b"fastapi" not in body.lower()
    if status == 200:
        assert _is_index_html(body)
    else:
        assert status == 404


# ---------------------------------------------------------------- F-02

def test_secret_round_trip(monkeypatch, tmp_path):
    from server import secrets_store
    monkeypatch.delenv("LP_SECRET_KEY", raising=False)
    monkeypatch.setattr(secrets_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(secrets_store, "_fernet", None)
    token = secrets_store.encrypt("sk-ant-super-secret")
    assert token.startswith("enc:")
    assert secrets_store.decrypt(token) == "sk-ant-super-secret"
    key_path = tmp_path / "secret.key"
    assert key_path.exists()
    assert (key_path.stat().st_mode & 0o777) == 0o600


def test_secret_empty_round_trip():
    from server import secrets_store
    assert secrets_store.encrypt("") == ""
    assert secrets_store.decrypt("") == ""


def test_legacy_plaintext_is_readable_and_gets_migrated(client):
    from server.settings import get_settings, migrate_plaintext_secrets
    conn = client.app.state.conn
    conn.execute("INSERT INTO settings(key, value) VALUES('anthropic_api_key', 'sk-ant-plaintext')")
    conn.commit()
    assert get_settings(conn)["anthropic_api_key"] == "sk-ant-plaintext"
    changed = migrate_plaintext_secrets(conn)
    assert changed == 1
    row = conn.execute("SELECT value FROM settings WHERE key='anthropic_api_key'").fetchone()
    assert row["value"].startswith("enc:")
    assert get_settings(conn)["anthropic_api_key"] == "sk-ant-plaintext"
    assert migrate_plaintext_secrets(conn) == 0  # idempotent


def test_public_settings_never_leaks_secret(client):
    from server.settings import set_settings, public_settings, mask
    conn = client.app.state.conn
    set_settings(conn, {"anthropic_api_key": "sk-ant-abcd1234wxyz"})
    out = public_settings(conn)
    assert out["anthropic_api_key"] == "••••••••"
    assert out["anthropic_api_key_set"] is True
    assert "wxyz" not in out["anthropic_api_key"]
    assert mask("sk-ant-abcd1234wxyz") == "••••••••"
    assert mask("") == ""


def test_set_settings_encrypts_at_rest(client):
    from server.settings import set_settings
    conn = client.app.state.conn
    set_settings(conn, {"anthropic_api_key": "sk-ant-abcd1234wxyz"})
    row = conn.execute("SELECT value FROM settings WHERE key='anthropic_api_key'").fetchone()
    assert row["value"].startswith("enc:")
    assert "sk-ant-abcd1234wxyz" not in row["value"]


# ---------------------------------------------------------------- F-06

@pytest.fixture
def reload_config(monkeypatch):
    import server.config as config

    def _reload():
        importlib.reload(config)
        return config

    yield _reload
    # Leave later tests a clean, valid environment.
    monkeypatch.delenv("LP_BASE_URL", raising=False)
    monkeypatch.delenv("LP_TRUST_PROXY", raising=False)
    monkeypatch.delenv("LP_COOKIE_SECURE", raising=False)
    importlib.reload(config)


def test_trust_proxy_without_base_url_fails_closed(monkeypatch, reload_config):
    monkeypatch.delenv("LP_BASE_URL", raising=False)
    monkeypatch.setenv("LP_TRUST_PROXY", "1")
    with pytest.raises(RuntimeError, match="LP_BASE_URL"):
        reload_config()


def test_cookie_secure_without_base_url_fails_closed(monkeypatch, reload_config):
    monkeypatch.delenv("LP_BASE_URL", raising=False)
    monkeypatch.delenv("LP_TRUST_PROXY", raising=False)
    monkeypatch.setenv("LP_COOKIE_SECURE", "1")
    with pytest.raises(RuntimeError, match="LP_BASE_URL"):
        reload_config()


def test_base_url_with_path_is_rejected(monkeypatch, reload_config):
    monkeypatch.setenv("LP_BASE_URL", "https://x.example/sub")
    with pytest.raises(RuntimeError):
        reload_config()


def test_cookie_secure_true_for_https_base_url(monkeypatch, reload_config):
    monkeypatch.setenv("LP_BASE_URL", "https://x.example")
    monkeypatch.delenv("LP_TRUST_PROXY", raising=False)
    monkeypatch.delenv("LP_COOKIE_SECURE", raising=False)
    config = reload_config()
    assert config.COOKIE_SECURE is True
    assert config.BASE_URL == "https://x.example"


# ---------------------------------------------------------------- F-05 / F-15

def test_leftmost_spoofed_xff_does_not_bypass_ip_limit(client, monkeypatch):
    import server.auth as auth_mod
    monkeypatch.setattr(auth_mod, "TRUST_PROXY", True)
    # rightmost hop ("9.9.9.9") is the one the trusted proxy appended and stays
    # constant; the leftmost (client-supplied) hop changes on every request.
    for i in range(10):
        r = client.post(
            "/api/auth/login",
            json={"email": f"nouser-xff-{i}@example.com", "password": "wrong password!"},
            headers={"X-Forwarded-For": f"1.2.3.{i}, 9.9.9.9"},
        )
        assert r.status_code == 401
    r = client.post(
        "/api/auth/login",
        json={"email": "nouser-xff-10@example.com", "password": "wrong password!"},
        headers={"X-Forwarded-For": "1.2.3.99, 9.9.9.9"},
    )
    assert r.status_code == 429


def test_per_account_login_bucket_independent_of_source_ip(client, monkeypatch):
    import server.auth as auth_mod
    monkeypatch.setattr(auth_mod, "TRUST_PROXY", True)
    make_user(client, "victim-acct@example.com")
    for i in range(5):
        r = client.post(
            "/api/auth/login",
            json={"email": "victim-acct@example.com", "password": "wrong password!"},
            headers={"X-Real-IP": f"10.0.0.{i}"},
        )
        assert r.status_code == 401
    r = client.post(
        "/api/auth/login",
        json={"email": "victim-acct@example.com", "password": "wrong password!"},
        headers={"X-Real-IP": "10.0.0.250"},
    )
    assert r.status_code == 429


def test_health_carries_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert r.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in r.headers
    assert "strict-transport-security" not in r.headers  # COOKIE_SECURE is false in tests


def test_export_html_carries_stricter_csp(client):
    make_user(client, "export-csp@example.com")
    login(client, "export-csp@example.com")
    r = client.get("/api/lessons/2026-04/a/export.html")
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:"


# ---------------------------------------------------------------- F-03

def test_export_html_sanitises_notes(client):
    make_user(client, "sanitise@example.com")
    login(client, "sanitise@example.com")
    malicious = (
        "<img src=x onerror=alert(1)>\n\n"
        "<script>alert(1)</script>\n\n"
        "[x](javascript:alert(1))"
    )
    client.put("/api/lessons/2026-04/a", json={"notes_md": malicious})
    r = client.get("/api/lessons/2026-04/a/export.html")
    assert r.status_code == 200
    body = r.text
    assert "onerror" not in body
    assert "<script" not in body.lower()
    assert "javascript:" not in body.lower()


def test_eleventh_email_in_an_hour_is_throttled(client, monkeypatch):
    import server.routers.lessons as lessons_mod
    monkeypatch.setattr(lessons_mod, "send_html", lambda *a, **k: {"provider": "stub"})
    make_user(client, "emailer@example.com")
    login(client, "emailer@example.com")
    conn = client.app.state.conn
    from server.settings import set_settings
    set_settings(conn, {"email_from": "a@b.com", "email_provider": "postmark", "postmark_server_token": "tok"})
    for _ in range(10):
        r = client.post("/api/lessons/2026-04/a/email", json={"to": ["someone@example.com"]})
        assert r.status_code == 200, r.text
    r = client.post("/api/lessons/2026-04/a/email", json={"to": ["someone@example.com"]})
    assert r.status_code == 429


def test_rate_limit_recreates_bucket_after_full_expiry(monkeypatch):
    """A bucket that prunes down to empty is deleted and rebuilt fresh, rather
    than the same deque object (and dict entry) being kept forever."""
    import server.auth as auth_mod
    t = {"now": 0.0}
    monkeypatch.setattr(auth_mod.time, "monotonic", lambda: t["now"])
    key = "test:prune:identity"
    auth_mod._buckets.pop(key, None)
    auth_mod.rate_limit(key, limit=5, window_s=10)
    old_deque = auth_mod._buckets[key]
    t["now"] = 100.0  # window fully elapsed
    auth_mod.rate_limit(key, limit=5, window_s=10)
    new_deque = auth_mod._buckets[key]
    assert new_deque is not old_deque
    assert len(new_deque) == 1


def test_successful_logins_do_not_lock_the_account(client):
    """The per-account bucket counts attempts; a correct password resets it so a user
    signing in from several devices is not locked out by their own successes."""
    make_user(client, "multi@example.com")
    for _ in range(7):
        r = client.post("/api/auth/login", json={"email": "multi@example.com", "password": "correct horse battery"})
        assert r.status_code == 200, r.text
