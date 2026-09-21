# Follow-ups and status

Dated status that git does not already record. Update or delete lines as they resolve.

## As of 2026-09-21 (evening)

**Digest feature:** committed 2026-09-15 (87db893) after a real end-to-end run with Sonnet 5 on 2026-09-11 (31 tests green). Working tree clean as of 2026-09-20.

**Commit authorship:** all three commits were rewritten on 2026-09-15 to the global `uri@uacconsulting.com`
(new SHAs 5f153a0, 6469c9c, 862e4e6); the mistaken repo-local ArbiterSports identity is gone.

**Server:** running on 2026-09-20, bound to 0.0.0.0:8765; the machine's LAN address changes (192.168.1.24 on 2026-09-07, 192.168.1.52 on 2026-09-19) — read it with `ip -4 addr show wlo1` rather than quoting an old one. Started by hand with `python3 -m server.cli serve --host 0.0.0.0 --port 8765` (nohup). It does
not survive a reboot; a systemd user unit was offered but not built.

**No git remote** is configured; nothing has ever been pushed.

## Endnotes scraped separately (done)

The scraper (since 0317794) stores endnotes per talk (`notes`) with in-text marker positions (`note_refs`);
the indexer stores `marker`/`note_refs` on `paragraphs`; the reader shows clickable superscript markers.

The full re-scrape finished 2026-09-20: 4,267 talks, all with a `notes` key, 26,312 endnotes, same talk URLs
as before. Swapped into `data/general_conference_talks.json`, index rebuilt (42 s, 519 chunks re-embedded,
built_at 2026-09-20T17:21:35) and server restarted the same evening; older talks now show numbered notes
(e.g. 2025-10/32dennis has 35 marked notes). Nothing pending here.

## Multi-user + hosting (plan approved 2026-09-21; sections 1–3 done, 4–6 not started)

Done 2026-09-21, all committed and pushed to github.com/urielc/talkPrepper (`main`, last commit 315ff61):
accounts, sessions, invites, per-user notes/pins/chats/My lessons, admin Settings/Users pages, landing page
redesign (hero + Handbook panel, menu bar with one "Lesson prep" link to `/lessons`, three counsel columns,
sources), `/lessons` page (your lessons + talk picker). The admin `uri@uacconsulting.com` has set a password
and can sign in. Email is **not** configured (from-address missing), so invites hand the admin a link.

Content files: `web/src/content/hero.json` (hero + Handbook panel), `web/src/content/landing.md` (columns
split on `## ` headings; "Sources" renders beneath), `web/src/content/videos.json` (see the YouTube note
below).

Not done from the plan: section 4 (`make ship-index`), 5 (deploy files: `deploy/nginx.conf`,
`deploy/lessonprep.service`, `deploy/README.md`, `.github/workflows/deploy.yml`), 6 (droplet step 0).

## Next (Uri, 2026-09-21): settings page changes

Uri will describe the settings changes. Settings page is
`web/src/views/SettingsView.vue` (~300 lines: AI provider, email, talk index, appearance sections;
admin-only; backed by `server/routers/settings.py` with `SETTINGS_DEFAULTS` in `server/config.py`).

**YouTube link done 2026-09-21:** `videos.json` holds Elder Bednar's "Technology Cannot Replace the
Divine" (2EY65ZrznJ0). Entries are `{title, speaker, url, blurb?}`. The first entry is featured on the
landing page as a click-to-play `youtube-nocookie` embed beside its title, speaker and blurb; further
entries, if added, fall into the old thumbnail grid beneath. Rebuild with `cd web && npm run build`.

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
