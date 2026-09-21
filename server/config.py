"""Paths and constants shared by the server, indexer and CLI."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# On a server the data lives outside the git clone (LP_DATA_DIR); locally it is ./data.
DATA_DIR = Path(os.environ.get("LP_DATA_DIR") or ROOT / "data")
TALKS_JSON = DATA_DIR / "general_conference_talks.json"
SCRIPTURES_JSON = DATA_DIR / "scriptures.json"
DB_PATH = DATA_DIR / "app.db"
EMBEDDINGS_DIR = DATA_DIR / "embeddings"
CHUNKS_NPY = EMBEDDINGS_DIR / "chunks.npy"
CHUNK_HASHES = EMBEDDINGS_DIR / "chunk_hashes.json"
WEB_DIST = ROOT / "web" / "dist"

SCRIPTURES_URL = (
    "https://raw.githubusercontent.com/beandog/lds-scriptures/master/json/lds-scriptures-json.txt"
)

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

# Chunking for embeddings: paragraph-aligned, roughly this many words per chunk.
CHUNK_TARGET_WORDS = 200
CHUNK_MAX_WORDS = 320

SETTINGS_DEFAULTS = {
    "ai_provider": "anthropic",
    "anthropic_api_key": "",
    "anthropic_model": DEFAULT_ANTHROPIC_MODEL,
    "ollama_base_url": DEFAULT_OLLAMA_URL,
    "ollama_model": "",
    # email: Postmark HTTP API (default) or plain SMTP
    "email_provider": "postmark",  # postmark | smtp
    "email_from": "",              # must be a verified Postmark sender signature / domain
    "postmark_server_token": "",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_user": "",
    "smtp_password": "",
    "smtp_tls": "starttls",  # starttls | ssl | none
    "embedding_model": DEFAULT_EMBEDDING_MODEL,
}
SECRET_SETTINGS = {"anthropic_api_key", "smtp_password", "postmark_server_token"}

# Auth / deployment (environment; all optional on a LAN install)
BASE_URL = os.environ.get("LP_BASE_URL", "")            # e.g. https://lessons.example.com, for links in emails
COOKIE_NAME = "lp_session"
COOKIE_SECURE = os.environ.get("LP_COOKIE_SECURE", "0") in ("1", "true", "yes")
TRUST_PROXY = os.environ.get("LP_TRUST_PROXY", "0") in ("1", "true", "yes")
SESSION_DAYS = 30
INVITE_HOURS = 72
POSTMARK_API_URL = "https://api.postmarkapp.com/email"
