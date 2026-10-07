Runtime data (not committed):

- `general_conference_talks.json`: scraped talks (`python3 scrape_conference_talks.py`)
- `scriptures.json`: standard works (`python -m server.cli download-scriptures`)
- `apocrypha.json`: KJV Apocrypha (`python -m server.cli download-apocrypha`)
- `josephus/`: the works of Josephus, Perseus TEI XML (`python -m server.cli download-josephus`)
- `app.db`: SQLite index + notes/pins/settings (`python -m server.cli index`)
- `embeddings/`: chunk vectors (talks: `chunks.npy`; Josephus: `josephus.npy`), each with a hash sidecar
