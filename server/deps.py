"""FastAPI dependencies.

Each request gets its own SQLite connection (cheap, and safe with the
threadpool that runs sync endpoints and streaming responses). The search
engine is process-wide and owns a separate connection.
"""

from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Request

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
