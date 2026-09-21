"""Accounts, sessions and invite tokens.

Passwords are hashed with argon2id. A login creates a server-side session row;
the browser holds only a random token in an HttpOnly cookie, and the row stores
the token's SHA-256. Invite and password-reset links carry a one-time token,
also stored hashed.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import HTTPException, Request, Response

from .config import COOKIE_NAME, COOKIE_SECURE, SESSION_DAYS, INVITE_HOURS, TRUST_PROXY

_hasher = PasswordHasher()
MIN_PASSWORD_LEN = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


# A fixed hash to verify against when there is no real user/password: keeps the
# argon2 verification cost the same whether or not the email is registered, so
# the response time does not leak which addresses have accounts.
_DUMMY_HASH = hash_password("dummy-timing-pad")


# ---------------------------------------------------------------- users

def user_to_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "email": r["email"], "name": r["name"], "is_admin": bool(r["is_admin"]),
            "disabled": bool(r["disabled"]), "has_password": bool(r["password_hash"]),
            "created_at": r["created_at"], "last_login_at": r["last_login_at"]}


def get_user_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE lower(email)=lower(?)", (email.strip(),)).fetchone()


def create_user(conn: sqlite3.Connection, email: str, name: str = "", is_admin: bool = False,
                password: str | None = None) -> sqlite3.Row:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "A valid email address is required.")
    if get_user_by_email(conn, email):
        raise HTTPException(409, "A user with that email already exists.")
    pw = hash_password(password) if password else None
    cur = conn.execute(
        "INSERT INTO users(email, name, password_hash, is_admin) VALUES(?,?,?,?)",
        (email, name.strip(), pw, int(is_admin)))
    uid = cur.lastrowid
    # The first user ever created adopts any data that predates accounts.
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1:
        claim_orphaned_data(conn, uid)
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


_CLAIM_SQL = (
    "UPDATE lessons SET user_id=? WHERE user_id IS NULL",
    "UPDATE pins SET user_id=? WHERE user_id IS NULL",
    "UPDATE chat_sessions SET user_id=? WHERE user_id IS NULL",
    "UPDATE working_on SET user_id=? WHERE user_id IS NULL",
)


def claim_orphaned_data(conn: sqlite3.Connection, user_id: int) -> None:
    """Rows written before accounts existed belong to the first user."""
    for sql in _CLAIM_SQL:
        conn.execute(sql, (user_id,))


# ---------------------------------------------------------------- sessions

def create_session(conn: sqlite3.Connection, response: Response, user_id: int, user_agent: str = "") -> None:
    token = secrets.token_urlsafe(32)
    expires = _now() + timedelta(days=SESSION_DAYS)
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at, user_agent) VALUES(?,?,?,?)",
                 (_hash_token(token), user_id, _iso(expires), user_agent[:200]))
    conn.execute("UPDATE users SET last_login_at=datetime('now') WHERE id=?", (user_id,))
    conn.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=COOKIE_SECURE, samesite="lax", path="/")


def destroy_session(conn: sqlite3.Connection, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))
        conn.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


def user_from_request(conn: sqlite3.Connection, request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    th = _hash_token(token)
    row = conn.execute(
        "SELECT u.*, s.expires_at AS session_expires FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=?", (th,)).fetchone()
    if not row:
        return None
    if row["session_expires"] < _iso(_now()) or row["disabled"]:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
        conn.commit()
        return None
    # Sliding expiry: extend when less than half the lifetime remains.
    if row["session_expires"] < _iso(_now() + timedelta(days=SESSION_DAYS / 2)):
        conn.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?",
                     (_iso(_now() + timedelta(days=SESSION_DAYS)), th))
        conn.commit()
    return row


# ---------------------------------------------------------------- invites / resets

def issue_invite(conn: sqlite3.Connection, user_id: int, hours: int = INVITE_HOURS) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM invites WHERE user_id=? AND used_at IS NULL", (user_id,))
    conn.execute("INSERT INTO invites(token_hash, user_id, expires_at) VALUES(?,?,?)",
                 (_hash_token(token), user_id, _iso(_now() + timedelta(hours=hours))))
    conn.commit()
    return token


def consume_invite(conn: sqlite3.Connection, token: str) -> sqlite3.Row:
    th = _hash_token(token)
    inv = conn.execute("SELECT * FROM invites WHERE token_hash=?", (th,)).fetchone()
    if not inv or inv["used_at"] or inv["expires_at"] < _iso(_now()):
        raise HTTPException(400, "This link is invalid or has expired. Ask for a new one.")
    conn.execute("UPDATE invites SET used_at=datetime('now') WHERE token_hash=?", (th,))
    return conn.execute("SELECT * FROM users WHERE id=?", (inv["user_id"],)).fetchone()


# ---------------------------------------------------------------- rate limiting

_buckets: dict[str, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    """The address to rate-limit on.

    Only trusted when LP_TRUST_PROXY is set (nginx or similar sits in front and
    sets these itself). Prefers X-Real-IP; otherwise the *rightmost* hop of
    X-Forwarded-For, which is the one the proxy appended and the client cannot
    forge (nginx's usual ``$proxy_add_x_forwarded_for`` appends to whatever the
    client sent, so trusting the leftmost entry lets an attacker supply a fresh
    one per request and dodge the limiter entirely).
    """
    if TRUST_PROXY:
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            parts = [p.strip() for p in fwd.split(",") if p.strip()]
            if parts:
                return parts[-1]
    return request.client.host if request.client else "?"


def rate_limit(key: str, limit: int, window_s: int) -> None:
    """Allow ``limit`` hits per ``window_s`` seconds for ``key``; 429 otherwise."""
    now = time.monotonic()
    q = _buckets[key]
    while q and q[0] < now - window_s:
        q.popleft()
    if not q:
        # Don't let an emptied-out bucket sit in the dict forever.
        del _buckets[key]
        q = _buckets[key]
    if len(q) >= limit:
        from .log import event
        # Log the key's prefix (which endpoint/bucket) and a hash of the whole
        # key, never the key itself — a per-account key embeds the plaintext
        # email address.
        event("ratelimit.hit", level=logging.WARNING, key_prefix=key.split(":", 1)[0],
              key_hash=_hash_token(key)[:12])
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    q.append(now)
