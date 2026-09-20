# Follow-ups and status

Dated status that git does not already record. Update or delete lines as they resolve.

## As of 2026-09-20

**Digest feature:** committed 2026-09-15 (87db893) after a real end-to-end run with Sonnet 5 on 2026-09-11 (31 tests green). Working tree clean as of 2026-09-20.

**Commit authorship:** all three commits were rewritten on 2026-09-15 to the global `uri@uacconsulting.com`
(new SHAs 5f153a0, 6469c9c, 862e4e6); the mistaken repo-local ArbiterSports identity is gone.

**Server:** running on 2026-09-20, bound to 0.0.0.0:8765; the machine's LAN address changes (192.168.1.24 on 2026-09-07, 192.168.1.52 on 2026-09-19) — read it with `ip -4 addr show wlo1` rather than quoting an old one. Started by hand with `python3 -m server.cli serve --host 0.0.0.0 --port 8765` (nohup). It does
not survive a reboot; a systemd user unit was offered but not built.

**No git remote** is configured; nothing has ever been pushed.

## Endnotes are now scraped separately (partial data until the re-scrape lands)

Fixed 2026-09-20: `scrape_conference_talks.py` now pulls `<footer class="notes">` into a `notes` list per talk
(`{n, text}`) and records footnote-marker positions per body paragraph (`note_refs`); the indexer stores
`marker` / `note_refs` on `paragraphs` and only falls back to the `mark_notes` heuristic for talks scraped
with the old extractor; the reader renders clickable superscript markers that jump to the numbered note.
`--refresh YYYY/MM` re-scrapes chosen conferences in place.

**Only April 2026 has been refreshed so far.** A full re-scrape with the new extractor was started on
2026-09-20 writing `general_conference_talks.new.json` (log in the session scratchpad, ~2.5 h at 1 req/s).
When it finishes: verify talk count (4,267) and that every talk has a `notes` key, move it to
`data/general_conference_talks.json`, run `python -m server.cli index`, restart the server. Until then, older
talks still show heuristically-detected notes without markers.

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
