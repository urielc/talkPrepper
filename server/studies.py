"""Topic studies: lessons built on a queue of sources (talks, manual pages, songs, scripture passages, Josephus).

A study is a lesson. Notes, pins, my-lessons and chat are keyed by a plain string, so a study uses the key
``study:<id>`` in those tables (no slash, so it never collides with a talk id like ``2026-04/46renlund``).
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import HTTPException

from .audience import CLASSES, DEFAULT_KEY, label as audience_label

PREFIX = "study:"
SOURCE_KINDS = ("talk", "manual", "song", "scripture", "josephus", "apocrypha")
MAX_SOURCES = 12


def study_key(study_id: int) -> str:
    return f"{PREFIX}{study_id}"


def study_id_of(key: str | None) -> int | None:
    """The study id in a lesson key, or None when the key names a talk (or is malformed)."""
    if key and key.startswith(PREFIX) and key[len(PREFIX):].isdigit():
        return int(key[len(PREFIX):])
    return None


def is_study_key(key: str | None) -> bool:
    return bool(key) and key.startswith(PREFIX)


def study_to_dict(r: sqlite3.Row) -> dict:
    aud = r["audience"] if r["audience"] in CLASSES else DEFAULT_KEY
    summary = None
    if r["summary_json"]:
        summary = {**json.loads(r["summary_json"]), "provider": r["provider"], "model": r["model"]}
    return {"id": r["id"], "key": study_key(r["id"]), "topic": r["topic"], "audience": aud,
            "audience_label": audience_label(aud), "modifier": r["modifier"],
            "sources": json.loads(r["sources_json"] or "[]"), "summary": summary,
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def get_study(conn: sqlite3.Connection, uid: int, study_id: int) -> dict | None:
    """The study, only if ``uid`` owns it."""
    r = conn.execute("SELECT * FROM studies WHERE id=? AND user_id=?", (study_id, uid)).fetchone()
    return study_to_dict(r) if r else None


def get_study_or_404(conn: sqlite3.Connection, uid: int, study_id: int) -> dict:
    s = get_study(conn, uid, study_id)
    if s is None:
        raise HTTPException(404, "study not found")
    return s


def require_subject(conn: sqlite3.Connection, uid: int, lesson_key: str) -> None:
    """404 unless the lesson key names a talk that exists or a study this user owns."""
    sid = study_id_of(lesson_key)
    if sid is not None:
        get_study_or_404(conn, uid, sid)
    elif is_study_key(lesson_key):
        raise HTTPException(404, "study not found")
    else:
        from .routers.talks import get_talk_or_404
        get_talk_or_404(conn, lesson_key)


def study_audience(conn: sqlite3.Connection, uid: int, lesson_key: str) -> str | None:
    """The audience of a study the user owns, or None when the key is not an owned study."""
    sid = study_id_of(lesson_key)
    if sid is None:
        return None
    r = conn.execute("SELECT audience FROM studies WHERE id=? AND user_id=?", (sid, uid)).fetchone()
    return (r["audience"] if r["audience"] in CLASSES else DEFAULT_KEY) if r else None


def delete_study(conn: sqlite3.Connection, uid: int, study_id: int) -> None:
    """Remove the study and everything keyed by its lesson key."""
    key = study_key(study_id)
    sessions = [r["id"] for r in conn.execute(
        "SELECT id FROM chat_sessions WHERE talk_id=? AND user_id=?", (key, uid))]
    for sid in sessions:
        conn.execute("DELETE FROM chat_messages WHERE session_id=?", (sid,))
    conn.execute("DELETE FROM chat_sessions WHERE talk_id=? AND user_id=?", (key, uid))
    for table in ("pins", "lessons", "working_on"):
        conn.execute(f"DELETE FROM {table} WHERE talk_id=? AND user_id=?", (key, uid))
    conn.execute("DELETE FROM studies WHERE id=? AND user_id=?", (study_id, uid))
    conn.commit()
