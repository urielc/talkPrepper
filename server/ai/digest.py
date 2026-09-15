"""Talk digest: the essence of a talk, its key quotations, and discussion questions.

Generated once per talk with the configured AI provider (structured JSON) and
cached in the ``digests`` table until the user asks to regenerate.
"""

from __future__ import annotations

import json
import sqlite3

from . import get_provider
from .base import ProviderError
from ..settings import get_settings

DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "essence": {
            "type": "string",
            "description": "The talk's central message in 2–4 sentences, in the speaker's own terms.",
        },
        "main_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "point": {"type": "string", "description": "One observation or teaching, one or two sentences."},
                    "paragraph": {"type": ["integer", "null"], "description": "Index of the paragraph that best supports it."},
                },
                "required": ["point", "paragraph"],
                "additionalProperties": False,
            },
        },
        "key_quotes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Exact sentence(s) copied verbatim from the talk."},
                    "paragraph": {"type": ["integer", "null"]},
                    "why": {"type": "string", "description": "Why this line matters to the message, one sentence."},
                },
                "required": ["text", "paragraph", "why"],
                "additionalProperties": False,
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "kind": {"type": "string", "enum": ["opening", "discussion", "application"]},
                    "note": {"type": "string", "description": "What the question is meant to surface, one sentence for the teacher."},
                },
                "required": ["question", "kind", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["essence", "main_points", "key_quotes", "questions"],
    "additionalProperties": False,
}

SYSTEM = """You prepare a reader's digest of a General Conference talk for someone who will lead an elders quorum discussion on it.

Work only from the talk text provided. Do not add doctrine, commentary or testimony of your own; the digest is a faithful distillation of what the speaker said, plus questions that will get a class talking about it.

Guidelines:
- essence: the central message in 2–4 sentences, using the speaker's own framing and key terms.
- main_points: 4–8 observations that carry the talk's argument or structure, in the order they appear. Each points at the paragraph index that best supports it (indices are given in [brackets] before each paragraph).
- key_quotes: 3–6 sentences copied verbatim from the talk that a teacher would want to read aloud. Never paraphrase or splice; copy exactly.
- questions: 6–10 thought-provoking questions for a quorum of adult men. Mix kinds: "opening" (draws people in, no wrong answers), "discussion" (probes the talk's ideas, invites disagreement or nuance), "application" (connects the teaching to their week, families, callings). Avoid yes/no questions and avoid questions whose answer is simply restating the talk. Each has a short teacher note on what it is meant to surface.
"""


def build_user_message(talk: dict, paragraphs: list[dict]) -> str:
    body = "\n\n".join(f"[{p['idx']}] {p['text']}" for p in paragraphs if not p.get("is_note"))
    return (f"Title: {talk['title']}\nSpeaker: {talk['speaker']}\nConference: {talk.get('conference')}\n\n"
            f"--- TALK (paragraph indices in brackets) ---\n{body}")


def load_digest(conn: sqlite3.Connection, talk_id: str) -> dict | None:
    r = conn.execute("SELECT * FROM digests WHERE talk_id=?", (talk_id,)).fetchone()
    if not r:
        return None
    data = json.loads(r["json"])
    return {"talk_id": talk_id, "provider": r["provider"], "model": r["model"],
            "created_at": r["created_at"], **data}


def generate_digest(conn: sqlite3.Connection, talk: dict, paragraphs: list[dict]) -> dict:
    provider = get_provider(get_settings(conn))
    data = provider.generate_json(SYSTEM, build_user_message(talk, paragraphs), DIGEST_SCHEMA)
    valid = {p["idx"] for p in paragraphs}
    for item in data.get("main_points", []) + data.get("key_quotes", []):
        if item.get("paragraph") not in valid:
            item["paragraph"] = None
    conn.execute(
        "INSERT INTO digests(talk_id, provider, model, json, created_at) VALUES(?,?,?,?,datetime('now')) "
        "ON CONFLICT(talk_id) DO UPDATE SET provider=excluded.provider, model=excluded.model, "
        "json=excluded.json, created_at=excluded.created_at",
        (talk["id"], provider.name, provider.model, json.dumps(data, ensure_ascii=False)))
    conn.commit()
    return load_digest(conn, talk["id"])


def delete_digest(conn: sqlite3.Connection, talk_id: str) -> None:
    conn.execute("DELETE FROM digests WHERE talk_id=?", (talk_id,))
    conn.commit()


__all__ = ["DIGEST_SCHEMA", "load_digest", "generate_digest", "delete_digest", "ProviderError"]
