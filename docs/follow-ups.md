# Follow-ups and status

Dated status that git does not already record. Update or delete lines as they resolve.

## As of 2026-09-21

**Digest feature:** committed 2026-09-15 (87db893) after a real end-to-end run with Sonnet 5 on 2026-09-11 (31 tests green). Working tree clean as of 2026-09-20.

**Commit authorship:** all three commits were rewritten on 2026-09-15 to the global `uri@uacconsulting.com`
(new SHAs 5f153a0, 6469c9c, 862e4e6); the mistaken repo-local ArbiterSports identity is gone.

**Server:** running on 2026-09-20, bound to 0.0.0.0:8765; the machine's LAN address changes (192.168.1.24 on 2026-09-07, 192.168.1.52 on 2026-09-19) — read it with `ip -4 addr show wlo1` rather than quoting an old one. Started by hand with `python3 -m server.cli serve --host 0.0.0.0 --port 8765` (nohup). It does
not survive a reboot; a systemd user unit was offered but not built.

**No git remote** is configured; nothing has ever been pushed.

## Endnotes scraped separately — full data swap in progress

The scraper (since 0317794) stores endnotes per talk (`notes`) with in-text marker positions (`note_refs`);
the indexer stores `marker`/`note_refs` on `paragraphs`; the reader shows clickable superscript markers.

The full re-scrape finished 2026-09-20: 4,267 talks, all with a `notes` key, 26,312 endnotes, same talk URLs
as before. Swapped into `data/general_conference_talks.json`, index rebuilt (42 s, 519 chunks re-embedded,
built_at 2026-09-20T17:21:35) and server restarted the same evening; older talks now show numbered notes
(e.g. 2025-10/32dennis has 35 marked notes). Nothing pending here.

## Multi-user + hosting (plan approved 2026-09-21; sections 1–3 built the same day)

Done locally on 2026-09-21: users/sessions/invites/working_on tables; argon2 passwords; cookie sessions;
per-user notes, pins, chats and "My lessons" (replaces the single current talk); admin-only Settings/Users/
index; invite + set-password + forgot-password flows; landing page with the preparation statement
(`web/src/content/landing.md`), a Church-leaders video row (`web/src/content/videos.json`, empty until Uri
adds `{title, speaker, url}` entries), My lessons and the talk picker. The LAN database was migrated; Uri's
data belongs to the admin account `uri@uacconsulting.com`, which still needs its password set from the
invite link printed on 2026-09-21 (valid 72 h; regenerate with `python -m server.cli migrate` + Users page,
or `issue_invite`).

Not yet done from the plan: section 4 (ship-index), 5 (deploy files: `deploy/nginx.conf`,
`deploy/lessonprep.service`, `deploy/README.md`, `.github/workflows/deploy.yml`), 6 (droplet step 0), the
GitHub remote under `UrielC`, and the earlier UI task below. Email invites use the Postmark settings already
in the DB; tested only with email unconfigured (link handed to admin) — a real invite email has not been sent.

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
