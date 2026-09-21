"""Settings: AI provider, keys, models, SMTP."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import SETTINGS_DEFAULTS, SECRET_SETTINGS
from ..deps import get_admin, get_conn, get_user
from ..log import event
from ..mailer import send_html, MailConfigError, email_ready, missing_email_setup
from ..settings import get_settings, set_settings, public_settings

router = APIRouter(tags=["settings"])


class SettingsBody(BaseModel):
    values: dict[str, str]


class TestEmailBody(BaseModel):
    to: str = Field(min_length=3)


@router.get("/ai-status")
def ai_status(conn=Depends(get_conn), _user=Depends(get_user)):
    """Whether the AI assistant is usable; safe for non-admins (no secrets)."""
    s = get_settings(conn)
    prov = s.get("ai_provider") or "anthropic"
    if prov == "anthropic":
        out = {"configured": bool(s.get("anthropic_api_key")), "provider": prov, "label": f"Claude ({s.get('anthropic_model')})"}
    else:
        out = {"configured": bool(s.get("ollama_model")), "provider": prov, "label": f"Ollama ({s.get('ollama_model') or 'no model'})"}
    out["email_ready"] = email_ready(s)
    out["email_missing"] = missing_email_setup(s)
    return out


@router.get("/settings")
def read_settings(conn=Depends(get_conn), _admin=Depends(get_admin)):
    out = public_settings(conn)
    s = get_settings(conn)
    out["email_ready"] = email_ready(s)
    out["email_missing"] = missing_email_setup(s)
    return out


@router.put("/settings")
def write_settings(body: SettingsBody, conn=Depends(get_conn), _admin=Depends(get_admin)):
    clean = {}
    for k, v in body.values.items():
        if k not in SETTINGS_DEFAULTS:
            continue
        # Masked secrets echoed back from the UI are not changes.
        if k in SECRET_SETTINGS and v and set(v) <= {"•"}:
            continue
        if k in SECRET_SETTINGS and v.startswith("••••••••"):
            continue
        clean[k] = v.strip() if isinstance(v, str) else v
    set_settings(conn, clean)
    if clean:
        event("settings.written", admin_id=_admin["id"], keys=",".join(sorted(clean)))
    return public_settings(conn)


@router.post("/settings/test-ai")
def test_ai(conn=Depends(get_conn), _admin=Depends(get_admin)):
    from ..ai import get_provider
    settings = get_settings(conn)
    try:
        provider = get_provider(settings)
        info = provider.ping()
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **info}


@router.get("/settings/ollama/models")
def ollama_models(conn=Depends(get_conn), _admin=Depends(get_admin)):
    settings = get_settings(conn)
    base = (settings.get("ollama_base_url") or "").rstrip("/")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=5)
        r.raise_for_status()
        return {"models": [m["name"] for m in r.json().get("models", [])]}
    except Exception as e:
        raise HTTPException(400, f"Could not reach Ollama at {base}: {e}")


@router.post("/settings/test-email")
def test_email(body: TestEmailBody, conn=Depends(get_conn), _admin=Depends(get_admin)):
    settings = get_settings(conn)
    try:
        info = send_html(settings, [body.to], "Lesson Prep: test email",
                         "<p>Your email settings work. This is a test message from Lesson Prep.</p>")
    except MailConfigError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Email error: {e}")
    return {"ok": True, **info}
