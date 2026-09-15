# Follow-ups and status

Dated status that git does not already record. Update or delete lines as they resolve.

## As of 2026-09-15

**Digest feature:** committed 2026-09-15 after a real end-to-end run with Sonnet 5 on 2026-09-11 (31 tests green).

**Commit authorship:** all three commits were rewritten on 2026-09-15 to the global `uri@uacconsulting.com`
(new SHAs 5f153a0, 6469c9c, 862e4e6); the mistaken repo-local ArbiterSports identity is gone.

**Server:** started by hand with `python3 -m server.cli serve --host 0.0.0.0 --port 8765` (nohup). It does
not survive a reboot; a systemd user unit was offered but not built.

**No git remote** is configured; nothing has ever been pushed.

## Next: improve the pinning system

Where pins live today, for whoever picks this up:

- Schema: `pins` table in `server/db.py` (`kind` is `talk | scripture | quote | note`; `ref_talk_id`,
  `ref_paragraph_id`, `scripture_ref`, `text`, `note`, `ord`). API in `server/routers/lessons.py`
  (`add_pin`, `patch_pin`, `delete_pin`, `reorder_pins`; `render_export` builds the print/email HTML).
- Client store: `web/src/stores/lesson.ts` (`addPin`, `hasPin`, `patchPin`, `removePin`, `reorder`).
- Pin creators: `TalkListItem.vue` (talk), `TalkDrawer.vue` (talk), `ScripturePanel.vue`,
  `ScripturesSection.vue`, `ResearchColumn.vue` (scripture), `TalkReader.vue` (selected text → quote),
  `ChatPanel.vue` ("Pin this answer" → note), `DigestPane.vue` (quote with `why` as note; question → note).
- Display: `NotesColumn.vue` (right column; up/down reorder, inline note edit, Print, Email…).

Known rough edges: `hasPin` only de-duplicates talk and scripture pins, so the same quote or question can be
pinned twice; note pins carry the digest's context only in the free-text `note`; pins have no grouping or
tagging; reorder is button-based, not drag.
