# Security remediation plan (2026-09-21)

Implements the findings in `docs/security-review-2026-09-21.md`. Work through the tasks in order; each
one names the files, the exact behaviour wanted and the test that proves it. Read the corresponding
finding in the review before starting a task.

## Ground rules

- Personal project. Git identity is the global one; do not touch `git config`. Do **not** commit; leave
  the work unstaged for review.
- Python 3, FastAPI, SQLite. Tests: `python3 -m pytest -q` (38 pass today; all must still pass, plus the
  new ones). Frontend: `cd web && npm run build` must succeed. Do not run the real server on port 8765
  (Uri's LAN instance is on it); use another port for any manual probe and stop it afterwards.
- Never write a real secret anywhere. Never publish anything or call external services beyond `pip`.
- Keep changes minimal and local to the finding. No refactors, no renames of existing settings keys, no
  new frameworks. Match the existing code style (docstrings, `from __future__ import annotations`).
- When a task says "regression test", write the test first, confirm it fails against the current code,
  then fix.
- Out of scope (Uri decides these separately): rotating the leaked secrets, per-user AI/email quotas
  (F-07), SSRF allowlists for Ollama/SMTP hosts (F-13), restricting email recipients to registered users.

## Task 1 — F-01 path traversal in the SPA catch-all (Critical)

`server/main.py:63-72`. Serve a file only when its resolved path lies inside `web/dist`.

```python
WEB_DIST_RESOLVED = WEB_DIST.resolve()

@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path:
        try:
            candidate = (WEB_DIST_RESOLVED / full_path).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            candidate = None
        if candidate and candidate.is_file() and candidate.is_relative_to(WEB_DIST_RESOLVED):
            return FileResponse(candidate)
    return FileResponse(WEB_DIST_RESOLVED / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
```

Regression test in a new `tests/test_hardening.py` (reuse the `client` fixture pattern from
`tests/test_auth.py`; the SPA route only exists when `web/dist` exists, so `pytest.skip` if it doesn't):
request `/..%2f..%2frequirements.txt` and `/../../requirements.txt` (build the ASGI scope by hand if the
HTTP client normalises the path) and assert the body is `index.html`, never the requirements file.
Also assert `/assets/../../requirements.txt` is not served.

## Task 2 — F-02 secrets at rest (High)

Encrypt the three `SECRET_SETTINGS` values in the `settings` table with Fernet.

- Add `cryptography>=42` to `requirements.txt` (server section) and `pip install` it.
- New module `server/secrets_store.py`:
  - `_load_key()`: use `LP_SECRET_KEY` from the environment if set; otherwise read `DATA_DIR / "secret.key"`,
    creating it with `Fernet.generate_key()` and mode `0o600` on first use. Cache the `Fernet` instance.
  - `encrypt(plain: str) -> str` returns `"enc:" + token` (empty string stays empty).
  - `decrypt(stored: str) -> str`: values starting with `enc:` are decrypted; anything else is returned
    as-is (legacy plaintext). A failed decrypt raises a clear `RuntimeError` naming `LP_SECRET_KEY`.
- `server/settings.py`: `set_settings` encrypts keys in `SECRET_SETTINGS` before writing; `get_settings`
  and `get_setting` decrypt on read. Add `migrate_plaintext_secrets(conn)` that re-encrypts any legacy
  plaintext secret rows; call it once from `lifespan` in `server/main.py` after `apply_schema`.
- `mask()` must return a **fixed** `"••••••••"` for any non-empty value (drop the last-4 reveal). Keep it
  non-empty: `server/routers/settings.py:53-56` skips bullet-only echoes on write, and an empty string
  would clear the secret. Verify the Settings page still shows "Saved" placeholders
  (`web/src/views/SettingsView.vue:116,172,182` use the `_set` flags, so no UI change should be needed).
- On startup, if `DATA_DIR` is writable, `chmod 0o700` it (best effort, ignore errors).
- Tests: round-trip encrypt/decrypt; a plaintext row is readable and gets re-encrypted by the migration;
  `public_settings` never contains the plaintext or its last four characters; the raw `settings` row for
  `anthropic_api_key` starts with `enc:` after `set_settings`.
- README "Accounts" section: mention `LP_SECRET_KEY` (recommended on a server; otherwise
  `data/secret.key` is generated) and that secrets are encrypted at rest.

## Task 3 — F-06 fail-closed deployment flags (Medium)

`server/config.py:49-52`, `server/routers/auth.py:86-105`.

- `COOKIE_SECURE = BASE_URL.startswith("https://") or <existing LP_COOKIE_SECURE flag>`.
- At import time in `config.py`: if `TRUST_PROXY` or `COOKIE_SECURE` is true and `BASE_URL` is empty,
  raise `RuntimeError("LP_BASE_URL is required when LP_TRUST_PROXY or LP_COOKIE_SECURE is set")`. Also
  raise if `BASE_URL` is set but is not `http://` or `https://` or has a path component.
- `base_url()` in `routers/auth.py`: return `BASE_URL` when set; otherwise the socket-level address
  exactly as the last three lines do today. Remove the `X-Forwarded-Proto`/`X-Forwarded-Host` branch
  entirely (it is unreachable after the check above, and it was the poisoning vector).
- Tests: `monkeypatch.setenv` + `importlib.reload(server.config)` inside a test that asserts the
  RuntimeError for `LP_TRUST_PROXY=1` without `LP_BASE_URL`; reload again with a clean environment at
  the end so later tests are unaffected (use a fixture with teardown). Assert `COOKIE_SECURE` is true when
  `LP_BASE_URL=https://x.example`.

## Task 4 — F-05 / F-15 rate limiting behind a proxy (Medium)

`server/auth.py:167-186`, `server/routers/auth.py:36`.

- `client_ip`: when `TRUST_PROXY`, use the `X-Real-IP` header if present; else the **rightmost** entry of
  `X-Forwarded-For`; else the socket address. Never the leftmost entry.
- Add a per-account bucket on login: `rate_limit(f"login:acct:{body.email.strip().lower()}", limit=5,
  window_s=900)` in addition to the IP bucket. The 429 message stays the same.
- `rate_limit`: after popping expired entries, if the deque is empty and the request is allowed, fine;
  but when a deque becomes empty during pruning delete the key from `_buckets` so the dict does not grow
  forever (re-create it before appending).
- Tests: leftmost spoofed `X-Forwarded-For` does not bypass the limit when `TRUST_PROXY` is patched true
  (monkeypatch `server.auth.TRUST_PROXY`); six failed logins for one email from six different
  `X-Real-IP` values yield a 429 on the sixth; `_buckets` has no empty deques after the window passes
  (monkeypatch `time.monotonic`).

## Task 5 — F-04 security headers (Medium)

- New `server/middleware.py` with a pure-ASGI or `BaseHTTPMiddleware` that adds to every response:
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: camera=(), microphone=(), geolocation=()`
  - `X-Frame-Options: DENY`
  - `Content-Security-Policy` for HTML responses (or all responses; simpler):
    `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://img.youtube.com; frame-src https://www.youtube-nocookie.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains` only when `COOKIE_SECURE`.
- The lesson export at `server/routers/lessons.py:84-89` (`export_html`) gets a stricter CSP on that
  response: `default-src 'none'; style-src 'unsafe-inline'; img-src https: data:`. The middleware must not
  overwrite a CSP a route already set (only set the header if absent).
- `server/cli.py:66`: pass `server_header=False` to `uvicorn.run`.
- Check the built app still works under the CSP: `cd web && npm run build`, start the app on a spare
  port, load `/` in headless Chrome (`google-chrome --headless=new --dump-dom` or
  `--enable-logging --v=0` to see console errors) and confirm no CSP violation is logged for the landing
  page assets, Google Fonts or the YouTube poster. If Vite emits inline scripts, prefer fixing the build
  over loosening `script-src`.
- Test: `GET /api/health` carries the four fixed headers and a CSP; `export.html` (signed in) carries the
  stricter CSP; HSTS is absent when `COOKIE_SECURE` is false.

## Task 6 — F-03 sanitised export HTML and email throttle (High)

`server/routers/lessons.py:92-105, 281-282`.

- Add `nh3>=0.2` to `requirements.txt` and install it. In `render_export`, pass the Markdown output
  through `nh3.clean(notes_html)` (default allowlist; it strips `script`, event handlers and `javascript:`
  URLs). Only the notes block is user-authored Markdown; the rest is already `html.escape`d.
- `EmailBody.subject`: `Field(default=None, max_length=200)`.
- In `email_lesson`, before sending: `rate_limit(f"email:{user['id']}", limit=10, window_s=3600)`.
- Replace `HTTPException(502, f"Sending failed: {e}")` with a fixed message
  `"Sending failed. Check the email settings or try again later."` and log the exception (see Task 8).
- Tests: notes containing `<img src=x onerror=alert(1)>`, `<script>`, and `[x](javascript:alert(1))`
  produce export HTML with none of `onerror`, `<script`, `javascript:`; the eleventh email in an hour
  returns 429 (monkeypatch `server.routers.lessons.send_html` to a stub so nothing is sent).

## Task 7 — F-08 dependency pins

`requirements.txt`: `fastapi>=0.141`, add `starlette>=1.3.1`. Run `pip install -r requirements.txt` and
the test suite. Add a `make audit` target that runs `python3 -m pip_audit -r requirements.txt` (do not
add pip-audit to requirements; document `pip install pip-audit` in the target's comment).

## Task 8 — F-14 / F-12 security logging and error messages

- New `server/log.py` exposing `security = logging.getLogger("lp.security")` and a helper
  `event(name: str, **fields)` that emits one line `name key=value ...` at INFO (WARNING for failures).
  Configure basic logging to stderr in `server/cli.py` `serve` (INFO) if no handlers are configured.
- Emit events for: `login.ok`, `login.fail` (email hashed with SHA-256 truncated to 12 hex chars, never
  the plaintext email or password), `ratelimit.hit` (key prefix and client IP), `setpassword.ok`,
  `forgot.requested`, `forgot.send_failed` (WARNING, with the exception class name; replace the bare
  `except Exception: pass` at `routers/auth.py:81-82`), `invite.issued` (from `routers/users.py`),
  `user.patched` (admin, target user id, changed fields), `settings.written` (key names only, never
  values), `email.sent` (user id, recipient count), `email.failed`.
- `server/routers/chat.py:118-125`: store and return a fixed user-facing message
  (`"The AI request failed. Try again, or ask an admin to check the AI settings."`) and log the real
  exception with `security.exception(...)` or a `lp.ai` logger. Leave the admin-only test endpoints in
  `routers/settings.py` as they are (admins need the detail).
- Test: a failed login emits a `login.fail` record (use `caplog`) that does not contain the email.

## Task 9 — F-09 / F-10 / F-11 small auth fixes

- F-09 `routers/auth.py` `forgot`: only act when `user and not user["disabled"] and user["password_hash"]`.
  Test: `forgot` for an invited-but-unset user leaves the existing invite row untouched.
- F-10 `login`: always run `verify_password`. Add a module-level `_DUMMY_HASH = hash_password("dummy-timing-pad")`
  in `server/auth.py`; compute `ok = verify_password(body.password, user["password_hash"] if user and user["password_hash"] else _DUMMY_HASH)`
  then reject when `not user or user["disabled"] or not user["password_hash"] or not ok`.
- F-11 `web/src/views/LoginView.vue:27`: accept `next` only when `/^\/(?!\/)/.test(next)`.

## Task 10 — I-02 dev CORS in production

`server/main.py:35-40`. Check `web/vite.config.ts`: if the dev server proxies `/api` to 8765 the CORS
middleware is unnecessary and should be removed. If it does not proxy, keep the middleware but only add
it when `os.environ.get("LP_DEV") == "1"` and set `LP_DEV=1` in `dev.sh`.

## Task 11 — deploy files with safe defaults

Create `deploy/` so the secure configuration is the documented one:

- `deploy/lessonprep.service` (systemd, `User=lessonprep`, `WorkingDirectory=/opt/lessonprep`,
  `EnvironmentFile=/etc/lessonprep.env`, `ExecStart=/opt/lessonprep/.venv/bin/python -m server.cli serve --host 127.0.0.1 --port 8765`,
  `Restart=on-failure`, `ProtectSystem=strict`, `ReadWritePaths=/var/lib/lessonprep`, `PrivateTmp=yes`,
  `NoNewPrivileges=yes`).
- `deploy/lessonprep.env.example` with `LP_DATA_DIR=/var/lib/lessonprep`, `LP_BASE_URL=https://CHANGE.ME`,
  `LP_TRUST_PROXY=1`, `LP_SECRET_KEY=` (comment: generate with
  `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`), and a
  note that the file must be mode 0600.
- `deploy/nginx.conf`: HTTPS server block (certbot paths as placeholders), `proxy_pass http://127.0.0.1:8765`,
  `proxy_set_header X-Real-IP $remote_addr`, `X-Forwarded-Proto $scheme`, `Host $host`;
  `limit_req_zone $binary_remote_addr zone=lp_auth:1m rate=10r/m` applied to `location /api/auth/`;
  `client_max_body_size 1m`; HTTP→HTTPS redirect. No `add_header` lines (the app sets its headers).
- `deploy/README.md`: numbered steps from a fresh droplet (user, venv, clone to /opt, `LP_DATA_DIR`
  outside the clone with mode 700, copy env file, `make build`, `python -m server.cli migrate --admin-email`,
  enable the unit, certbot, nginx). Mention the traversal fix means the app may serve `web/dist` itself.

## Task 12 — docs

- README env-var paragraph (line ~89): rewrite to say `LP_BASE_URL` is required on any public deployment
  and implies `Secure` cookies when https; `LP_TRUST_PROXY=1` requires it; `LP_SECRET_KEY`.
- Append a dated section to `docs/follow-ups.md`: what was fixed (finding ids), what remains (rotation,
  F-07, F-13, recipient policy), and that `deploy/` now exists.

## Done when

- `python3 -m pytest -q` green with the new tests (expect roughly 50+).
- `cd web && npm run build` succeeds.
- Manual probe on a spare port: `curl --path-as-is -s -o /dev/null -w '%{http_code} %{size_download}\n' http://127.0.0.1:PORT/../../requirements.txt`
  returns the size of `index.html`, and `curl -sI http://127.0.0.1:PORT/api/health` shows the security
  headers and no `server:` header.
- `git status` shows only intended files; nothing committed.
- A short report: per task, what changed (files) and anything you could not do or chose differently, with
  the reason.
