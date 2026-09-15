import json
import sqlite3

import pytest

from server import db as dbm
from server.ai import digest as dg
from server.ai.base import Provider


class FakeProvider(Provider):
    name = "fake"
    model = "fake-1"

    def __init__(self):
        self.calls = []

    def generate_json(self, system, user_message, schema):
        self.calls.append((system, user_message, schema))
        return {
            "essence": "Cheer, don't judge.",
            "main_points": [{"point": "Only the Lord can judge.", "paragraph": 1},
                            {"point": "Bogus paragraph pointer", "paragraph": 999}],
            "key_quotes": [{"text": "Only the Lord fully knows our individual limitations and capacity.",
                            "paragraph": 1, "why": "Thesis sentence."}],
            "questions": [{"question": "When have you felt cheered on?", "kind": "opening", "note": "Warm up."}],
        }


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.ensure_schema(c)
    return c


TALK = {"id": "2025-10/x", "title": "Cheering Each Other On", "speaker": "Sister Dennis", "conference": "October 2025"}
PARAS = [{"idx": 0, "text": "First Counselor", "is_note": False},
         {"idx": 1, "text": "Only the Lord fully knows our individual limitations and capacity.", "is_note": False},
         {"idx": 2, "text": "See Alma 41:14.", "is_note": True}]


def test_generate_and_cache(conn, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(dg, "get_provider", lambda settings: fake)
    assert dg.load_digest(conn, TALK["id"]) is None
    d = dg.generate_digest(conn, TALK, PARAS)
    assert d["essence"] == "Cheer, don't judge."
    assert d["provider"] == "fake" and d["model"] == "fake-1"
    # invalid paragraph pointers are nulled, valid ones kept
    assert [m["paragraph"] for m in d["main_points"]] == [1, None]
    # footnotes are excluded from the prompt, body paragraphs are indexed
    system, user, schema = fake.calls[0]
    assert "[1] Only the Lord" in user and "See Alma 41:14" not in user
    assert schema is dg.DIGEST_SCHEMA and "questions" in system
    # cached
    again = dg.load_digest(conn, TALK["id"])
    assert again["essence"] == d["essence"] and again["created_at"]
    dg.delete_digest(conn, TALK["id"])
    assert dg.load_digest(conn, TALK["id"]) is None


def test_regenerate_replaces(conn, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(dg, "get_provider", lambda settings: fake)
    dg.generate_digest(conn, TALK, PARAS)
    fake.model = "fake-2"
    d = dg.generate_digest(conn, TALK, PARAS)
    assert d["model"] == "fake-2"
    assert conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 1


def test_schema_is_strict_json_schema():
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)
    check(dg.DIGEST_SCHEMA)
    json.dumps(dg.DIGEST_SCHEMA)
