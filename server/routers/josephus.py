"""Josephus passage lookup for the reader panel."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import josephus as jos
from ..deps import get_conn, get_user

router = APIRouter(tags=["josephus"])


@router.get("/josephus/lookup")
def lookup(ref: str = Query(..., min_length=3, max_length=120), conn=Depends(get_conn), _user=Depends(get_user)):
    parsed = jos.parse_josephus_ref(ref)
    if parsed is None:
        raise HTTPException(400, f"could not parse Josephus reference: {ref!r}")
    rows = jos.resolve(conn, parsed)
    if not rows:
        raise HTTPException(404, f"no passage for {ref}")
    first, last = rows[0], rows[-1]
    work = jos.WORKS_BY_KEY[first["work"]]
    prev, nxt = jos.neighbor(conn, first, -1), jos.neighbor(conn, last, 1)
    chapter_ref = None
    if work.chapters and len({(r["book"], r["chapter"]) for r in rows}) == 1:
        chapter_ref = (f"{work.short} {first['book']} Preface" if first["chapter"] == 0
                       else f"{work.short} {first['book']}.{first['chapter']}")
    return {
        "ref": jos.range_label(rows),
        "niese": jos.range_niese(rows),
        "work": work.key,
        "work_title": work.title,
        "chapter_title": first["chapter_title"],
        "chapter_ref": chapter_ref,
        "sections": [{"ref": jos.row_label(r), "niese": jos.row_niese(r), "section": r["section"],
                      "text": r["text"], "notes": json.loads(r["notes"] or "[]")} for r in rows],
        "prev": jos.row_label(prev) if prev else None,
        "next": jos.row_label(nxt) if nxt else None,
        "attribution": jos.ATTRIBUTION,
    }
