"""User settings stored in the SQLite ``settings`` table."""

from __future__ import annotations

import sqlite3

from .config import SETTINGS_DEFAULTS, SECRET_SETTINGS


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    out = dict(SETTINGS_DEFAULTS)
    for r in conn.execute("SELECT key, value FROM settings"):
        if r["key"] in out:
            out[r["key"]] = r["value"]
    return out


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return SETTINGS_DEFAULTS.get(key, "")
    return row["value"]


def set_settings(conn: sqlite3.Connection, values: dict[str, str]) -> dict[str, str]:
    for k, v in values.items():
        if k not in SETTINGS_DEFAULTS:
            continue
        if v is None:
            continue
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, str(v)),
        )
    conn.commit()
    return get_settings(conn)


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return "•" * 8 + value[-4:]


def public_settings(conn: sqlite3.Connection) -> dict:
    s = get_settings(conn)
    out: dict = {}
    for k, v in s.items():
        if k in SECRET_SETTINGS:
            out[k] = mask(v)
            out[k + "_set"] = bool(v)
        else:
            out[k] = v
    return out
