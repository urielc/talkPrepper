# Follow-ups and status

Dated status that git does not already record. Update or delete lines as they resolve.

## As of 2026-09-21 (night)

**Digest feature:** committed 2026-09-15 (87db893) after a real end-to-end run with Sonnet 5 on 2026-09-11 (31 tests green). Working tree clean as of 2026-09-20.

**Commit authorship:** all three commits were rewritten on 2026-09-15 to the global `uri@uacconsulting.com`
(new SHAs 5f153a0, 6469c9c, 862e4e6); the mistaken repo-local ArbiterSports identity is gone.

**Server:** restarted 2026-09-21 (midday) on the hardened code (commit 2106939), bound to 0.0.0.0:8765, log in `data/server.log`; the machine's LAN address changes (192.168.1.24 on 2026-09-07, 192.168.1.52 on 2026-09-19) — read it with `ip -4 addr show wlo1` rather than quoting an old one. Started by hand with `python3 -m server.cli serve --host 0.0.0.0 --port 8765` (nohup). It does
not survive a reboot; a systemd user unit was offered but not built.

**No git remote** is configured; nothing has ever been pushed.

## Endnotes scraped separately (done)

The scraper (since 0317794) stores endnotes per talk (`notes`) with in-text marker positions (`note_refs`);
the indexer stores `marker`/`note_refs` on `paragraphs`; the reader shows clickable superscript markers.

The full re-scrape finished 2026-09-20: 4,267 talks, all with a `notes` key, 26,312 endnotes, same talk URLs
as before. Swapped into `data/general_conference_talks.json`, index rebuilt (42 s, 519 chunks re-embedded,
built_at 2026-09-20T17:21:35) and server restarted the same evening; older talks now show numbered notes
(e.g. 2025-10/32dennis has 35 marked notes). Nothing pending here.

## Multi-user + hosting (plan approved 2026-09-21; done, see Production)

Done 2026-09-21, all committed and pushed to github.com/urielc/talkPrepper (`main`, last commit 315ff61):
accounts, sessions, invites, per-user notes/pins/chats/My lessons, admin Settings/Users pages, landing page
redesign (hero + Handbook panel, menu bar with one "Lesson prep" link to `/lessons`, three counsel columns,
sources), `/lessons` page (your lessons + talk picker). The admin `uri@uacconsulting.com` has set a password
and can sign in. Email is **not** configured (from-address missing), so invites hand the admin a link.

Content files: `web/src/content/hero.json` (hero + Handbook panel), `web/src/content/landing.md` (columns
split on `## ` headings; "Sources" renders beneath), `web/src/content/videos.json` (see the YouTube note
below).

Section 4 (`make ship-index`) was dropped: the index is copied with `data/` instead. Sections 5–6 landed
2026-09-21 evening (deploy files, workflow, droplet), see Production.

## Next (Uri, 2026-09-21 night): change the LLM model, redo the landing page

1. **LLM model.** Today the Settings page (admin) picks `anthropic_model`; default `claude-opus-5` in
   `server/config.py`, and Uri's stored choice was `claude-sonnet-5`. Uri will say which model; change the
   default and/or the stored setting (production and LAN databases are separate copies).
2. **Landing page** (`web/src/views/LandingView.vue`, content in `web/src/content/{hero.json,landing.md,videos.json}`):
   move the featured video up (today it sits under the three counsel columns), and turn the three
   columns ("What this tool is for", "What it is not for", "What Church leaders have said", split from
   `landing.md` on `## ` headings) into a collapsible list to the right of the video, so little remains
   below the fold. "Sources" stays beneath. Hazards: the CSP blocks inline scripts (see the screenshot
   recipe in memory); `landing.md` is a build-time asset rendered with `v-html` via the sanitised
   `renderMarkdown`; the video poster/iframe hosts are whitelisted in `server/middleware.py` CSP.
   Rebuild with `cd web && npm run build`; production gets it via the pipeline (once the CI key is
   authorised) or a manual pull + `rsync web/dist/`.

## Production (deployed 2026-09-21 evening)

**https://lessonprep.chinstrapsoftware.com**, on a small shared droplet (Ubuntu 24.04, nginx 1.24, 2 GB
RAM) alongside other sites. Access details live in Uri's private notes, not in this public repo.

- Layout follows `deploy/README.md`: code in `/opt/lessonprep` (git clone, service user `lessonprep`,
  venv, CPU torch), data in `/var/lib/lessonprep` (copy of the LAN `data/` taken 2026-09-21, same Fernet
  `secret.key`, bge-small model pre-seeded in `hf-cache/`), unit `lessonprep.service`, vhost per
  `deploy/nginx.conf`, certificate via `certbot certonly --nginx`.
- Production runs commit 37a1821 (deployed by hand 2026-09-21 night). Verified over HTTPS: redirect, HSTS,
  CSP, traversal blocked, per-account 429 then nginx 503 on `/api/auth/`, SSE proxying unbuffered.
- **CD not yet active:** `.github/workflows/deploy.yml` has its secrets/variables set, the test job passes,
  but the deploy job fails at SSH because the CI public key is not authorised on the server. Uri has a
  script for that one-time step (login shell for `lessonprep`, `authorized_keys`, sudoers for
  `systemctl restart lessonprep`). Until then deploy by hand as root: pull as `lessonprep`, rsync
  `web/dist/`, `systemctl restart lessonprep`.
- Email is **not configured** in production; a temporary admin password was set directly in the DB on
  2026-09-21 and Uri was to change it via the new Change password page (`/account`).
- Open from the security review: rotate the Anthropic key exposed before the traversal fix, quotas (F-07),
  SSRF allowlist (F-13), recipient policy for emailed notes, memory footprint once the embedding model loads
  on the droplet (unmeasured).
- The LAN instance on this machine keeps running separately (started 2026-09-21 midday on commit 2106939);
  the two databases diverge from 2026-09-21.

## Still open: related-talks list, tabbed reading, tighter centre margins

Asked by Uri on 2026-09-20:

1. **Related talks collapsible and compact** — show only title, speaker and month/year (no snippets, no
   "shared scriptures" aside). Today `ResearchColumn.vue` wraps `RelatedSection.vue` in `CollapsibleSection`
   (the whole section already collapses); the compaction is inside `RelatedSection.vue`, which passes
   `snippets` and `aside` to `TalkListItem.vue` (props `snippets?`, `aside?`). Conference label already
   carries "April 2026"-style month/year (`talk.conference`).
2. **Open related talks as tabs in the centre top pane** instead of the slide-over drawer. Today
   `TalkListItem` calls `ui.openTalk(id)` (`web/src/stores/ui.ts`, `drawerTalkId`) and `TalkDrawer.vue`
   renders it. Plan: a tab strip above `.reader-pane` in `WorkspaceView.vue` (lesson talk pinned as first
   tab, closable extra tabs, each a `TalkReader`), while `.digest-pane` and the notes/pins column stay bound
   to the lesson talk (`props.talkId`). Keep the drawer for scripture-panel "talks citing" and AI citations,
   or route those to tabs too — Uri didn't say; ask or default to tabs.
3. **Tighter centre margins** — `.reader-pane`/`.digest-pane` padding is `1.75rem 3rem` / `0.75rem 3rem`
   and `--reader-width: 46rem` in `web/src/styles/tokens.css`; side columns are `--research-w: 380px` /
   `--notes-w: 400px`. Reduce centre padding and let the side columns grow (e.g. `minmax(380px, 1fr)`).

## Pins and digest questions

Fixed 2026-09-20: pinning a digest question now carries its teacher note into the pin's `note` field
(`pinQuestion` in `web/src/components/DigestPane.vue`), so the grey explanatory line shows in the Pins
column and in the print/email export. Still open: `hasPin` in `web/src/stores/lesson.ts` only de-duplicates
talk and scripture pins, so a question or quote can be pinned twice; ChatPanel's "Pin this answer" uses a
fixed note of "From AI assistant".

Broader pin map, for later work on the pinning system:

- Schema: `pins` table in `server/db.py` (`kind` is `talk | scripture | quote | note`; `ref_talk_id`,
  `ref_paragraph_id`, `scripture_ref`, `text`, `note`, `ord`). API in `server/routers/lessons.py`
  (`add_pin`, `patch_pin`, `delete_pin`, `reorder_pins`; `render_export` builds the print/email HTML).
- Client store: `web/src/stores/lesson.ts` (`addPin`, `hasPin`, `patchPin`, `removePin`, `reorder`).
- Pin creators: `TalkListItem.vue`, `TalkDrawer.vue` (talk), `ScripturePanel.vue`, `ScripturesSection.vue`,
  `ResearchColumn.vue` (scripture), `TalkReader.vue` (selected text → quote), `ChatPanel.vue` (answer → note),
  `DigestPane.vue` (quote, question → note).
- Display: `NotesColumn.vue` (right column; up/down reorder, inline note edit, Print, Email…).

## Security remediation (2026-09-21)

Implemented the full plan in `docs/security-remediation-plan-2026-09-21.md` for the review in
`docs/security-review-2026-09-21.md`. Fixed: F-01 (path traversal in the SPA catch-all — the one that made
the app unsafe to expose publicly), F-02 (secrets encrypted at rest with Fernet, `LP_SECRET_KEY`), F-03
(export/email notes HTML sanitised with `nh3`, email subject capped, per-user email rate limit, generic
"sending failed" message), F-04 (security headers + CSP middleware, stricter CSP on `export.html`,
`--no-server-header`), F-05 (rate limiting reads `X-Real-IP`/rightmost `X-Forwarded-For` only when
`LP_TRUST_PROXY`, plus a per-account login bucket), F-06 (`LP_BASE_URL` required whenever `LP_TRUST_PROXY`
or `LP_COOKIE_SECURE` is set; `COOKIE_SECURE` follows `https://` in `LP_BASE_URL`; `base_url()` never reads
forwarded headers), F-08 (`fastapi>=0.141`, `starlette>=1.3.1`; `make audit` target for `pip-audit`), F-09
(password reset no longer cancels a pending invite), F-10 (login always runs `verify_password`, against a
dummy hash when there's no real one, to remove the timing side channel), F-11 (`next` redirect regex tightened
against `//evil.example`), F-12/F-14 (`server/log.py`; security events for login, rate limits, invites,
user patches, settings writes, email send/fail; `forgot` no longer swallows send failures silently),
F-15 (rate-limit buckets are pruned/recreated instead of growing forever), I-02 (dev CORS middleware
removed entirely — the Vite dev server already proxies `/api`, so it was unnecessary in every environment).
`deploy/` now has a systemd unit, nginx config and README with these settings as the shipped defaults.

New tests: `tests/test_hardening.py` (regression coverage for all of the above), plus
`tests/conftest.py` (a throwaway `LP_SECRET_KEY` per test run, and a per-test reset of the rate-limit
buckets so tests don't bleed into each other).

Deferred, per the plan's ground rules (Uri's call, not made here):

- **Rotating the exposed secrets.** The review found the LAN instance's Anthropic key, Postmark token and
  SMTP password readable in plaintext via F-01 before this fix; the fix stops new exposure but does not
  invalidate anything already read off the LAN box. Rotate those three, and consider `DELETE FROM
  sessions` to invalidate existing session cookies too.
- **F-07** — no per-user AI/email quota or spend cap yet; any signed-in user can still run up Anthropic/
  Postmark usage.
- **F-13** — `ollama_base_url` and `smtp_host` still accept any host:port from an admin (SSRF surface,
  low severity since it requires an admin session).
- Recipient policy for the "email my notes" feature is unchanged — still any address the user types, up
  to 20 per request (now rate-limited to 10 sends/hour/user).
