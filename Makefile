.PHONY: setup scriptures index dev build serve test scrape update-talks

PY ?= python3

setup:            ## install Python and Node dependencies
	pip install -r requirements.txt
	cd web && npm install

scriptures:       ## download the standard works JSON into data/
	$(PY) -m server.cli download-scriptures

index:            ## (re)build the SQLite index + embeddings from data/general_conference_talks.json
	$(PY) -m server.cli index

dev:              ## API on :8765 with reload + Vite on :5173
	./dev.sh

build:            ## production build of the web app into web/dist
	cd web && npm run build

serve: build      ## single process serving API + built web app on 127.0.0.1:8765
	$(PY) -m server.cli serve

serve-lan: build  ## same, reachable from other devices on the local network
	$(PY) -m server.cli serve --host 0.0.0.0

test:
	$(PY) -m pytest -q

scrape:           ## full re-scrape (hours)
	$(PY) scrape_conference_talks.py

update-talks:     ## scrape only conferences missing from the JSON, then re-index
	$(PY) scrape_conference_talks.py --update
	$(PY) -m server.cli index
