# Lesson Prep

A local study and preparation tool for leading elders quorum discussions built on a General Conference talk. It indexes every conference talk since 1971 plus the standard works, and gives you, for the assigned talk:

- the full text with every scripture reference clickable in place,
- related talks (keyword + meaning-based search) and talks that cite the same passages,
- free-text search across all talks and scriptures,
- an AI assistant (Claude API or a local Ollama model) that searches the same index and cites clickable references,
- notes and pinned references per lesson, printable and emailable.

Backend: Python / FastAPI / SQLite (FTS5) / sentence-transformers. Frontend: Vue 3 + Vite.

## Setup

```bash
pip install -r requirements.txt          # CPU torch is fine: pip install --index-url https://download.pytorch.org/whl/cpu torch
cd web && npm install && cd ..

python -m server.cli download-scriptures  # public-domain KJV / Book of Mormon / D&C / PoGP (18 MB)
python -m server.cli index                # builds data/app.db + embeddings (a few minutes on CPU the first time)
```

The index needs `data/general_conference_talks.json`, produced by the scraper (see below).

## Run

Development (API with reload on :8765, Vite on :5173):

```bash
./dev.sh            # or: make dev
```

Single process (serves the built web app and the API on :8765):

```bash
make serve          # runs `npm run build` then `python -m server.cli serve`
```

To use it from a phone or another computer on the same network:

```bash
make serve-lan      # binds 0.0.0.0:8765; open http://<this machine's IP>:8765 on the other device
```

The firewall must allow TCP 8765 (Fedora's default workstation zone already allows 1025–65535; otherwise `sudo firewall-cmd --add-port=8765/tcp --permanent && sudo firewall-cmd --reload`).

## Accounts

Everything except the health endpoint requires a signed-in user. Accounts are invitation-only:

```bash
python -m server.cli migrate --admin-email you@example.com --name "Your Name"   # first admin; prints a set-password link
```

Admins invite others from **Users** in the account menu; each person receives a set-password link by email (Postmark or SMTP, configured in Settings) or, if email is not set up, the admin gets the link to pass on. Notes, pins, chat sessions and the "My lessons" list are per user; talk digests are shared. Settings and Users are admin-only.

Environment variables for a server deployment (all optional locally): `LP_DATA_DIR` (data directory outside the clone), `LP_BASE_URL` (used in emailed links), `LP_COOKIE_SECURE=1` (behind HTTPS), `LP_TRUST_PROXY=1` (read `X-Forwarded-For` behind nginx).

Open Settings in the app to enter an Anthropic API key (or pick an Ollama model) and, optionally, email details for sending your notes: a Postmark server token plus a verified sender address (default), or any SMTP server. Settings live in `data/app.db`, not in environment files.

The app uses port 8765 for the API because 8000 was taken on the development machine; change it in `dev.sh`, `web/vite.config.ts` and `server/cli.py` if you prefer another.

## Getting the talks

```bash
python3 scrape_conference_talks.py            # full scrape of all conferences (hours; 1 request/second)
python3 scrape_conference_talks.py --update   # only conferences missing from the JSON (e.g. after a new conference)
python -m server.cli index                    # then rebuild the index (or use Settings → Rebuild index)
```

Output goes to `data/general_conference_talks.json`:

```json
{
  "metadata": {"scraped_date": "...", "total_conferences": 111, "total_talks": 4267},
  "conferences": {
    "https://www.churchofjesuschrist.org/study/general-conference/2026/04?lang=eng": {
      "url": "...", "talk_count": 37,
      "talks": [{"speaker": "...", "title": "...", "content": "...", "paragraphs": ["..."], "url": "..."}]
    }
  }
}
```

## Project layout

```
server/            FastAPI app, indexer, search, AI providers, routers
web/               Vue 3 frontend
data/              runtime data (talks JSON, scriptures JSON, app.db, embeddings) — not committed
scrape_conference_talks.py
tests/             pytest
```

## Tests

```bash
python -m pytest -q
```

## Notes

- Related-talk and “meaning” search use `BAAI/bge-small-en-v1.5` embeddings computed locally; keyword search uses SQLite FTS5 with BM25.
- Scripture references are parsed from the talk text (`server/citations.py`). Footnote citations of other talks are resolved to indexed talks when the title and conference match.
- The Claude provider uses adaptive thinking, prompt caching of the talk text, streaming, and server-side refusal fallbacks. Ollama models without tool support get search results injected instead of calling tools.
- Design is inspired by the Church's website but uses its own mark; the Church logo and the Christus image are trademarks of Intellectual Reserve, Inc. and are intentionally not included.
