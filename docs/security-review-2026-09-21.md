# Security review — Lesson Prep (churchreferencematerial)

**Date:** 2026-09-21
**Scope:** `server/`, `web/src/`, `Makefile`, `requirements.txt`, `web/package.json`, git history (17 commits, HEAD `1fb24f1`). No `.github/` directory exists.
**Baseline:** OWASP Top 10 (2021), OWASP ASVS 4.0 Level 1 where applicable.
**Method:** Read-only review of every router and module; each finding was confirmed by reading the code path and, where possible, by exercising the running app on a throwaway port (`uvicorn` on 127.0.0.1:8799/8798, `curl --path-as-is`). `pytest` (38 tests) passes. `pip-audit` and `npm audit` were run. Review assumes the intended deployment: public droplet, nginx in front, HTTPS.

---

## Summary

The application's authentication and authorization design is sound: argon2id password hashing, random server-side session tokens stored hashed in an HttpOnly/SameSite=Lax cookie, hashed single-use invite/reset tokens, every data endpoint scoped by `user_id`, fully parameterised SQL, and DOMPurify on every `v-html`. It is undone by one bug: the SPA catch-all route in `server/main.py` joins the raw request path onto `web/dist` without a containment check, so an unauthenticated request for `/../../data/app.db` returns the whole SQLite database, which holds the Anthropic API key, Postmark/SMTP credentials, every user's email, password hashes, and notes in plaintext. That must be fixed (and the keys rotated) before the app is reachable from the internet. Behind it sit a cluster of medium issues typical of a LAN app being promoted to public hosting: no security headers, secrets at rest in the database, IP-based rate limiting that breaks or is bypassable behind a proxy, security-critical behaviour gated on optional environment variables, unsanitised Markdown in the emailed/printed export, an outdated Starlette, and no security logging.

| Severity | Count |
|---|---|
| Critical | 1 |
| High | 2 |
| Medium | 7 |
| Low | 6 |
| Informational | 6 |

---

## Findings

### CRITICAL

#### F-01 — Unauthenticated path traversal in the SPA catch-all serves any file on disk (including `data/app.db`)

- **Location:** `server/main.py:63-72`
- **OWASP:** A01:2021 Broken Access Control (CWE-22); ASVS 12.3.1
- **Evidence:**
  ```python
  @app.get("/{full_path:path}", include_in_schema=False)
  def spa(full_path: str):
      candidate = WEB_DIST / full_path
      if full_path and candidate.is_file():
          return FileResponse(candidate)
  ```
  Uvicorn does not normalise dot segments, so `full_path` can contain `..`. Verified against the running app:
  ```
  GET /../../data/README.md          -> 200 text/markdown  (repo file)
  GET /..%2f..%2fdata%2fREADME.md    -> 200                (URL-encoded variant)
  GET /%2e%2e/%2e%2e/requirements.txt-> 200
  GET /../../../../../../etc/hostname-> 200 text/plain     "megatron"
  GET /../../.git/config             -> 200                (remote URL disclosed)
  GET /../../data/app.db  (Range 0-15)-> 206  "SQLite format 3\0"
  ```
  No session cookie was sent. The `/assets` mount uses Starlette `StaticFiles`, which does its own containment check and correctly returned 404 for `/assets/../../../requirements.txt`; only the hand-written `spa()` route is affected.
- **Impact:** Anyone on the internet downloads `data/app.db` (177 MB, works with Range requests) and obtains: `settings` rows with `anthropic_api_key`, `postmark_server_token`, `smtp_password` in plaintext (see F-02); every user's email, name and argon2 hash; SHA-256 of live session tokens; all notes, pins and chat transcripts. Also readable: source code, `.git/`, and anything the service account can read (`/etc/passwd`, private keys if present). If the service is fronted by nginx, nginx normalises `..` in `$uri` before proxying, which would mask most probes, but the app must not depend on that: any direct access to port 8765 (current LAN mode), a misconfigured `proxy_pass` with `$request_uri`, or an alternative encoding nginx does not normalise reopens the hole.
- **Fix (must do before public exposure):**
  ```python
  WEB_DIST_RESOLVED = WEB_DIST.resolve()

  @app.get("/{full_path:path}", include_in_schema=False)
  def spa(full_path: str):
      if full_path:
          try:
              candidate = (WEB_DIST_RESOLVED / full_path).resolve(strict=True)
          except (OSError, RuntimeError):
              candidate = None
          if candidate and candidate.is_file() and candidate.is_relative_to(WEB_DIST_RESOLVED):
              return FileResponse(candidate)
      return FileResponse(WEB_DIST_RESOLVED / "index.html", headers={...})
  ```
  Alternatively serve `web/dist` from nginx (`try_files $uri /index.html`) and have FastAPI only own `/api`. Add a regression test that requests `/../../requirements.txt` with a raw ASGI scope and expects `index.html`. Then **rotate the Anthropic key, Postmark token and SMTP password** and invalidate all sessions (`DELETE FROM sessions`): the LAN instance has been running with this bug, so treat the current secrets as exposed.

### HIGH

#### F-02 — Third-party secrets stored in plaintext in SQLite and returned partially unmasked

- **Location:** `server/config.py:46` (`SECRET_SETTINGS`), `server/settings.py:25-37` (`set_settings` writes raw values), `server/settings.py:40-45` (`mask` reveals last 4 characters)
- **OWASP:** A02:2021 Cryptographic Failures; ASVS 2.10.4 / 6.4.1
- **Evidence:** `set_settings` stores `anthropic_api_key`, `smtp_password` and `postmark_server_token` as-is in the `settings` table of the same file that holds user data. There is no encryption, no separate file, and no file-permission hardening. `mask()` returns `••••••••` plus the last four characters to admins.
- **Impact:** Any read of the database file (F-01, a backup copy, a stolen droplet snapshot, a misconfigured `LP_DATA_DIR` permission) yields live billing credentials. The Anthropic key can be used to run up charges; the Postmark token sends mail as the verified sender.
- **Fix:** Preferred: take these three values from environment variables (`LP_ANTHROPIC_API_KEY`, `LP_POSTMARK_TOKEN`, `LP_SMTP_PASSWORD`) loaded by systemd with `EnvironmentFile=` (mode 0600) and make the Settings page display "set via environment". If they must stay editable in the UI, encrypt them at rest with a key from the environment (e.g. `cryptography.fernet.Fernet`) before writing to `settings`, decrypt in `get_settings`. Either way: `chmod 700` the data directory, keep it outside the clone (`LP_DATA_DIR`), exclude it from any web-readable path, and drop the last-4 reveal in `mask()` (return only `_set: true`).

#### F-03 — Authenticated users can send arbitrary HTML email from the server's verified sender to any address (unsanitised Markdown in `render_export`)

- **Location:** `server/routers/lessons.py:92-105` (`email_lesson`), `server/routers/lessons.py:281-282` (`render_export`), `server/routers/lessons.py:84-89` (`export_html`), `server/mailer.py:64-68`
- **OWASP:** A03:2021 Injection (stored XSS, CWE-79) and A04:2021 Insecure Design (mail relay abuse); ASVS 5.3.3
- **Evidence:** Notes are rendered with Python-Markdown and no sanitiser:
  ```python
  notes_html = markdown.markdown(lesson["notes_md"] or "", extensions=["extra", "sane_lists"])
  ```
  Confirmed locally: `markdown.markdown('<img src=x onerror=alert(1)> <script>alert(1)</script> [x](javascript:alert(1))')` returns the tags and `javascript:` href untouched. `email_lesson` accepts any list of up to 20 recipients (validated only by `EMAIL_RE`) and an arbitrary `subject`, with no per-user rate limit, and mails that HTML via Postmark or SMTP. `export_html` serves the same HTML as `text/html` on the API origin (`HTMLResponse`) with the session cookie present.
- **Impact:** Any invited user (or anyone holding a stolen session) can use the deployment as an outbound phishing/spam relay: a fully attacker-controlled HTML body and subject, sent from the church group's verified Postmark domain, to arbitrary recipients, 20 per request with no throttle. This burns sender reputation and Postmark quota and can get the domain blacklisted. The `export.html` side is self-XSS today (each user only renders their own notes) but becomes real stored XSS the moment any sharing or admin-view feature is added, and there is no CSP to contain it (F-04). Header injection via `subject` is **not** possible: Python's `EmailMessage` rejects CR/LF in headers (verified), and Postmark takes JSON.
- **Fix:**
  1. Sanitise the rendered notes with an allowlist before embedding: `nh3.clean(notes_html)` (Rust-backed, MIT) or `bleach`; strip `javascript:` URLs.
  2. Constrain recipients: default to the sender's own address; if sending to others is a real need, limit to registered users' addresses or require admin, and add `rate_limit(f"email:{uid}", limit=10, window_s=3600)`.
  3. Serve `export.html` with `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src https:` and `X-Content-Type-Options: nosniff`.

### MEDIUM

#### F-04 — No security response headers

- **Location:** `server/main.py` (no middleware); verified response to `GET /` contains only `date, server, cache-control, content-type, accept-ranges, content-length, last-modified, etag`.
- **OWASP:** A05:2021 Security Misconfiguration; ASVS 14.4.x
- **Impact:** No `Content-Security-Policy` (would blunt F-03 and any future XSS), no `X-Frame-Options`/`frame-ancestors` (clickjacking of the admin Settings/Users pages), no `X-Content-Type-Options`, no `Referrer-Policy`, no `Strict-Transport-Security`, and the `server: uvicorn` banner is advertised.
- **Fix:** Add either a small Starlette middleware or nginx `add_header` lines:
  ```
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' https://img.youtube.com data:; frame-src https://www.youtube-nocookie.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Strict-Transport-Security: max-age=31536000; includeSubDomains   (HTTPS only)
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  ```
  Run uvicorn with `--no-server-header`. Note the landing page loads Google Fonts (`web/index.html:9-14`) and the YouTube poster/iframe, so the CSP must allow those hosts (or self-host the fonts).

#### F-05 — Rate limiting is keyed on client IP in a way that fails behind a proxy and is bypassable when the proxy is trusted

- **Location:** `server/auth.py:167-186` (`_buckets`, `client_ip`, `rate_limit`); callers `server/routers/auth.py:36,57,69`
- **OWASP:** A07:2021 Identification and Authentication Failures; ASVS 2.2.1
- **Evidence:** Verified 11 bad logins from one IP → ten 401s then a 429, so the limiter works as coded. But:
  - Without `LP_TRUST_PROXY`, every request behind nginx arrives from 127.0.0.1, so **ten failed logins by anyone lock the login endpoint for all users for ten minutes** (trivial denial of service), and `forgot` is capped at five per hour for the whole site.
  - With `LP_TRUST_PROXY=1`, `client_ip` takes the **leftmost** `X-Forwarded-For` entry (`fwd.split(",")[0]`). nginx's usual `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for` appends the real address to whatever the client sent, so an attacker supplies a fresh random `X-Forwarded-For` per request and never hits the limit.
  - There is no per-account throttle, so a distributed attacker gets 10 guesses per IP per 10 minutes against any account indefinitely.
  - `_buckets` is a `defaultdict` that is never pruned; each distinct key costs memory forever.
- **Fix:** Have nginx set `proxy_set_header X-Real-IP $remote_addr` and read that (or take the **rightmost** untrusted hop of XFF). Add a second bucket keyed by `lower(email)` (e.g. 5 per 15 minutes) so an account is protected regardless of source IP. Delete a bucket when its deque empties. Consider `slowapi` or nginx `limit_req` on `/api/auth/` as a belt-and-braces layer.

#### F-06 — Security-critical behaviour depends on optional environment variables and fails open

- **Location:** `server/config.py:49-52`, `server/auth.py:284-285` (`secure=COOKIE_SECURE`), `server/routers/auth.py:86-105` (`base_url`)
- **OWASP:** A05:2021 Security Misconfiguration; ASVS 3.4.1, 14.1.x
- **Evidence:** `COOKIE_SECURE` defaults to off, so on a public HTTPS deployment where the operator forgets `LP_COOKIE_SECURE=1` the session cookie is sent over plain HTTP. `base_url()` refuses to derive the origin from headers only when `COOKIE_SECURE` is set; if the operator sets `LP_TRUST_PROXY=1` (needed for F-05) but not `LP_BASE_URL`, the reset/invite link is built from `X-Forwarded-Proto`/`X-Forwarded-Host`, which nginx typically populates from the client's `Host`/`X-Forwarded-Host` headers. An attacker who requests a password reset for a victim with `Host: attacker.example` then receives the victim's token when they click the emailed link (the exact attack the docstring describes). The README (line 89) lists all four variables as optional.
- **Fix:** Fail closed at startup: if `LP_TRUST_PROXY` or `LP_COOKIE_SECURE` is set, require `LP_BASE_URL`; derive `COOKIE_SECURE = BASE_URL.startswith("https://")` instead of a separate flag; never read `X-Forwarded-Host` in `base_url` (always return `BASE_URL` when configured, else the socket address). Prefix the cookie name with `__Host-` when secure. Ship the deploy files (systemd unit / nginx config) with these values set so the safe configuration is the default one.

#### F-07 — Any authenticated user can spend unlimited paid AI and email quota

- **Location:** `server/routers/chat.py:57-131`, `server/routers/digest.py:21-27`, `server/routers/lessons.py:92-105`; `server/ai/anthropic_provider.py:19-20` (`MAX_TOOL_ROUNDS = 8`, `MAX_TOKENS = 16000`)
- **OWASP:** A04:2021 Insecure Design (unrestricted resource consumption; API4:2023)
- **Evidence:** No per-user or global quota, counter or logging exists for chat, digest generation (any user may regenerate the shared digest for any talk) or email. A single chat turn can be up to 9 model calls with a cached ~10k-token system prompt each.
- **Impact:** A careless or compromised account (or a session stolen via F-01) can run up the Anthropic bill and exhaust Postmark credits; the owner has no visibility until the invoice.
- **Fix:** Add a `usage` table keyed by user/day (the Anthropic provider already emits token counts at `anthropic_provider.py:145-149`), enforce a daily cap per user with a clear 429, and show usage on the admin page. Restrict digest regeneration to admins or to once per talk per day. Set a monthly spend limit in the Anthropic console.

#### F-08 — Vulnerable component: Starlette 1.0.0 (five published advisories)

- **Location:** `requirements.txt:8` (`fastapi>=0.115`, Starlette unpinned); installed `fastapi 0.136.0`, `starlette 1.0.0`
- **OWASP:** A06:2021 Vulnerable and Outdated Components
- **Evidence (`pip-audit`):**

  | Advisory | CVE / GHSA | Fixed in | Applies here? |
  |---|---|---|---|
  | PYSEC-2026-161 | GHSA-86qp-5c8j-p5mr | 1.0.1 | **Partly.** `request.url` is rebuilt from an unvalidated `Host`. `base_url()` reads `request.url.netloc`/`scheme` when `LP_TRUST_PROXY` is set (`auth.py:100-101`). |
  | PYSEC-2026-248 | CVE-2026-54282 | 1.3.0 | Same code path (`request.url` authority confusion); low exploitability. |
  | PYSEC-2026-249 | CVE-2026-54283 | 1.3.1 | Not directly — the app never calls `request.form()`. |
  | PYSEC-2026-2280 | CVE-2026-48817 | 1.1.0 | No — no `HTTPEndpoint` subclasses. |
  | PYSEC-2026-2281 | CVE-2026-48818 | 1.1.0 | No — Windows-only. |

- **Fix:** Pin `starlette>=1.3.1` (FastAPI 0.136 accepts `starlette>=0.46`; FastAPI 0.141.1 is current). Add `pip-audit` to `make test` or a CI step. Consider a lockfile (`pip-compile`) so the droplet installs known versions.

#### F-09 — Password-reset flow can be used to cancel a pending invitation (unauthenticated)

- **Location:** `server/auth.py:147-153` (`issue_invite` deletes all unused invites for the user), `server/routers/auth.py:66-83` (`forgot`)
- **OWASP:** A04:2021 Insecure Design
- **Evidence:** `forgot` for an address that has been invited but has not yet set a password calls `issue_invite(hours=2)`, which first runs `DELETE FROM invites WHERE user_id=? AND used_at IS NULL`. The 72-hour invite the admin sent is destroyed and replaced by a 2-hour one the attacker cannot read.
- **Impact:** Anyone who can guess a pending invitee's address can repeatedly void their invitation (5 per IP per hour). Nuisance-level, but it undermines the invitation UX and, combined with F-05, is cheap to automate.
- **Fix:** In `forgot`, skip users with `password_hash IS NULL` (they have nothing to reset), or store invites and resets with a `kind` column and only supersede the same kind.

### LOW

#### F-10 — Login timing side channel reveals whether an email is registered

- **Location:** `server/routers/auth.py:38`
- **Evidence:** `if not user or user["disabled"] or not verify_password(...)` short-circuits: unknown addresses skip the ~50–100 ms argon2 verification, known ones pay it. The response body is identical, so this is timing-only.
- **Fix:** Verify against a fixed dummy hash when the user is missing or disabled, e.g. `verify_password(body.password, user["password_hash"] if user else _DUMMY_HASH)` and then evaluate the conditions.

#### F-11 — `next` redirect check accepts protocol-relative URLs

- **Location:** `web/src/views/LoginView.vue:27`
- **Evidence:** `route.query.next.startsWith('/')` admits `//evil.example/x`. Today vue-router's catch-all `{ path: '/:pathMatch(.*)*', redirect: '/' }` (`router.ts:19`) swallows it, so no redirect occurs; the guard is one route change away from being an open redirect.
- **Fix:** `/^\/(?!\/)/.test(next)` and prefer `router.replace(router.resolve(next).fullPath)` only when the resolved route is not the catch-all.

#### F-12 — Internal exception text is echoed to users and persisted

- **Location:** `server/routers/chat.py:118-120,122-125` (stores `f"{type(e).__name__}: {e}"` into `chat_messages`), `server/routers/settings.py:72,85,97`, `server/routers/lessons.py:104`, `server/routers/users.py:56`, `server/routers/admin.py:42` (absolute path of `TALKS_JSON`)
- **Evidence:** Exception messages from httpx/smtplib/anthropic are surfaced verbatim. Most are admin-only; the chat path is reachable by any user.
- **Fix:** Map known exception classes to fixed messages, log the original with a request id, return the id to the client.

#### F-13 — Admin-controlled outbound connections (SSRF surface)

- **Location:** `server/routers/settings.py:79-85` (`ollama_base_url` → `httpx.get(f"{base}/api/tags")`), `server/mailer.py:110-120` (`smtp_host`/`smtp_port`), `server/ai/ollama_provider.py:31,49,116`
- **Evidence:** An admin can point the server at any host:port; error strings reveal connect/refused/timeout, giving an internal port scanner and a way to POST JSON to internal services from the droplet.
- **Impact:** Requires admin, who is trusted, so this is a defence-in-depth note; it matters if an admin session is stolen.
- **Fix:** Restrict `ollama_base_url` to `http(s)://` with a hostname allowlist (`localhost`, RFC1918 addresses the owner chooses) or move it to the environment; same for `smtp_host`.

#### F-14 — No security event logging

- **Location:** whole `server/` package — no `logging` import anywhere; `server/routers/auth.py:81-82` swallows send failures with `except Exception: pass`.
- **OWASP:** A09:2021 Security Logging and Monitoring Failures; ASVS 7.1/7.2
- **Impact:** Failed logins, 429s, password resets, invitations, admin role changes and settings writes leave no trace; a brute-force or the F-01 exploitation would be invisible except in nginx access logs. Silent failure in `forgot` also hides mail misconfiguration.
- **Fix:** Add a `logging.getLogger("lp.security")` and emit one structured line (event, user id or email hash, client IP, outcome) for: login success/failure, 429, set-password, forgot, invite issued, user patched, settings written, index rebuild. Log `forgot` send failures at WARNING. Ship logs via journald; consider fail2ban on the login failure line.

#### F-15 — Rate-limit state is process-local and unbounded

- **Location:** `server/auth.py:167`
- **Evidence:** `_buckets = defaultdict(deque)`; keys are never removed. With `--workers > 1` each worker has its own counters (limits multiply).
- **Fix:** Prune empty deques in `rate_limit`; run a single worker (fine for this load) or move counters to SQLite/nginx `limit_req`.

### INFORMATIONAL

- **I-01 `/api/health` is unauthenticated** (`server/main.py:47-56`) and reveals `has_users`, `built_at`, `semantic`. Harmless, but `has_users` tells an attacker whether the first-admin bootstrap has happened. Consider returning only `{"ok": true}` to anonymous callers.
- **I-02 CORS allows the Vite dev origins in production** (`server/main.py:35-40`). `allow_credentials` is not set, so cookies are never sent cross-origin and this is not exploitable; gate it on an env flag anyway so production has no CORS at all.
- **I-03 Sessions slide indefinitely** (`server/auth.py:137-141`): a 30-day cookie that is used weekly never expires and there is no absolute lifetime or "sign out everywhere" (except on password set). ASVS L1 does not require it; consider a 90-day absolute cap and a session list in the UI.
- **I-04 Password policy**: minimum 10, maximum 200, no composition rules (good, per NIST). No breached-password check (ASVS 2.1.7, L1). Optional: k-anonymity check against the Pwned Passwords API at set-password time.
- **I-05 Digests are a shared, unauthenticated-to-overwrite cache**: `digests` is keyed by `talk_id` only; any user can regenerate (overwrite) the digest all users see (`digest.py:21`). By design, and the content is derived only from the talk text (no user notes enter any AI prompt — verified in `ai/prompts.py:22-34` and `ai/digest.py:78-81`), so no cross-user data leak. Noted for F-07 cost reasons.
- **I-06 Frontend third-party loads**: Google Fonts (`web/index.html:9-14`) and YouTube thumbnails/iframe (`LandingView.vue:41-53`) are the only external resources; the iframe is `youtube-nocookie`, click-to-load, with `referrerpolicy` set. Fine; must be reflected in the CSP (F-04). Self-hosting the two font families removes the Google dependency and a privacy leak of visitor IPs.

---

## OWASP Top 10 (2021) coverage

| Category | Status | Findings / notes |
|---|---|---|
| A01 Broken Access Control | **Fail** | F-01 (unauthenticated file read). Otherwise strong: every data route depends on `get_user`, all queries filter by `user_id`, admin routes use `get_admin`, IDOR checks on pins/chats/sessions verified (`lessons.py:112,120,134`, `chat.py:69-72,144,155`), `test_scoping_between_users` covers it. |
| A02 Cryptographic Failures | Partial | F-02 (secrets plaintext at rest), F-06 (`Secure` cookie flag optional). Good: argon2id, SHA-256 hashed tokens, `secrets.token_urlsafe(32)`. |
| A03 Injection | Partial | F-03 (unsanitised Markdown → HTML in export/email). SQL: all `conn.execute` calls parameterised; f-strings only build `?` placeholder lists and constant table names (`talks.py:43-44`, `search.py:90`, `db.py:242`). FTS5: `fts_query` quotes every term (`search.py:55-69`). No `subprocess`/`eval`/`os.system` anywhere. SMTP header injection blocked by stdlib (verified). |
| A04 Insecure Design | Partial | F-07 (no quotas), F-09 (reset cancels invite), F-03 recipient model. |
| A05 Security Misconfiguration | **Fail** | F-04 (no headers), F-06 (fail-open env flags), I-02 (dev CORS in prod), `server: uvicorn` banner. |
| A06 Vulnerable Components | Partial | F-08 (Starlette 1.0.0). npm audit: 0 findings. |
| A07 Identification & Authentication | Partial | F-05 (rate limiting), F-10 (timing enumeration), I-03. Good: hashed single-use expiring tokens, sessions revoked on disable/password set, `forgot` always 200, invites admin-only. |
| A08 Software & Data Integrity | Pass | No deserialisation of untrusted data (`json.loads` only on own DB rows and provider responses); no CI/CD pipeline present; `np.load` reads a locally generated file. Recommend a lockfile (F-08). |
| A09 Logging & Monitoring | **Fail** | F-14. |
| A10 SSRF | Partial | F-13 (admin-controlled Ollama/SMTP hosts). No user-supplied URLs are fetched; Postmark URL is a constant (`config.py:55`). |

CSRF (ASVS 4.2.2): adequate. The session cookie is `SameSite=Lax`, all state-changing endpoints are `POST/PUT/PATCH/DELETE` with JSON bodies (a cross-origin form post cannot produce `application/json`), `allow_credentials` is off, and no `GET` has side effects. No separate CSRF token is needed while these three properties hold; add a test that asserts them.

---

## Dependency audit

### Python (`requirements.txt`, installed versions)

| Package | Installed | Result |
|---|---|---|
| fastapi | 0.136.0 | no advisory (0.141.1 available) |
| **starlette** | **1.0.0** | **5 advisories — see F-08; upgrade to ≥1.3.1** |
| uvicorn | 0.42.0 | clean |
| anthropic | 0.112.0 | clean |
| httpx | 0.28.1 | clean |
| markdown | 3.10.2 | clean (but unsanitised by design — F-03) |
| argon2-cffi | 23.1.0 | clean |
| pydantic | 2.12.5 | clean |
| python-multipart | 0.0.22 | clean (unused by the app; can be dropped) |
| requests / beautifulsoup4 / lxml | 2.33.1 / — / — | scraper only; clean |
| numpy / sentence-transformers / torch | 2.4.4 / 6.0.1 / 2.14.0+cpu | clean (torch not auditable from the CPU index) |

`pip-audit` also reported `tornado 6.5.7` and `weasyprint 68.1`; these are system-site packages on the workstation, not imported by this project, and will not exist in the droplet's venv. Use a virtualenv on the server so the audit surface is only the app's own dependencies.

Licences: all Python and npm dependencies are MIT/BSD/Apache-2.0 (torch BSD-3, sentence-transformers Apache-2.0, argon2-cffi MIT, dompurify Apache-2.0/MPL-2.0 dual, marked MIT). No copyleft obligations. The scripture data source (`beandog/lds-scriptures`, `config.py:17-19`) is public-domain text under a permissive repository licence; talk text is scraped from churchofjesuschrist.org and is subject to that site's terms — a content-licensing question rather than a code one, but worth confirming before public hosting.

### npm (`web/package.json`)

`npm audit`: 0 vulnerabilities (0 info/low/moderate/high/critical). Installed: vue 3.5.42, vue-router 4.6.4, pinia 4.0.3, dompurify 3.4.15, marked 18.0.11, vite 8.2.2.

---

## What is done well (keep these)

- **Password storage:** argon2id via `argon2-cffi` defaults (`auth.py:24,42-45`), 10-character minimum enforced server-side, hash never leaves the server (`user_to_dict` exposes only `has_password`).
- **Sessions:** 256-bit random token, only its SHA-256 stored (`auth.py:104-112`), `HttpOnly`, `SameSite=Lax`, `path=/`; server-side revocation on logout, on disable (`users.py:93-94`) and on password set (`auth.py:60`); disabled users rejected on every request (`auth.py:133-136`).
- **Invite / reset tokens:** 256-bit, hashed at rest, single-use (`used_at`), expiring (72 h / 2 h), superseded on reissue; `forgot` always returns 200 and is rate-limited; the reset link origin is never taken from `Host` on the default configuration (`auth.py:103-105`).
- **Authorization model:** `Depends(get_user)` on every non-public route, `Depends(get_admin)` on users/settings/index/digest-delete; ownership enforced in SQL `WHERE ... AND user_id=?` rather than after the fact; covered by `tests/test_auth.py`.
- **SQL:** 100 % parameterised; FTS5 input neutralised by quoting; `LIKE` patterns parameterised.
- **Frontend XSS hygiene:** every `v-html` goes through DOMPurify (`utils/markdown.ts`); search snippets allow only `<mark>`; AI output is Markdown-rendered then sanitised, and citation buttons carry only escaped `data-*` attributes handled in JS (`ChatPanel.vue:70-77`); `landing.md` is a build-time asset, not user input.
- **Secrets in transit to the UI:** masked on read, masked echoes ignored on write (`settings.py:55-58`); `ai-status` exposes no secret to non-admins.
- **Input bounds:** pydantic `Field(max_length=...)` on notes, pins, chat, email, login bodies; `limit` parameters capped.
- **Email:** recipient regex validation; Postmark via JSON; stdlib `EmailMessage` blocks header injection; STARTTLS/SSL with `ssl.create_default_context()`.
- **Repository hygiene:** no secrets in any of the 17 commits; `data/`, `web/dist/`, `.env`-style files ignored; default bind is `127.0.0.1`.
- **Tests:** 38 passing, including invite flow, scoping between users, admin gating, disabled-user login.

---

## Recommended order of remediation

1. **F-01** — fix `spa()` containment (or move static serving to nginx); add the regression test. *Same day.*
2. **Rotate** the Anthropic key, Postmark token and SMTP password; `DELETE FROM sessions`. *Same day, after 1.*
3. **F-02** — move secrets to environment / encrypt at rest; `chmod 700` the data dir; drop the last-4 reveal.
4. **F-06 + F-05** — write the deploy files now (systemd unit with `EnvironmentFile`, nginx site) so `LP_BASE_URL`, HTTPS-derived `Secure`, `X-Real-IP` and `limit_req` on `/api/auth/` are the defaults; make the app refuse to start half-configured; fix XFF handling and add per-account throttling.
5. **F-04** — security headers (nginx `add_header` or middleware) including CSP; `--no-server-header`.
6. **F-03** — sanitise notes HTML in `render_export`; restrict email recipients and rate-limit sending.
7. **F-08** — `starlette>=1.3.1`, `fastapi>=0.141`; add `pip-audit` to `make test`; introduce a lockfile.
8. **F-14** — security logging for auth events; stop swallowing `forgot` send errors.
9. **F-07** — per-user AI/email quotas and a usage view; spend cap in the Anthropic console.
10. **F-09, F-10, F-11, F-12, F-13, F-15** and the informational items as routine hardening.

Items 1–5 are the gate for making the droplet reachable from the internet; 6–8 should land in the first week of public operation; the rest can follow.
