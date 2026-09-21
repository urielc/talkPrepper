"""Per-lesson notes and pinned references, with HTML export and email."""

from __future__ import annotations

import html
import sqlite3
from typing import Literal

import markdown
import nh3
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..auth import rate_limit
from ..deps import get_conn, get_user
from ..log import event, security
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
    subject: str | None = Field(default=None, max_length=200)


def ensure_lesson(conn: sqlite3.Connection, uid: int, talk_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO lessons(user_id, talk_id) VALUES(?, ?)", (uid, talk_id))


def pin_to_dict(r: sqlite3.Row, talks: dict[str, dict]) -> dict:
    d = dict(r)
    d["ref_talk"] = talks.get(r["ref_talk_id"]) if r["ref_talk_id"] else None
    return d


def load_pins(conn: sqlite3.Connection, uid: int, talk_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM pins WHERE user_id=? AND talk_id=? ORDER BY ord, id", (uid, talk_id)).fetchall()
    talks = fetch_talks(conn, [r["ref_talk_id"] for r in rows if r["ref_talk_id"]])
    return [pin_to_dict(r, talks) for r in rows]


@router.get("/lessons")
def list_lessons(conn=Depends(get_conn), user=Depends(get_user)):
    rows = conn.execute(
        "SELECT l.talk_id, l.updated_at, LENGTH(l.notes_md) AS notes_len, "
        "(SELECT COUNT(*) FROM pins p WHERE p.talk_id=l.talk_id AND p.user_id=l.user_id) AS pin_count, "
        "(SELECT COUNT(*) FROM chat_sessions s WHERE s.talk_id=l.talk_id AND s.user_id=l.user_id) AS chat_count "
        "FROM lessons l WHERE l.user_id=? ORDER BY l.updated_at DESC LIMIT 50", (user["id"],)).fetchall()
    talks = fetch_talks(conn, [r["talk_id"] for r in rows])
    out = []
    for r in rows:
        if r["talk_id"] in talks and (r["notes_len"] or r["pin_count"] or r["chat_count"]):
            out.append({"talk": talks[r["talk_id"]], "updated_at": r["updated_at"],
                        "notes_len": r["notes_len"], "pin_count": r["pin_count"],
                        "chat_count": r["chat_count"]})
    return out


EXPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:"


@router.get("/lessons/{talk_id:path}/export.html", response_class=HTMLResponse)
def export_html(talk_id: str, sections: str | None = None, conn=Depends(get_conn), user=Depends(get_user)):
    """Printable lesson sheet. ``sections`` is a comma list drawn from
    notes, essence, points, quotes, questions, pins; omitted means everything."""
    chosen = [x.strip() for x in sections.split(",") if x.strip()] if sections else None
    return HTMLResponse(render_export(conn, user["id"], talk_id, chosen),
                        headers={"Content-Security-Policy": EXPORT_CSP, "X-Content-Type-Options": "nosniff"})


@router.post("/lessons/{talk_id:path}/email")
def email_lesson(talk_id: str, body: EmailBody, conn=Depends(get_conn), user=Depends(get_user)):
    talk = talk_row_to_dict(get_talk_or_404(conn, talk_id))
    settings = get_settings(conn)
    if not email_ready(settings):
        raise HTTPException(400, "Email is not configured. " + missing_email_setup(settings))
    rate_limit(f"email:{user['id']}", limit=10, window_s=3600)
    subject = body.subject or f"Lesson prep: {talk['title']} ({talk['speaker']})"
    try:
        info = send_html(settings, body.to, subject, render_export(conn, user["id"], talk_id))
    except MailConfigError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # network / smtplib errors
        security.exception("email.failed user_id=%s recipients=%d", user["id"], len(body.to))
        raise HTTPException(502, "Sending failed. Check the email settings or try again later.")
    event("email.sent", user_id=user["id"], recipients=len(body.to))
    return {"ok": True, "to": body.to, "subject": subject, **info}


@router.post("/lessons/{talk_id:path}/pins/reorder")
def reorder_pins(talk_id: str, body: ReorderBody, conn=Depends(get_conn), user=Depends(get_user)):
    uid = user["id"]
    for i, pid in enumerate(body.ids):
        conn.execute("UPDATE pins SET ord=? WHERE id=? AND talk_id=? AND user_id=?", (i, pid, talk_id, uid))
    touch(conn, uid, talk_id)
    return load_pins(conn, uid, talk_id)


@router.patch("/lessons/{talk_id:path}/pins/{pin_id}")
def patch_pin(talk_id: str, pin_id: int, body: PinPatch, conn=Depends(get_conn), user=Depends(get_user)):
    uid = user["id"]
    row = conn.execute("SELECT id FROM pins WHERE id=? AND talk_id=? AND user_id=?", (pin_id, talk_id, uid)).fetchone()
    if not row:
        raise HTTPException(404, "pin not found")
    if body.text is not None:
        conn.execute("UPDATE pins SET text=? WHERE id=?", (body.text, pin_id))
    if body.note is not None:
        conn.execute("UPDATE pins SET note=? WHERE id=?", (body.note, pin_id))
    touch(conn, uid, talk_id)
    return load_pins(conn, uid, talk_id)


@router.delete("/lessons/{talk_id:path}/pins/{pin_id}")
def delete_pin(talk_id: str, pin_id: int, conn=Depends(get_conn), user=Depends(get_user)):
    uid = user["id"]
    conn.execute("DELETE FROM pins WHERE id=? AND talk_id=? AND user_id=?", (pin_id, talk_id, uid))
    touch(conn, uid, talk_id)
    return load_pins(conn, uid, talk_id)


@router.post("/lessons/{talk_id:path}/pins")
def add_pin(talk_id: str, body: PinBody, conn=Depends(get_conn), user=Depends(get_user)):
    uid = user["id"]
    get_talk_or_404(conn, talk_id)
    ensure_lesson(conn, uid, talk_id)
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
    ord_ = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM pins WHERE talk_id=? AND user_id=?",
                        (talk_id, uid)).fetchone()[0]
    conn.execute(
        "INSERT INTO pins(user_id, talk_id, kind, ref_talk_id, ref_paragraph_id, scripture_ref, text, note, ord) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (uid, talk_id, body.kind, body.ref_talk_id, body.ref_paragraph_id, body.scripture_ref, text, body.note, ord_))
    touch(conn, uid, talk_id)
    return load_pins(conn, uid, talk_id)


def lesson_for(conn: sqlite3.Connection, uid: int, talk_id: str) -> dict:
    row = conn.execute("SELECT notes_md, updated_at FROM lessons WHERE user_id=? AND talk_id=?",
                       (uid, talk_id)).fetchone()
    return {
        "talk_id": talk_id,
        "notes_md": row["notes_md"] if row else "",
        "updated_at": row["updated_at"] if row else None,
        "pins": load_pins(conn, uid, talk_id),
    }


@router.get("/lessons/{talk_id:path}")
def get_lesson(talk_id: str, conn=Depends(get_conn), user=Depends(get_user)):
    return lesson_for(conn, user["id"], talk_id)


@router.put("/lessons/{talk_id:path}")
def put_notes(talk_id: str, body: NotesBody, conn=Depends(get_conn), user=Depends(get_user)):
    uid = user["id"]
    get_talk_or_404(conn, talk_id)
    ensure_lesson(conn, uid, talk_id)
    conn.execute("UPDATE lessons SET notes_md=?, updated_at=datetime('now') WHERE user_id=? AND talk_id=?",
                 (body.notes_md, uid, talk_id))
    conn.commit()
    return lesson_for(conn, uid, talk_id)


def touch(conn: sqlite3.Connection, uid: int, talk_id: str) -> None:
    ensure_lesson(conn, uid, talk_id)
    conn.execute("UPDATE lessons SET updated_at=datetime('now') WHERE user_id=? AND talk_id=?", (uid, talk_id))
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
.essence{font-size:1.08rem;line-height:1.6}.points{padding-left:1.4rem}.points li{margin-bottom:.45rem}
.quote{margin:0 0 1rem;padding:.6rem 1rem;border-left:3px solid #c9a227;background:#faf8f2}.quote blockquote{margin:0 0 .3rem;font-style:italic}
.quote .why,.q .qnote{font-family:system-ui,sans-serif;font-size:.88rem;color:#5b6570}
.qkind{font:600 .78rem system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#8a6d1a;margin:1rem 0 .35rem}
.q{margin:0 0 .8rem}.q .qtext{font-size:1.02rem;margin:0 0 .15rem}
a{color:#0b2e59}
@page{size:letter;margin:0.45in 0.55in}
@media print{
  body{margin:0;max-width:none;font-size:10pt;line-height:1.32;color:#000}
  h1{font-size:15pt;margin:0 0 .1rem}h2{font-size:11pt;margin:.7rem 0 .35rem;padding-bottom:.1rem;break-after:avoid}
  .meta{font-size:8.5pt;margin-bottom:.6rem}.notes{font-size:9.5pt}.notes p,.notes li{margin:.15rem 0}
  .essence{font-size:10pt;line-height:1.35}.points{padding-left:1.1rem}.points li{margin-bottom:.15rem}
  .quote{margin:0 0 .4rem;padding:.3rem .6rem;background:none;border-left-width:2px}.quote blockquote{margin:0 0 .1rem}
  .quote .why,.q .qnote,.pin .src,.pin .note{font-size:8.5pt}
  .qkind{font-size:7.5pt;margin:.5rem 0 .2rem}.q{margin:0 0 .4rem}.q .qtext{font-size:10pt;margin:0}
  .pin{margin:0 0 .45rem;padding:.3rem .6rem;background:none;border-left-width:2px}.pin .kind{font-size:6.5pt}
  .pin blockquote{margin:.1rem 0}.pin .note{margin-top:.15rem}.pin .src{margin-top:.15rem}
  .pin,.quote,.q{break-inside:avoid}a{text-decoration:none;color:inherit}
}
"""

ALL_SECTIONS = ["notes", "essence", "points", "quotes", "questions", "pins"]
SECTION_TITLES = {"essence": "Essence", "points": "Main points", "quotes": "Worth reading aloud",
                  "questions": "Questions for the quorum"}
KIND_LABEL = {"opening": "Opening", "discussion": "Discussion", "application": "Application"}


def render_digest_sections(digest: dict | None, chosen: list[str]) -> str:
    esc = html.escape
    wanted = [k for k in ("essence", "points", "quotes", "questions") if k in chosen]
    if not wanted:
        return ""
    if not digest:
        return "<h2>Digest</h2><p><em>No digest has been generated for this talk yet.</em></p>"
    out = []
    if "essence" in wanted:
        out.append(f"<h2>Essence</h2><p class='essence'>{esc(digest.get('essence', ''))}</p>")
    if "points" in wanted:
        items = "".join(f"<li>{esc(m.get('point', ''))}</li>" for m in digest.get("main_points", []))
        out.append(f"<h2>Main points</h2><ol class='points'>{items}</ol>")
    if "quotes" in wanted:
        qs = "".join(
            f"<div class='quote'><blockquote>“{esc(q.get('text', ''))}”</blockquote>"
            f"<div class='why'>{esc(q.get('why', ''))}</div></div>"
            for q in digest.get("key_quotes", []))
        out.append(f"<h2>Worth reading aloud</h2>{qs}")
    if "questions" in wanted:
        blocks = []
        for kind in ("opening", "discussion", "application"):
            qs = [q for q in digest.get("questions", []) if q.get("kind", "discussion") == kind]
            if not qs:
                continue
            blocks.append(f"<div class='qkind'>{KIND_LABEL[kind]}</div>" + "".join(
                f"<div class='q'><p class='qtext'>{esc(q.get('question', ''))}</p>"
                f"<div class='qnote'>{esc(q.get('note', ''))}</div></div>" for q in qs))
        out.append("<h2>Questions for the quorum</h2>" + "".join(blocks))
    return "".join(out)


def render_export(conn: sqlite3.Connection, uid: int, talk_id: str, sections: list[str] | None = None) -> str:
    from ..ai.digest import load_digest
    chosen = [x for x in (sections or ALL_SECTIONS) if x in ALL_SECTIONS] or ALL_SECTIONS
    talk = talk_row_to_dict(get_talk_or_404(conn, talk_id))
    lesson = lesson_for(conn, uid, talk_id)
    digest_html = render_digest_sections(load_digest(conn, talk_id), chosen)
    esc = html.escape
    notes_html = nh3.clean(markdown.markdown(lesson["notes_md"] or "", extensions=["extra", "sane_lists"])) \
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
{f'<h2>Notes</h2><div class="notes">{notes_html}</div>' if 'notes' in chosen else ''}
{digest_html}
{f"<h2>Pinned references ({len(pins_html)})</h2>{''.join(pins_html) or '<p><em>Nothing pinned yet.</em></p>'}" if 'pins' in chosen else ''}
</body></html>"""
