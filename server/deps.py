"""FastAPI dependencies.

Each request gets its own SQLite connection (cheap, and safe with the
threadpool that runs sync endpoints and streaming responses). The search
engine is process-wide and owns a separate connection.
"""

from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Depends, HTTPException, Request

from . import db as dbm
from .search import SearchEngine


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = dbm.connect()
    try:
        yield conn
    finally:
        conn.close()


def get_engine(request: Request) -> SearchEngine:
    return request.app.state.engine


def get_user(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> sqlite3.Row:
    """The logged-in user, or 401."""
    from .auth import user_from_request
    user = user_from_request(conn, request)
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    return user


def get_admin(user: sqlite3.Row = Depends(get_user)) -> sqlite3.Row:
    if not user["is_admin"]:
        raise HTTPException(403, "Administrator access required.")
    return user
