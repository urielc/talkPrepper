"""Send lesson exports by email.

Two providers, chosen by the ``email_provider`` setting:

* ``postmark`` (default): Postmark's HTTP API with a server token. The
  from-address must be a verified sender signature or domain in Postmark.
* ``smtp``: any SMTP server (also works with Postmark's SMTP endpoint).
"""

from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from .config import POSTMARK_API_URL

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class MailConfigError(RuntimeError):
    pass


def email_ready(settings: dict) -> bool:
    if not settings.get("email_from"):
        return False
    if settings.get("email_provider", "postmark") == "postmark":
        return bool(settings.get("postmark_server_token"))
    return bool(settings.get("smtp_host"))


def missing_email_setup(settings: dict) -> str:
    prov = settings.get("email_provider", "postmark")
    if not settings.get("email_from"):
        return "Set the from-address in Settings → Email."
    if prov == "postmark" and not settings.get("postmark_server_token"):
        return "Enter your Postmark server token in Settings → Email."
    if prov == "smtp" and not settings.get("smtp_host"):
        return "Enter your SMTP host in Settings → Email."
    return ""


def html_to_text(html: str) -> str:
    text = re.sub(r"<(br|/p|/h\d|/li|/tr)[^>]*>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _validate(settings: dict, to: list[str]) -> None:
    if not email_ready(settings):
        raise MailConfigError("Email is not configured. " + missing_email_setup(settings))
    if not to:
        raise MailConfigError("No recipients.")
    for addr in to:
        if not EMAIL_RE.fullmatch(addr):
            raise MailConfigError(f"Invalid email address: {addr}")


def send_html(settings: dict, to: list[str], subject: str, html: str) -> dict:
    _validate(settings, to)
    if settings.get("email_provider", "postmark") == "postmark":
        return _send_postmark(settings, to, subject, html)
    return _send_smtp(settings, to, subject, html)


def _send_postmark(settings: dict, to: list[str], subject: str, html: str) -> dict:
    payload = {
        "From": settings["email_from"],
        "To": ", ".join(to),
        "Subject": subject,
        "HtmlBody": html,
        "TextBody": html_to_text(html),
        "MessageStream": "outbound",
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Postmark-Server-Token": settings["postmark_server_token"],
    }
    r = httpx.post(POSTMARK_API_URL, json=payload, headers=headers, timeout=30)
    try:
        data = r.json()
    except ValueError:
        data = {"Message": r.text}
    if r.status_code != 200 or data.get("ErrorCode", 0) != 0:
        msg = data.get("Message") or f"HTTP {r.status_code}"
        code = data.get("ErrorCode")
        hint = ""
        if code == 10:
            hint = " (bad server token)"
        elif code in (400, 401):
            hint = " (the from-address must be a verified sender signature in Postmark)"
        raise MailConfigError(f"Postmark rejected the message: {msg}{hint}")
    return {"provider": "postmark", "message_id": data.get("MessageID")}


def _send_smtp(settings: dict, to: list[str], subject: str, html: str) -> dict:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings["email_from"]
    msg["To"] = ", ".join(to)
    msg.set_content(html_to_text(html))
    msg.add_alternative(html, subtype="html")

    host = settings["smtp_host"]
    port = int(settings.get("smtp_port") or 587)
    mode = (settings.get("smtp_tls") or "starttls").lower()
    user = settings.get("smtp_user") or ""
    password = settings.get("smtp_password") or ""
    context = ssl.create_default_context()

    if mode == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    try:
        server.ehlo()
        if mode == "starttls":
            server.starttls(context=context)
            server.ehlo()
        if user:
            server.login(user, password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return {"provider": "smtp"}
