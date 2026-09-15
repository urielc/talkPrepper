Runtime data (not committed):

- `general_conference_talks.json` — scraped talks (`python3 scrape_conference_talks.py`)
- `scriptures.json` — standard works (`python -m server.cli download-scriptures`)
- `app.db` — SQLite index + notes/pins/settings (`python -m server.cli index`)
- `embeddings/` — chunk vectors
