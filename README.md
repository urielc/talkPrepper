# Lesson Prep

A local study and preparation tool for leading elders quorum discussions built on a General Conference talk. It indexes every conference talk since 1971 plus the standard works, and gives you, for the assigned talk:

- the full text with every scripture reference clickable in place,
- related talks (keyword + meaning-based search) and talks that cite the same passages,
- free-text search across all talks and scriptures,
- an AI assistant (Claude API or a local Ollama model) that searches the same index and cites clickable references,
- notes and pinned references per lesson, printable and emailable.

Backend: Python / FastAPI / SQLite (FTS5) / sentence-transformers. Frontend: Vue 3 + Vite.

## Setup from a fresh clone

Requirements: Python 3.11+ (3.14 tested), Node 20+, about 3 GB of disk (CPU torch is the bulk), and a
network connection for the first three steps. The talk text, scriptures, database and embeddings are not
in the repository; the steps below create them.

```bash
git clone https://github.com/urielc/talkPrepper.git && cd talkPrepper

# 1. Python dependencies (CPU-only torch keeps the download at ~200 MB)
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install -r requirements.txt

# 2. Frontend dependencies and production build
cd web && npm install && npm run build && cd ..

# 3. Talk text: scrape all General Conference talks since 1971 into data/general_conference_talks.json
#    (one request per second out of courtesy to the site; expect 2–3 hours)
python3 scrape_conference_talks.py

# 4. Standard works (public-domain JSON, 18 MB)
python -m server.cli download-scriptures

# 5. Build the search index and embeddings (several minutes on CPU; downloads the bge-small model once)
python -m server.cli index

# 6. Create your admin account; prints a link to set your password
python -m server.cli migrate --admin-email you@example.com --name "Your Name"

# 7. Run it
python -m server.cli serve            # http://127.0.0.1:8765
```

Open the set-password link from step 6, sign in, then go to **Settings** in the account menu to enter an
Anthropic API key (or point at an Ollama model) and, optionally, email details for invitations and for
mailing your notes. Nothing works without step 6: every page except the health check requires a signed-in
user.

Keeping the talks current after a new conference:

```bash
make update-talks    # scrapes only conferences missing from the JSON, then rebuilds the index
```

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
