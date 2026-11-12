"""Church manual pages for the reader panel, and manual search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import manuals as man
from ..deps import get_conn, get_engine, get_user
from ..suggest import fetch_pages

router = APIRouter(tags=["manuals"])


def page_payload(conn, page) -> dict:
    prev, nxt = man.neighbor(conn, page, -1), man.neighbor(conn, page, 1)
    return {
        "uri": page["uri"],
        "title": page["title"],
        "manual": page["manual_title"],
        "manual_key": page["manual_key"],
        "kind": page["kind"],
        "audience": page["audience"].split(),
        "url": page["url"],
        "blocks": [{"text": r["text"], "h": r["heading"]} for r in man.page_paragraphs(conn, page["id"])],
        "prev": {"uri": prev["uri"], "title": prev["title"]} if prev else None,
        "next": {"uri": nxt["uri"], "title": nxt["title"]} if nxt else None,
        "attribution": man.ATTRIBUTION,
    }


@router.get("/manuals")
def list_manuals(conn=Depends(get_conn), _user=Depends(get_user)):
    rows = conn.execute(
        "SELECT m.key, m.title, m.kind, m.audience, COUNT(p.id) AS pages FROM manuals m "
        "LEFT JOIN manual_pages p ON p.manual_key=m.key GROUP BY m.key ORDER BY m.ord").fetchall()
    return [{**dict(r), "audience": r["audience"].split()} for r in rows]


@router.get("/manuals/lookup")
def lookup(uri: str = Query(..., min_length=3, max_length=400), conn=Depends(get_conn), _user=Depends(get_user)):
    page = man.get_page(conn, uri)
    if page is None:
        raise HTTPException(404, f"no manual page {uri}")
    return page_payload(conn, page)


@router.get("/manuals/search")
def search(q: str = Query(..., min_length=2, max_length=300), audience: str | None = None,
           gender: str | None = None, manual: str | None = None, limit: int = Query(10, ge=1, le=30),
           conn=Depends(get_conn), engine=Depends(get_engine), _user=Depends(get_user)):
    hits = engine.manual_search(q, "hybrid", limit, manual=manual, audience=audience, gender=gender)
    pages = fetch_pages(conn, [int(h.talk_id) for h in hits])
    return [{**pages[int(h.talk_id)], "snippet": h.snippets[0] if h.snippets else ""}
            for h in hits if int(h.talk_id) in pages]
