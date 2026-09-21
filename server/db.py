"""SQLite access and schema.

Two groups of tables live in one database file:

* Index tables (conferences, talks, paragraphs, refs, chunks, scriptures and
  their FTS mirrors) are rebuilt from scratch by the indexer.
* User tables (users, sessions, invites, working_on, settings, lessons, pins,
  digests, chat_*) are created once and never dropped by the indexer.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import DB_PATH, DATA_DIR

INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS conferences (
    id      TEXT PRIMARY KEY,          -- '2026-04'
    year    INTEGER NOT NULL,
    month   INTEGER NOT NULL,
    label   TEXT NOT NULL,             -- 'April 2026'
    url     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS talks (
    id            TEXT PRIMARY KEY,    -- '2026-04/46renlund'
    conference_id TEXT NOT NULL REFERENCES conferences(id),
    speaker       TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL DEFAULT '',
    url           TEXT NOT NULL,
    word_count    INTEGER NOT NULL DEFAULT 0,
    ord           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS talks_conf ON talks(conference_id, ord);

CREATE TABLE IF NOT EXISTS paragraphs (
    id        INTEGER PRIMARY KEY,
    talk_id   TEXT NOT NULL REFERENCES talks(id),
    idx       INTEGER NOT NULL,
    text      TEXT NOT NULL,
    is_note   INTEGER NOT NULL DEFAULT 0,
    marker    INTEGER,                 -- endnote number when is_note, else NULL
    note_refs TEXT                     -- JSON [{"n": 13, "pos": 185}, ...] for body paragraphs
);
CREATE INDEX IF NOT EXISTS paragraphs_talk ON paragraphs(talk_id, idx);

CREATE VIRTUAL TABLE IF NOT EXISTS paragraphs_fts USING fts5(
    text, talk_id UNINDEXED,
    content='paragraphs', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE IF NOT EXISTS talks_fts USING fts5(
    id UNINDEXED, title, speaker,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS scripture_refs (
    id           INTEGER PRIMARY KEY,
    talk_id      TEXT NOT NULL REFERENCES talks(id),
    paragraph_id INTEGER NOT NULL REFERENCES paragraphs(id),
    book         TEXT NOT NULL,        -- canonical book title, e.g. 'Alma'
    chapter      INTEGER NOT NULL,
    verse_start  INTEGER,              -- NULL for chapter-only refs
    verse_end    INTEGER,
    raw          TEXT NOT NULL,
    char_start   INTEGER NOT NULL,
    char_end     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sref_book ON scripture_refs(book, chapter);
CREATE INDEX IF NOT EXISTS sref_talk ON scripture_refs(talk_id);

CREATE TABLE IF NOT EXISTS talk_refs (
    id            INTEGER PRIMARY KEY,
    talk_id       TEXT NOT NULL REFERENCES talks(id),
    paragraph_id  INTEGER NOT NULL REFERENCES paragraphs(id),
    cited_talk_id TEXT,                -- resolved talks.id or NULL
    raw_title     TEXT,
    raw_year      INTEGER,
    raw_month     INTEGER,
    raw           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tref_talk ON talk_refs(talk_id);
CREATE INDEX IF NOT EXISTS tref_cited ON talk_refs(cited_talk_id);

CREATE TABLE IF NOT EXISTS chunks (
    id         INTEGER PRIMARY KEY,    -- row index into chunks.npy
    talk_id    TEXT NOT NULL REFERENCES talks(id),
    para_start INTEGER NOT NULL,
    para_end   INTEGER NOT NULL,
    text       TEXT NOT NULL,
    text_hash  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_talk ON chunks(talk_id);

CREATE TABLE IF NOT EXISTS scriptures (
    id         INTEGER PRIMARY KEY,
    volume     TEXT NOT NULL,
    book       TEXT NOT NULL,
    book_short TEXT NOT NULL,
    chapter    INTEGER NOT NULL,
    verse      INTEGER NOT NULL,
    text       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS scriptures_ref ON scriptures(book, chapter, verse);
CREATE VIRTUAL TABLE IF NOT EXISTS scriptures_fts USING fts5(
    text, content='scriptures', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS index_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

INDEX_TABLES = [
    "paragraphs_fts", "talks_fts", "scriptures_fts",
    "scripture_refs", "talk_refs", "chunks", "paragraphs", "talks",
    "conferences", "scriptures", "index_meta",
]

USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL DEFAULT '',
    password_hash TEXT,                       -- NULL until the invite is accepted
    is_admin      INTEGER NOT NULL DEFAULT 0,
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    user_agent TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS invites (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    used_at    TEXT
);

CREATE TABLE IF NOT EXISTS working_on (
    user_id  INTEGER,                        -- NULL only for rows migrated before accounts existed
    talk_id  TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    ord      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, talk_id)
);

CREATE TABLE IF NOT EXISTS lessons (
    user_id    INTEGER,
    talk_id    TEXT NOT NULL,
    notes_md   TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, talk_id)
);

CREATE TABLE IF NOT EXISTS pins (
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER,
    talk_id          TEXT NOT NULL,           -- the lesson this pin belongs to
    kind             TEXT NOT NULL,           -- 'talk' | 'scripture' | 'quote'
    ref_talk_id      TEXT,
    ref_paragraph_id INTEGER,
    scripture_ref    TEXT,
    text             TEXT NOT NULL DEFAULT '',
    note             TEXT NOT NULL DEFAULT '',
    ord              INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS pins_lesson ON pins(talk_id, ord);

CREATE TABLE IF NOT EXISTS digests (
    talk_id    TEXT PRIMARY KEY,
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL,
    json       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER,
    talk_id    TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    provider   TEXT NOT NULL DEFAULT '',
    model      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS chat_sessions_talk ON chat_sessions(talk_id, updated_at);

CREATE TABLE IF NOT EXISTS chat_messages (
    id           INTEGER PRIMARY KEY,
    session_id   INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role         TEXT NOT NULL,             -- 'user' | 'assistant'
    content_json TEXT NOT NULL,             -- list of blocks for the UI (text / tool_call / tool_result)
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS chat_messages_session ON chat_messages(session_id, id);
"""


def connect(path=None) -> sqlite3.Connection:
    """Open the app database (default: DB_PATH, resolved at call time so tests can redirect it)."""
    path = path or DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(USER_SCHEMA)
    conn.executescript(INDEX_SCHEMA)
    conn.commit()


def drop_index_tables(conn: sqlite3.Connection) -> None:
    for t in INDEX_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def index_ready(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='talks'"
    ).fetchone()
    if not row:
        return False
    return conn.execute("SELECT COUNT(*) FROM talks").fetchone()[0] > 0


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    try:
        row = conn.execute("SELECT value FROM index_meta WHERE key=?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return default
    return row[0] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO index_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
