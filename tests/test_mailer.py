import pytest

from server import mailer
from server.mailer import MailConfigError, email_ready, missing_email_setup, send_html, html_to_text


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def test_email_ready_and_hints():
    s = {"email_provider": "postmark", "email_from": "", "postmark_server_token": ""}
    assert not email_ready(s) and "from-address" in missing_email_setup(s)
    s["email_from"] = "me@example.com"
    assert not email_ready(s) and "Postmark server token" in missing_email_setup(s)
    s["postmark_server_token"] = "tok"
    assert email_ready(s)
    smtp = {"email_provider": "smtp", "email_from": "me@example.com", "smtp_host": ""}
    assert "SMTP host" in missing_email_setup(smtp)


def test_postmark_send_payload(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return FakeResp(200, {"ErrorCode": 0, "MessageID": "abc"})

    monkeypatch.setattr(mailer.httpx, "post", fake_post)
    s = {"email_provider": "postmark", "email_from": "me@example.com", "postmark_server_token": "tok"}
    info = send_html(s, ["a@example.com", "b@example.com"], "Subj", "<p>Hi <b>there</b></p>")
    assert info == {"provider": "postmark", "message_id": "abc"}
    assert seen["headers"]["X-Postmark-Server-Token"] == "tok"
    assert seen["json"]["To"] == "a@example.com, b@example.com"
    assert seen["json"]["From"] == "me@example.com"
    assert seen["json"]["TextBody"] == "Hi there"


def test_postmark_error_is_reported(monkeypatch):
    monkeypatch.setattr(mailer.httpx, "post",
                        lambda *a, **k: FakeResp(422, {"ErrorCode": 10, "Message": "Bad or missing Server API token."}))
    s = {"email_provider": "postmark", "email_from": "me@example.com", "postmark_server_token": "bad"}
    with pytest.raises(MailConfigError) as e:
        send_html(s, ["a@example.com"], "Subj", "<p>x</p>")
    assert "bad server token" in str(e.value)


def test_recipient_validation():
    s = {"email_provider": "postmark", "email_from": "me@example.com", "postmark_server_token": "tok"}
    with pytest.raises(MailConfigError):
        send_html(s, ["not-an-email"], "Subj", "<p>x</p>")
    with pytest.raises(MailConfigError):
        send_html(s, [], "Subj", "<p>x</p>")


def test_html_to_text():
    assert html_to_text("<h1>T</h1><p>a</p><p>b<br>c</p>") == "T\na\nb\nc"
