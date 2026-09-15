"""Per-lesson notes and pinned references, with HTML export and email."""

from __future__ import annotations

import html
import sqlite3
from typing import Literal

import markdown
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..deps import get_conn
from ..mailer import send_html, MailConfigError, email_ready, missing_email_setup
from ..scriptures import get_verses, format_ref
from ..settings import get_settings
from .scriptures import parse_single_ref
from .talks import fetch_talks, get_talk_or_404, talk_row_to_dict

router = APIRouter(tags=["lessons"])


class NotesBody(BaseModel):
    notes_md: str = Field("", max_length=200_000)


class PinBody(BaseModel):
    kind: Literal["talk", "scripture", "quote", "note"]
    ref_talk_id: str | None = None
    ref_paragraph_id: int | None = None
    scripture_ref: str | None = None
    text: str = Field("", max_length=20_000)
    note: str = Field("", max_length=5_000)


class PinPatch(BaseModel):
    text: str | None = Field(None, max_length=20_000)
    note: str | None = Field(None, max_length=5_000)


class ReorderBody(BaseModel):
    ids: list[int]


class EmailBody(BaseModel):
    to: list[str] = Field(min_length=1, max_length=20)
    subject: str | None = None


def ensure_lesson(conn: sqlite3.Connection, talk_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO lessons(talk_id) VALUES(?)", (talk_id,))


def pin_to_dict(r: sqlite3.Row, talks: dict[str, dict]) -> dict:
    d = dict(r)
    d["ref_talk"] = talks.get(r["ref_talk_id"]) if r["ref_talk_id"] else None
    return d


def load_pins(conn: sqlite3.Connection, talk_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM pins WHERE talk_id=? ORDER BY ord, id", (talk_id,)).fetchall()
    talks = fetch_talks(conn, [r["ref_talk_id"] for r in rows if r["ref_talk_id"]])
    return [pin_to_dict(r, talks) for r in rows]


@router.get("/lessons")
def list_lessons(conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT l.talk_id, l.updated_at, LENGTH(l.notes_md) AS notes_len, "
        "(SELECT COUNT(*) FROM pins p WHERE p.talk_id=l.talk_id) AS pin_count, "
        "(SELECT COUNT(*) FROM chat_sessions s WHERE s.talk_id=l.talk_id) AS chat_count "
        "FROM lessons l ORDER BY l.updated_at DESC LIMIT 50").fetchall()
    talks = fetch_talks(conn, [r["talk_id"] for r in rows])
    out = []
    for r in rows:
        if r["talk_id"] in talks and (r["notes_len"] or r["pin_count"] or r["chat_count"]):
            out.append({"talk": talks[r["talk_id"]], "updated_at": r["updated_at"],
                        "notes_len": r["notes_len"], "pin_count": r["pin_count"],
                        "chat_count": r["chat_count"]})
    return out


@router.get("/lessons/{talk_id:path}/export.html", response_class=HTMLResponse)
def export_html(talk_id: str, conn=Depends(get_conn)):
    return HTMLResponse(render_export(conn, talk_id))


@router.post("/lessons/{talk_id:path}/email")
def email_lesson(talk_id: str, body: EmailBody, conn=Depends(get_conn)):
    talk = talk_row_to_dict(get_talk_or_404(conn, talk_id))
    settings = get_settings(conn)
    if not email_ready(settings):
        raise HTTPException(400, "Email is not configured. " + missing_email_setup(settings))
    subject = body.subject or f"Lesson prep: {talk['title']} ({talk['speaker']})"
    try:
        info = send_html(settings, body.to, subject, render_export(conn, talk_id))
    except MailConfigError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # network / smtplib errors
        raise HTTPException(502, f"Sending failed: {e}")
    return {"ok": True, "to": body.to, "subject": subject, **info}


@router.post("/lessons/{talk_id:path}/pins/reorder")
def reorder_pins(talk_id: str, body: ReorderBody, conn=Depends(get_conn)):
    for i, pid in enumerate(body.ids):
        conn.execute("UPDATE pins SET ord=? WHERE id=? AND talk_id=?", (i, pid, talk_id))
    touch(conn, talk_id)
    return load_pins(conn, talk_id)


@router.patch("/lessons/{talk_id:path}/pins/{pin_id}")
def patch_pin(talk_id: str, pin_id: int, body: PinPatch, conn=Depends(get_conn)):
    row = conn.execute("SELECT id FROM pins WHERE id=? AND talk_id=?", (pin_id, talk_id)).fetchone()
    if not row:
        raise HTTPException(404, "pin not found")
    if body.text is not None:
        conn.execute("UPDATE pins SET text=? WHERE id=?", (body.text, pin_id))
    if body.note is not None:
        conn.execute("UPDATE pins SET note=? WHERE id=?", (body.note, pin_id))
    touch(conn, talk_id)
    return load_pins(conn, talk_id)


@router.delete("/lessons/{talk_id:path}/pins/{pin_id}")
def delete_pin(talk_id: str, pin_id: int, conn=Depends(get_conn)):
    conn.execute("DELETE FROM pins WHERE id=? AND talk_id=?", (pin_id, talk_id))
    touch(conn, talk_id)
    return load_pins(conn, talk_id)


@router.post("/lessons/{talk_id:path}/pins")
def add_pin(talk_id: str, body: PinBody, conn=Depends(get_conn)):
    get_talk_or_404(conn, talk_id)
    ensure_lesson(conn, talk_id)
    text = body.text
    if body.kind == "scripture":
        if not body.scripture_ref:
            raise HTTPException(400, "scripture_ref required")
        book, chapter, vs, ve = parse_single_ref(body.scripture_ref)
        body.scripture_ref = format_ref(book, chapter, vs, ve)
        if not text:
            verses = get_verses(conn, book, chapter, vs, ve)
            text = " ".join(f"{v.verse} {v.text}" for v in verses)
    elif body.kind in ("talk", "quote"):
        if not body.ref_talk_id:
            raise HTTPException(400, "ref_talk_id required")
        get_talk_or_404(conn, body.ref_talk_id)
        if body.kind == "quote" and not text and body.ref_paragraph_id:
            row = conn.execute("SELECT text FROM paragraphs WHERE id=?", (body.ref_paragraph_id,)).fetchone()
            text = row["text"] if row else ""
    elif body.kind == "note" and not text:
        raise HTTPException(400, "text required for a note pin")
    ord_ = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM pins WHERE talk_id=?", (talk_id,)).fetchone()[0]
    conn.execute(
        "INSERT INTO pins(talk_id, kind, ref_talk_id, ref_paragraph_id, scripture_ref, text, note, ord) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (talk_id, body.kind, body.ref_talk_id, body.ref_paragraph_id, body.scripture_ref, text, body.note, ord_))
    touch(conn, talk_id)
    return load_pins(conn, talk_id)


@router.get("/lessons/{talk_id:path}")
def get_lesson(talk_id: str, conn=Depends(get_conn)):
    row = conn.execute("SELECT notes_md, updated_at FROM lessons WHERE talk_id=?", (talk_id,)).fetchone()
    return {
        "talk_id": talk_id,
        "notes_md": row["notes_md"] if row else "",
        "updated_at": row["updated_at"] if row else None,
        "pins": load_pins(conn, talk_id),
    }


@router.put("/lessons/{talk_id:path}")
def put_notes(talk_id: str, body: NotesBody, conn=Depends(get_conn)):
    get_talk_or_404(conn, talk_id)
    ensure_lesson(conn, talk_id)
    conn.execute("UPDATE lessons SET notes_md=?, updated_at=datetime('now') WHERE talk_id=?",
                 (body.notes_md, talk_id))
    conn.commit()
    return get_lesson(talk_id, conn)


def touch(conn: sqlite3.Connection, talk_id: str) -> None:
    ensure_lesson(conn, talk_id)
    conn.execute("UPDATE lessons SET updated_at=datetime('now') WHERE talk_id=?", (talk_id,))
    conn.commit()


# ---------------------------------------------------------------- export

EXPORT_CSS = """
body{font-family:Georgia,'Times New Roman',serif;color:#1d2530;max-width:760px;margin:2rem auto;padding:0 1.25rem;line-height:1.55}
h1{font-size:1.7rem;margin:0 0 .25rem;color:#0b2e59}h2{font-size:1.15rem;margin:2rem 0 .75rem;color:#0b2e59;border-bottom:2px solid #c9a227;padding-bottom:.25rem}
.meta{color:#5b6570;font-size:.95rem;margin-bottom:1.5rem}.notes{font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:.98rem}
.pin{margin:0 0 1.25rem;padding:.75rem 1rem;border-left:3px solid #c9a227;background:#faf8f2}
.pin .kind{font:600 .72rem system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#8a6d1a}
.pin .src{font-family:system-ui,sans-serif;font-size:.85rem;color:#5b6570;margin-top:.35rem}
.pin blockquote{margin:.4rem 0;font-style:italic}.pin .note{font-family:system-ui,sans-serif;font-size:.9rem;margin-top:.4rem}
a{color:#0b2e59}@media print{body{margin:0;max-width:none}.pin{break-inside:avoid}}
"""


def render_export(conn: sqlite3.Connection, talk_id: str) -> str:
    talk = talk_row_to_dict(get_talk_or_404(conn, talk_id))
    lesson = get_lesson(talk_id, conn)
    esc = html.escape
    notes_html = markdown.markdown(lesson["notes_md"] or "", extensions=["extra", "sane_lists"]) \
        if lesson["notes_md"] else "<p><em>No notes yet.</em></p>"
    pins_html = []
    for p in lesson["pins"]:
        if p["kind"] == "scripture":
            head = f"<div class='kind'>Scripture</div><strong>{esc(p['scripture_ref'] or '')}</strong>"
            body = f"<blockquote>{esc(p['text'])}</blockquote>"
            src = ""
        elif p["kind"] == "note":
            head = "<div class='kind'>Note</div>"
            body = f"<div>{esc(p['text']).replace(chr(10), '<br>')}</div>"
            src = ""
        else:
            t = p.get("ref_talk") or {}
            head = f"<div class='kind'>{'Quote' if p['kind'] == 'quote' else 'Talk'}</div>"
            if p["kind"] == "talk":
                head += f"<strong>{esc(t.get('title', ''))}</strong>"
            body = f"<blockquote>{esc(p['text'])}</blockquote>" if p["text"] else ""
            src = (f"<div class='src'>{esc(t.get('speaker', ''))} · {esc(t.get('conference') or '')} · "
                   f"<a href='{esc(t.get('url', ''))}'>{esc(t.get('title', ''))}</a></div>") if t else ""
        note = f"<div class='note'>{esc(p['note'])}</div>" if p["note"] else ""
        pins_html.append(f"<div class='pin'>{head}{body}{src}{note}</div>")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Lesson prep: {esc(talk['title'])}</title>
<style>{EXPORT_CSS}</style></head><body>
<h1>{esc(talk['title'])}</h1>
<div class="meta">{esc(talk['speaker'])} · {esc(talk['conference'] or '')} · <a href="{esc(talk['url'])}">Read the talk</a></div>
<h2>Notes</h2><div class="notes">{notes_html}</div>
<h2>Pinned references ({len(pins_html)})</h2>{''.join(pins_html) or '<p><em>Nothing pinned yet.</em></p>'}
</body></html>"""
