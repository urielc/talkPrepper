"""Login, logout, current user, set/reset password."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..auth import (
    _DUMMY_HASH, _buckets, client_ip, consume_invite, create_session, destroy_session, get_user_by_email,
    hash_password, issue_invite, rate_limit, user_to_dict, verify_password,
)
from ..config import BASE_URL
from ..deps import get_conn, get_user
from ..log import event, hash_email, security
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
    acct_key = f"login:acct:{body.email.strip().lower()}"
    rate_limit(acct_key, limit=5, window_s=900)
    user = get_user_by_email(conn, body.email)
    # Always run the argon2 verification, even for an unknown/disabled/passwordless
    # account, against a fixed dummy hash: this keeps the response time the same
    # either way, so it cannot be used to enumerate registered addresses.
    ok = verify_password(body.password, user["password_hash"] if user and user["password_hash"] else _DUMMY_HASH)
    if not user or user["disabled"] or not user["password_hash"] or not ok:
        event("login.fail", email_hash=hash_email(body.email), ip=client_ip(request))
        raise HTTPException(401, "Email or password is incorrect.")
    event("login.ok", user_id=user["id"], ip=client_ip(request))
    _buckets.pop(acct_key, None)  # a correct password ends the failed-attempt count for this account
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
    event("setpassword.ok", user_id=user["id"])
    create_session(conn, response, user["id"], request.headers.get("user-agent", ""))
    return user_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())


@router.post("/auth/forgot")
def forgot(body: ForgotBody, request: Request, conn=Depends(get_conn)):
    """Always answers 200 so addresses cannot be probed."""
    rate_limit(f"forgot:{client_ip(request)}", limit=5, window_s=3600)
    user = get_user_by_email(conn, body.email)
    # Only a user who can actually sign in has anything to reset. An invited
    # user with no password yet still has their original (unused) invite;
    # issuing a reset here would delete it (issue_invite supersedes any unused
    # invite for the same user) and hand the attacker a fresh, shorter-lived
    # token in its place instead of anything usable.
    if user and not user["disabled"] and user["password_hash"]:
        event("forgot.requested", user_id=user["id"])
        settings = get_settings(conn)
        if email_ready(settings):
            token = issue_invite(conn, user["id"], hours=2)
            link = f"{base_url(request)}/set-password?token={token}"
            try:
                send_html(settings, [user["email"]], "Lesson Prep: reset your password",
                          f"<p>Someone asked to reset the password for {user['email']} on Lesson Prep.</p>"
                          f"<p><a href='{link}'>Choose a new password</a> (link valid for two hours).</p>"
                          "<p>If that wasn't you, ignore this message.</p>")
            except Exception as e:
                security.warning("forgot.send_failed user_id=%s error=%s", user["id"], type(e).__name__)
    return {"ok": True}


def base_url(request: Request) -> str:
    """Origin for links placed in emails.

    Never derived from the Host header: an attacker could request a password
    reset for a victim with a forged Host and receive the token when the victim
    clicks the poisoned link. Production sets LP_BASE_URL (required whenever
    LP_TRUST_PROXY or LP_COOKIE_SECURE is set — see server/config.py); a LAN
    install without it falls back to the socket-level address the request
    actually arrived on.
    """
    if BASE_URL:
        return BASE_URL
    server = request.scope.get("server")
    host = f"{server[0]}:{server[1]}" if server else request.url.netloc
    return f"{request.url.scheme}://{host}"
