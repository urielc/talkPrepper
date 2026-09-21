"""Free-text search over talks and scriptures."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..deps import get_conn, get_engine, get_user
from ..search import SearchEngine, fts_query
from ..scriptures import search_verses
from .talks import fetch_talks

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    mode: Literal["hybrid", "keyword", "semantic"] = "hybrid"
    years: tuple[int, int] | None = None
    speaker: str | None = None
    conference: str | None = None
    limit: int = Field(20, ge=1, le=100)
    include_scriptures: bool = True


@router.post("/search")
def search(req: SearchRequest, conn=Depends(get_conn), engine: SearchEngine = Depends(get_engine), _user=Depends(get_user)):
    hits = engine.search(req.q, req.mode, req.limit, req.years, req.speaker, req.conference)
    talks = fetch_talks(conn, [h.talk_id for h in hits])
    results = []
    for h in hits:
        d = h.to_dict()
        d["talk"] = talks.get(h.talk_id)
        results.append(d)
    verses = []
    if req.include_scriptures and req.mode != "semantic":
        match = fts_query(req.q)
        if match:
            try:
                verses = search_verses(conn, match, limit=10)
            except Exception:
                verses = []
    return {
        "query": req.q, "mode": req.mode if engine.semantic_available or req.mode == "keyword" else "keyword",
        "semantic_available": engine.semantic_available,
        "results": results, "verses": verses,
    }
