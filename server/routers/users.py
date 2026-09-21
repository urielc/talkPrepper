"""Admin: invite and manage users."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import create_user, issue_invite, user_to_dict
from ..deps import get_admin, get_conn
from ..mailer import MailConfigError, email_ready, missing_email_setup, send_html
from ..settings import get_settings
from .auth import base_url

router = APIRouter(tags=["users"])


class InviteBody(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str = Field("", max_length=120)
    is_admin: bool = False


class UserPatch(BaseModel):
    name: str | None = Field(None, max_length=120)
    is_admin: bool | None = None
    disabled: bool | None = None


def _list(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
    pending = {r["user_id"] for r in conn.execute(
        "SELECT user_id FROM invites WHERE used_at IS NULL AND expires_at > strftime('%Y-%m-%dT%H:%M:%SZ','now')")}
    out = []
    for r in rows:
        d = user_to_dict(r)
        d["invite_pending"] = r["id"] in pending
        out.append(d)
    return out


def _send_invite(conn, request: Request, user, hours: int = 72) -> dict:
    settings = get_settings(conn)
    token = issue_invite(conn, user["id"], hours=hours)
    link = f"{base_url(request)}/set-password?token={token}"
    if not email_ready(settings):
        # No mail configured: hand the link to the admin to pass on by other means.
        return {"emailed": False, "link": link, "reason": missing_email_setup(settings)}
    try:
        send_html(settings, [user["email"]], "You're invited to Lesson Prep",
                  f"<p>{user['name'] or user['email']}, you have been invited to Lesson Prep, a preparation "
                  f"tool for lessons built on General Conference talks.</p>"
                  f"<p><a href='{link}'>Choose your password</a> to get started (link valid for three days).</p>")
    except MailConfigError as e:
        return {"emailed": False, "link": link, "reason": str(e)}
    except Exception as e:
        return {"emailed": False, "link": link, "reason": f"Sending failed: {e}"}
    return {"emailed": True}


@router.get("/users")
def list_users(conn=Depends(get_conn), _admin=Depends(get_admin)):
    return _list(conn)


@router.post("/users")
def invite(body: InviteBody, request: Request, conn=Depends(get_conn), _admin=Depends(get_admin)):
    user = create_user(conn, body.email, name=body.name, is_admin=body.is_admin)
    result = _send_invite(conn, request, user)
    return {"user": user_to_dict(user), **result}


@router.post("/users/{user_id}/invite")
def resend_invite(user_id: int, request: Request, conn=Depends(get_conn), _admin=Depends(get_admin)):
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(404, "user not found")
    return _send_invite(conn, request, user)


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, conn=Depends(get_conn), admin=Depends(get_admin)):
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(404, "user not found")
    if user_id == admin["id"] and (body.disabled or body.is_admin is False):
        raise HTTPException(400, "You cannot disable or demote your own account.")
    if body.name is not None:
        conn.execute("UPDATE users SET name=? WHERE id=?", (body.name.strip(), user_id))
    if body.is_admin is not None:
        conn.execute("UPDATE users SET is_admin=? WHERE id=?", (int(body.is_admin), user_id))
    if body.disabled is not None:
        conn.execute("UPDATE users SET disabled=? WHERE id=?", (int(body.disabled), user_id))
        if body.disabled:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.commit()
    return _list(conn)
