# Lesson Prep

A local study and preparation tool for leading elders quorum discussions built on a General Conference talk. It indexes every conference talk since 1971 plus the standard works, the KJV Apocrypha and the works of Josephus, and gives you, for the assigned talk:

- the full text with every scripture reference clickable in place,
- related talks (keyword + meaning-based search) and talks that cite the same passages,
- free-text search across all talks and scriptures,
- an AI assistant (Claude API or a local Ollama model) that searches the same index, including Josephus and the Apocrypha for historical background, and cites clickable references,
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

# 4. Standard works (public-domain JSON, 18 MB), the KJV Apocrypha (1.6 MB) and Josephus (5 MB).
#    The index step fetches any of these that are missing, so this is optional.
python -m server.cli download-scriptures
python -m server.cli download-apocrypha
python -m server.cli download-josephus

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

Environment variables for a server deployment (all optional on a LAN install, where the app is not reachable from outside your network): `LP_DATA_DIR` (data directory outside the clone). `LP_BASE_URL` (e.g. `https://lessons.example.com`, no path) is **required on any public deployment** — it's used to build invite/reset links safely instead of trusting request headers, and an `https://` value implies `Secure` session cookies. `LP_TRUST_PROXY=1` (read `X-Real-IP`/`X-Forwarded-For` from a trusted nginx in front) and `LP_COOKIE_SECURE=1` (force `Secure` cookies even without an `https://` `LP_BASE_URL`) both *require* `LP_BASE_URL` to be set — the app refuses to start otherwise, rather than silently running with headers it shouldn't trust or cookies sent over plain HTTP. `LP_SECRET_KEY` (encryption key for secrets at rest — see below). See `deploy/` for a systemd unit and nginx config with all of this set to safe defaults.

Open Settings in the app to enter an Anthropic API key (or pick an Ollama model) and, optionally, email details for sending your notes: a Postmark server token plus a verified sender address (default), or any SMTP server. Settings live in `data/app.db`, not in environment files. The three secret values (Anthropic key, Postmark token, SMTP password) are encrypted at rest with a Fernet key: set `LP_SECRET_KEY` yourself (recommended on a server — generate one with `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and keep it outside the clone), or leave it unset and the app generates `data/secret.key` (mode 0600) on first use.

The app uses port 8765 for the API because 8000 was taken on the development machine; change it in `dev.sh`, `web/vite.config.ts` and `server/cli.py` if you prefer another.

## Project layout

```
server/            FastAPI app, indexer, search, AI providers, routers
web/               Vue 3 frontend
data/              runtime data (talks JSON, scriptures and Apocrypha JSON, josephus/, app.db, embeddings), not committed
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
- **Apocrypha:** the KJV (1769 text) Apocrypha from eBible.org's public-domain "King James Version + Apocrypha" export, in the `scriptures` table under the volume "Apocrypha". Fourteen books; the Epistle of Jeremy is Baruch 6, as in the KJV, for fifteen by the usual count. Scripture lookups, the scripture panel and "talks citing" cover it; the landing page's verse search keeps to the standard works, and the assistant has its own `search_apocrypha` tool. The assistant is told to label it as Apocrypha and points to D&C 91.
- **Josephus:** William Whiston's 1737 translation (public domain) as encoded by the Perseus Digital Library (TEI XML, CC BY-SA 4.0 for the encoding), downloaded at setup rather than redistributed. One row per Whiston section (`Antiquities 18.3.3`), with the Niese range (`18.63–64`) beside it; references in either system resolve. Sections are embedded for meaning search (`embeddings/josephus.npy`). The parser repairs two chapter numbers the source has out of sequence (Antiquities 5 and 13). The assistant searches and reads it with `search_josephus` and `get_josephus` and cites `[[josephus:…]]`, which opens a reader panel.
- Ollama models without tool support get talk search results injected, but not Josephus or the Apocrypha.
- Design is inspired by the Church's website but uses its own mark; the Church logo and the Christus image are trademarks of Intellectual Reserve, Inc. and are intentionally not included.
