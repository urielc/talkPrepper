"""User settings stored in the SQLite ``settings`` table."""

from __future__ import annotations

import sqlite3

from .config import SETTINGS_DEFAULTS, SECRET_SETTINGS
from . import secrets_store


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    out = dict(SETTINGS_DEFAULTS)
    for r in conn.execute("SELECT key, value FROM settings"):
        if r["key"] in out:
            out[r["key"]] = r["value"]
    for k in SECRET_SETTINGS:
        if out.get(k):
            out[k] = secrets_store.decrypt(out[k])
    return out


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        value = SETTINGS_DEFAULTS.get(key, "")
    else:
        value = row["value"]
    if key in SECRET_SETTINGS and value:
        value = secrets_store.decrypt(value)
    return value


def set_settings(conn: sqlite3.Connection, values: dict[str, str]) -> dict[str, str]:
    for k, v in values.items():
        if k not in SETTINGS_DEFAULTS:
            continue
        if v is None:
            continue
        v = str(v)
        if k in SECRET_SETTINGS and v:
            v = secrets_store.encrypt(v)
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, v),
        )
    conn.commit()
    return get_settings(conn)


def migrate_plaintext_secrets(conn: sqlite3.Connection) -> int:
    """Re-encrypt any legacy plaintext secret rows in place. Returns the count changed."""
    changed = 0
    for key in SECRET_SETTINGS:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None or not row["value"] or row["value"].startswith(secrets_store.PREFIX):
            continue
        conn.execute("UPDATE settings SET value=? WHERE key=?",
                     (secrets_store.encrypt(row["value"]), key))
        changed += 1
    if changed:
        conn.commit()
    return changed


def mask(value: str) -> str:
    if not value:
        return ""
    return "••••••••"


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
