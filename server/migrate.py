"""Bring an existing database up to the multi-user schema.

Runs automatically at startup (structural part) and from ``python -m server.cli
migrate --admin-email …`` (creates the first admin, who adopts the pre-account
notes, pins, chats and current talk).
"""

from __future__ import annotations

import sqlite3

from . import db as dbm


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def apply_schema(conn: sqlite3.Connection) -> list[str]:
    """Idempotent structural migration. Returns the steps it performed."""
    done: list[str] = []
    dbm.ensure_schema(conn)

    # lessons: PK talk_id -> (user_id, talk_id)
    if _table_exists(conn, "lessons") and "user_id" not in _columns(conn, "lessons"):
        conn.executescript("""
            ALTER TABLE lessons RENAME TO lessons_old;
            CREATE TABLE lessons (
                user_id    INTEGER,
                talk_id    TEXT NOT NULL,
                notes_md   TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, talk_id)
            );
            INSERT INTO lessons(user_id, talk_id, notes_md, created_at, updated_at)
                SELECT NULL, talk_id, notes_md, created_at, updated_at FROM lessons_old;
            DROP TABLE lessons_old;
        """)
        done.append("lessons: added user_id, composite primary key")

    add_column = {
        "pins": "ALTER TABLE pins ADD COLUMN user_id INTEGER",
        "chat_sessions": "ALTER TABLE chat_sessions ADD COLUMN user_id INTEGER",
    }
    for table, sql in add_column.items():
        if _table_exists(conn, table) and "user_id" not in _columns(conn, table):
            conn.execute(sql)
            done.append(f"{table}: added user_id")

    if _table_exists(conn, "lessons") and "hidden_at" not in _columns(conn, "lessons"):
        conn.execute("ALTER TABLE lessons ADD COLUMN hidden_at TEXT")
        done.append("lessons: added hidden_at")

    # Index columns added after a build: present (empty) until the next re-index fills them,
    # so new code can run against an index built by older code.
    if _table_exists(conn, "talks"):
        cols = _columns(conn, "talks")
        if "calling" not in cols:
            conn.execute("ALTER TABLE talks ADD COLUMN calling TEXT NOT NULL DEFAULT ''")
            done.append("talks: added calling")
        if "audience_tags" not in cols:
            conn.execute("ALTER TABLE talks ADD COLUMN audience_tags TEXT NOT NULL DEFAULT ''")
            done.append("talks: added audience_tags")

    if _table_exists(conn, "working_on") and "audience" not in _columns(conn, "working_on"):
        conn.execute("ALTER TABLE working_on ADD COLUMN audience TEXT")
        done.append("working_on: added audience")

    # digests: PK talk_id -> (talk_id, audience). Existing digests were written for an elders quorum.
    if _table_exists(conn, "digests") and "audience" not in _columns(conn, "digests"):
        conn.executescript("""
            ALTER TABLE digests RENAME TO digests_old;
            CREATE TABLE digests (
                talk_id    TEXT NOT NULL,
                audience   TEXT NOT NULL DEFAULT 'adults-male',
                provider   TEXT NOT NULL,
                model      TEXT NOT NULL,
                json       TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (talk_id, audience)
            );
            INSERT INTO digests(talk_id, audience, provider, model, json, created_at)
                SELECT talk_id, 'adults-male', provider, model, json, created_at FROM digests_old;
            DROP TABLE digests_old;
        """)
        done.append("digests: keyed by talk and audience")

    # The single current talk becomes a working_on row (owner assigned when the first user is created).
    row = conn.execute("SELECT value FROM settings WHERE key='current_talk_id'").fetchone()
    if row:
        if row["value"]:
            conn.execute("INSERT OR IGNORE INTO working_on(user_id, talk_id) VALUES(NULL, ?)", (row["value"],))
        conn.execute("DELETE FROM settings WHERE key='current_talk_id'")
        done.append("current_talk_id moved to working_on")

    # Any user already present adopts orphaned rows.
    first = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if first:
        from .auth import claim_orphaned_data
        claim_orphaned_data(conn, first["id"])
    conn.commit()
    return done


def create_admin(conn: sqlite3.Connection, email: str, name: str = "", password: str | None = None):
    from .auth import create_user, issue_invite
    user = create_user(conn, email, name=name or email.split("@")[0], is_admin=True, password=password)
    token = None if password else issue_invite(conn, user["id"], hours=72)
    return user, token
