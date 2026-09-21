"""Login, logout, current user, set/reset password."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..auth import (
    client_ip, consume_invite, create_session, destroy_session, get_user_by_email, hash_password,
    issue_invite, rate_limit, user_to_dict, verify_password,
)
from ..config import BASE_URL
from ..deps import get_conn, get_user
from ..mailer import email_ready, send_html
from ..settings import get_settings

router = APIRouter(tags=["auth"])


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class SetPasswordBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class ForgotBody(BaseModel):
    email: str = Field(min_length=3, max_length=200)


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, conn=Depends(get_conn)):
    rate_limit(f"login:{client_ip(request)}", limit=10, window_s=600)
    user = get_user_by_email(conn, body.email)
    if not user or user["disabled"] or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect.")
    create_session(conn, response, user["id"], request.headers.get("user-agent", ""))
    return user_to_dict(user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, conn=Depends(get_conn)):
    destroy_session(conn, request, response)
    return {"ok": True}


@router.get("/auth/me")
def me(user=Depends(get_user)):
    return user_to_dict(user)


@router.post("/auth/set-password")
def set_password(body: SetPasswordBody, request: Request, response: Response, conn=Depends(get_conn)):
    rate_limit(f"setpw:{client_ip(request)}", limit=10, window_s=600)
    user = consume_invite(conn, body.token)
    conn.execute("UPDATE users SET password_hash=?, disabled=0 WHERE id=?", (hash_password(body.password), user["id"]))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))  # log out other devices
    conn.commit()
    create_session(conn, response, user["id"], request.headers.get("user-agent", ""))
    return user_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())


@router.post("/auth/forgot")
def forgot(body: ForgotBody, request: Request, conn=Depends(get_conn)):
    """Always answers 200 so addresses cannot be probed."""
    rate_limit(f"forgot:{client_ip(request)}", limit=5, window_s=3600)
    user = get_user_by_email(conn, body.email)
    if user and not user["disabled"]:
        settings = get_settings(conn)
        if email_ready(settings):
            token = issue_invite(conn, user["id"], hours=2)
            link = f"{base_url(request)}/set-password?token={token}"
            try:
                send_html(settings, [user["email"]], "Lesson Prep: reset your password",
                          f"<p>Someone asked to reset the password for {user['email']} on Lesson Prep.</p>"
                          f"<p><a href='{link}'>Choose a new password</a> (link valid for two hours).</p>"
                          "<p>If that wasn't you, ignore this message.</p>")
            except Exception:
                pass
    return {"ok": True}


def base_url(request: Request) -> str:
    if BASE_URL:
        return BASE_URL.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}"
