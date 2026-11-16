"""Topic studies: create, edit, summarize and delete, plus the workspace data for the left column."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import studies as st
from ..ai.base import ProviderError
from ..ai.study import generate_study
from ..audience import CLASSES, DEFAULT_KEY
from ..auth import rate_limit
from ..citations import parse_ref
from ..deps import get_conn, get_engine, get_user
from ..search import SearchEngine
from .talks import fetch_talks, shared_for_refs

router = APIRouter(tags=["studies"])


class SourceBody(BaseModel):
    kind: str
    ref: str = Field(min_length=1, max_length=300)
    title: str = Field("", max_length=400)


def _check_sources(sources: list[SourceBody]) -> list[dict]:
    out, seen = [], set()
    for s in sources:
        if s.kind not in st.SOURCE_KINDS:
            raise HTTPException(422, f"unknown source kind {s.kind!r}")
        if (s.kind, s.ref) in seen:
            continue
        seen.add((s.kind, s.ref))
        out.append({"kind": s.kind, "ref": s.ref.strip(), "title": s.title.strip() or s.ref.strip()})
    if not out:
        raise HTTPException(422, "Queue at least one source.")
    if len(out) > st.MAX_SOURCES:
        raise HTTPException(422, f"A study takes up to {st.MAX_SOURCES} sources.")
    return out


class StudyBody(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    audience: str = DEFAULT_KEY
    sources: list[SourceBody] = Field(min_length=1, max_length=st.MAX_SOURCES)
    modifier: str = Field("", max_length=2000)


class StudyPatch(BaseModel):
    topic: str | None = Field(None, min_length=2, max_length=300)
    audience: str | None = None
    sources: list[SourceBody] | None = Field(None, max_length=st.MAX_SOURCES)
    modifier: str | None = Field(None, max_length=2000)


def _summarize(conn: sqlite3.Connection, engine: SearchEngine, uid: int, study: dict) -> tuple[dict, str | None]:
    """Run the AI summary. A failure leaves the study as it was and comes back as a message.
    Callers check ``rate_limit`` first, so a refused request never leaves a half-made study behind."""
    try:
        return generate_study(conn, engine, uid, study), None
    except ProviderError as e:
        return study, str(e)


@router.post("/studies")
def create_study(body: StudyBody, conn=Depends(get_conn), engine=Depends(get_engine), user=Depends(get_user)):
    uid = user["id"]
    if body.audience not in CLASSES:
        raise HTTPException(422, f"unknown audience {body.audience!r}")
    sources = _check_sources(body.sources)
    rate_limit(f"study:{uid}", limit=20, window_s=600)
    cur = conn.execute(
        "INSERT INTO studies(user_id, topic, audience, modifier, sources_json) VALUES(?,?,?,?,?)",
        (uid, body.topic.strip(), body.audience, body.modifier.strip(), json.dumps(sources, ensure_ascii=False)))
    sid = cur.lastrowid
    nxt = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM working_on WHERE user_id=?", (uid,)).fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO working_on(user_id, talk_id, ord, audience) VALUES(?,?,?,?)",
                 (uid, st.study_key(sid), nxt, body.audience))
    conn.commit()
    study, error = _summarize(conn, engine, uid, st.get_study_or_404(conn, uid, sid))
    return {**study, "error": error}


@router.get("/studies")
def list_studies(conn=Depends(get_conn), user=Depends(get_user)):
    """This user's studies, most recently updated first, whether or not they are in my lessons."""
    rows = conn.execute(
        "SELECT s.*, EXISTS(SELECT 1 FROM working_on w WHERE w.user_id=s.user_id AND w.talk_id='study:' || s.id) AS mine "
        "FROM studies s WHERE s.user_id=? ORDER BY s.updated_at DESC, s.id DESC", (user["id"],)).fetchall()
    out = []
    for r in rows:
        d = st.study_to_dict(r)
        out.append({"id": d["id"], "key": d["key"], "topic": d["topic"], "audience": d["audience"],
                    "audience_label": d["audience_label"], "source_count": len(d["sources"]),
                    "has_summary": d["summary"] is not None, "in_my_lessons": bool(r["mine"]),
                    "updated_at": d["updated_at"]})
    return out


@router.get("/studies/{study_id}")
def get_study(study_id: int, conn=Depends(get_conn), user=Depends(get_user)):
    return st.get_study_or_404(conn, user["id"], study_id)


@router.patch("/studies/{study_id}")
def patch_study(study_id: int, body: StudyPatch, conn=Depends(get_conn), user=Depends(get_user)):
    """Change the sources, modifier, topic or audience. The summary stays until regenerated."""
    uid = user["id"]
    st.get_study_or_404(conn, uid, study_id)
    if body.audience is not None and body.audience not in CLASSES:
        raise HTTPException(422, f"unknown audience {body.audience!r}")
    if body.topic is not None:
        conn.execute("UPDATE studies SET topic=? WHERE id=? AND user_id=?", (body.topic.strip(), study_id, uid))
    if body.modifier is not None:
        conn.execute("UPDATE studies SET modifier=? WHERE id=? AND user_id=?", (body.modifier.strip(), study_id, uid))
    if body.sources is not None:
        conn.execute("UPDATE studies SET sources_json=? WHERE id=? AND user_id=?",
                     (json.dumps(_check_sources(body.sources), ensure_ascii=False), study_id, uid))
    if body.audience is not None:
        conn.execute("UPDATE studies SET audience=? WHERE id=? AND user_id=?", (body.audience, study_id, uid))
        conn.execute("UPDATE working_on SET audience=? WHERE user_id=? AND talk_id=?",
                     (body.audience, uid, st.study_key(study_id)))
    conn.execute("UPDATE studies SET updated_at=datetime('now') WHERE id=? AND user_id=?", (study_id, uid))
    conn.commit()
    return st.get_study_or_404(conn, uid, study_id)


@router.post("/studies/{study_id}/generate")
def regenerate(study_id: int, conn=Depends(get_conn), engine=Depends(get_engine), user=Depends(get_user)):
    uid = user["id"]
    study = st.get_study_or_404(conn, uid, study_id)
    rate_limit(f"study:{uid}", limit=20, window_s=600)
    study, error = _summarize(conn, engine, uid, study)
    if error:
        raise HTTPException(400, error)
    return study


@router.delete("/studies/{study_id}")
def remove_study(study_id: int, conn=Depends(get_conn), user=Depends(get_user)):
    st.get_study_or_404(conn, user["id"], study_id)
    st.delete_study(conn, user["id"], study_id)
    return {"ok": True}


# ---------------------------------------------------------------- left column

def queued_talk_ids(study: dict) -> list[str]:
    return [s["ref"] for s in study["sources"] if s["kind"] == "talk"]


def related_query(study: dict) -> str:
    themes = [t["heading"] for t in ((study["summary"] or {}).get("themes") or [])]
    return " ".join([study["topic"], *themes])[:600]


@router.get("/studies/{study_id}/related")
def related(study_id: int, limit: int = Query(20, le=100), conn=Depends(get_conn),
            engine: SearchEngine = Depends(get_engine), user=Depends(get_user)):
    """Talks on the study's topic and themes that are not already queued."""
    study = st.get_study_or_404(conn, user["id"], study_id)
    query = related_query(study)
    hits = engine.related_to_text(query, queued_talk_ids(study), limit)
    talks = fetch_talks(conn, [h.talk_id for h in hits])
    results = [{**h.to_dict(), "talk": talks.get(h.talk_id), "shared_scriptures": 0} for h in hits]
    return {"terms": [study["topic"]], "results": results, "semantic": engine.semantic_available, "custom": False}


def study_scripture_refs(conn: sqlite3.Connection, study: dict) -> list[tuple]:
    """Passages the study draws on: queued scripture sources, the summary's references and scriptures cited by
    queued talks."""
    raw = [s["ref"] for s in study["sources"] if s["kind"] == "scripture"]
    raw += (study["summary"] or {}).get("scriptures") or []
    refs: list[tuple] = []
    for r in raw:
        p = parse_ref(r)
        if p and p not in refs:
            refs.append(p)
    ids = queued_talk_ids(study)
    if ids:
        for r in conn.execute(
                "SELECT DISTINCT book, chapter, verse_start, verse_end FROM scripture_refs "
                "WHERE talk_id IN (SELECT value FROM json_each(?)) ORDER BY id", (json.dumps(ids),)):
            k = (r["book"], r["chapter"], r["verse_start"], r["verse_end"])
            if k not in refs:
                refs.append(k)
    return refs


@router.get("/studies/{study_id}/scriptures")
def scriptures(study_id: int, limit_per_passage: int = 12, conn=Depends(get_conn), user=Depends(get_user)):
    """For each passage the study draws on, the talks that cite it (leaving out the queued talks)."""
    study = st.get_study_or_404(conn, user["id"], study_id)
    return shared_for_refs(conn, study_scripture_refs(conn, study), exclude=queued_talk_ids(study) or None,
                           limit_per_passage=limit_per_passage)
