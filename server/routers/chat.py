"""AI chat about the selected talk, streamed as server-sent events."""

from __future__ import annotations

import json
import sqlite3
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..ai import get_provider
from ..ai.base import ChatEvent, ProviderError
from ..ai.prompts import build_system
from ..ai.tools import TOOLS, ToolContext
from ..cite_check import CitationChecker, StreamScanner, scan
from ..deps import get_conn, get_engine, get_user
from ..log import security
from ..settings import get_settings
from .talks import talk_detail

router = APIRouter(tags=["chat"])


class ChatBody(BaseModel):
    talk_id: str
    message: str = Field(min_length=1, max_length=20_000)
    session_id: int | None = None


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def load_history(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    """Prior turns as plain text (tool traces collapsed) for the model."""
    out = []
    for r in conn.execute("SELECT role, content_json FROM chat_messages WHERE session_id=? ORDER BY id",
                          (session_id,)):
        blocks = json.loads(r["content_json"])
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        if not text:
            tools = [b.get("summary", "") for b in blocks if b.get("type") == "tool"]
            text = "(used tools: " + "; ".join(t for t in tools if t) + ")" if tools else "…"
        out.append({"role": r["role"], "content": text})
    # The API requires alternating roles starting with user; merge duplicates.
    merged: list[dict] = []
    for m in out:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n\n" + m["content"]
        else:
            merged.append(m)
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


@router.post("/chat")
def chat(body: ChatBody, request: Request, conn=Depends(get_conn), engine=Depends(get_engine), user=Depends(get_user)):
    uid = user["id"]
    settings = get_settings(conn)
    try:
        provider = get_provider(settings)
    except ProviderError as e:
        raise HTTPException(400, str(e))
    talk = talk_detail(body.talk_id, conn, user)  # 404s if missing
    system = build_system(talk, talk["paragraphs"])

    if body.session_id:
        row = conn.execute("SELECT id FROM chat_sessions WHERE id=? AND talk_id=? AND user_id=?",
                           (body.session_id, body.talk_id, uid)).fetchone()
        if not row:
            raise HTTPException(404, "session not found")
        session_id = body.session_id
    else:
        title = body.message.strip().split("\n")[0][:80]
        cur = conn.execute("INSERT INTO chat_sessions(user_id, talk_id, title, provider, model) VALUES(?,?,?,?,?)",
                           (uid, body.talk_id, title, provider.name, provider.model))
        session_id = cur.lastrowid
        conn.commit()

    history = load_history(conn, session_id)
    conn.execute("INSERT INTO chat_messages(session_id, role, content_json) VALUES(?,?,?)",
                 (session_id, "user", json.dumps([{"type": "text", "text": body.message}])))
    conn.execute("UPDATE chat_sessions SET updated_at=datetime('now') WHERE id=?", (session_id,))
    conn.commit()

    ctx = ToolContext(conn, engine, body.talk_id)
    checker = CitationChecker(conn)

    def gen() -> Iterator[str]:
        yield sse("start", {"session_id": session_id, "provider": provider.name, "model": provider.model})
        blocks: list[dict] = []
        text_buf: list[str] = []
        pending_tools: dict[str, dict] = {}
        error: str | None = None
        scanner = StreamScanner(checker)

        def flush_text():
            if text_buf:
                text = "".join(text_buf)
                # Kept with the text it belongs to, so a reloaded session renders the
                # same marks without re-checking anything.
                blocks.append({"type": "text", "text": text, "citations": scan(text, checker)})
                text_buf.clear()

        try:
            for ev in provider.stream(system, history, body.message, TOOLS, ctx.execute):
                if ev.type == "text_delta":
                    text_buf.append(ev.data["text"])
                    for c in scanner.feed(ev.data["text"]):
                        yield sse("citation", c)
                elif ev.type == "tool_call":
                    flush_text()
                    pending_tools[ev.data["id"]] = {"type": "tool", "id": ev.data["id"],
                                                    "name": ev.data["name"], "input": ev.data["input"]}
                elif ev.type == "tool_result":
                    t = pending_tools.pop(ev.data["id"], {"type": "tool", "id": ev.data["id"],
                                                          "name": ev.data["name"], "input": {}})
                    t.update(summary=ev.data.get("summary", ""), refs=ev.data.get("refs", []),
                             preview=ev.data.get("preview", ""))
                    blocks.append(t)
                elif ev.type == "error":
                    error = ev.data.get("message", "unknown error")
                yield sse(ev.type, ev.data)
        except Exception as e:  # never leave the client hanging
            security.exception("chat.failed user_id=%s talk_id=%s", uid, body.talk_id)
            error = "The AI request failed. Try again, or ask an admin to check the AI settings."
            yield sse("error", {"message": error})
        flush_text()
        if error:
            blocks.append({"type": "error", "text": error})
        cur = conn.execute("INSERT INTO chat_messages(session_id, role, content_json) VALUES(?,?,?)",
                           (session_id, "assistant", json.dumps(blocks, ensure_ascii=False)))
        conn.execute("UPDATE chat_sessions SET updated_at=datetime('now') WHERE id=?", (session_id,))
        conn.commit()
        yield sse("done", {"session_id": session_id, "message_id": cur.lastrowid})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/chat/sessions")
def list_sessions(talk_id: str, conn=Depends(get_conn), user=Depends(get_user)):
    rows = conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id=s.id) AS message_count "
        "FROM chat_sessions s WHERE talk_id=? AND user_id=? ORDER BY updated_at DESC", (talk_id, user["id"])).fetchall()
    return [dict(r) for r in rows]


@router.get("/chat/sessions/{session_id}")
def get_session(session_id: int, conn=Depends(get_conn), user=Depends(get_user)):
    s = conn.execute("SELECT * FROM chat_sessions WHERE id=? AND user_id=?", (session_id, user["id"])).fetchone()
    if not s:
        raise HTTPException(404, "session not found")
    msgs = [{"id": r["id"], "role": r["role"], "blocks": json.loads(r["content_json"]),
             "created_at": r["created_at"]}
            for r in conn.execute("SELECT * FROM chat_messages WHERE session_id=? ORDER BY id", (session_id,))]
    return {**dict(s), "messages": msgs}


@router.delete("/chat/sessions/{session_id}")
def delete_session(session_id: int, conn=Depends(get_conn), user=Depends(get_user)):
    own = conn.execute("SELECT id FROM chat_sessions WHERE id=? AND user_id=?", (session_id, user["id"])).fetchone()
    if not own:
        raise HTTPException(404, "session not found")
    conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
    conn.commit()
    return {"ok": True}
