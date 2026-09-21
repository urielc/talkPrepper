"""Scripture lookup and reverse lookup (which talks cite a passage)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..citations import parse_ref
from ..deps import get_conn, get_user
from ..scriptures import (
    get_verses, chapter_count, format_ref, display_book, canonical_book, BOOKS, BOOK_VOLUME,
)
from .talks import talks_citing

router = APIRouter(tags=["scriptures"])


def parse_single_ref(ref: str):
    parsed = parse_ref(ref)
    if parsed is None:
        raise HTTPException(400, f"could not parse scripture reference: {ref!r}")
    return parsed


@router.get("/scriptures/books")
def books():
    return [{"book": display_book(t), "short": s, "volume": v} for t, s, v, _ in BOOKS]


@router.get("/scriptures/lookup")
def lookup(ref: str = Query(..., min_length=3), conn=Depends(get_conn), _user=Depends(get_user)):
    book, chapter, vs, ve = parse_single_ref(ref)
    verses = get_verses(conn, book, chapter, vs, ve)
    if not verses:
        raise HTTPException(404, f"no verses for {format_ref(book, chapter, vs, ve)}")
    return {
        "ref": format_ref(book, chapter, vs, ve),
        "book": display_book(book), "volume": BOOK_VOLUME.get(book),
        "chapter": chapter, "verse_start": vs, "verse_end": ve,
        "chapters": chapter_count(conn, book),
        "verses": [v.to_dict() for v in verses],
    }


@router.get("/scriptures/lookup/talks")
def lookup_talks(ref: str = Query(..., min_length=3), limit: int = Query(50, le=200),
                 exclude: str | None = None, conn=Depends(get_conn), _user=Depends(get_user)):
    book, chapter, vs, ve = parse_single_ref(ref)
    res = talks_citing(conn, book, chapter, vs, ve, exclude=exclude, limit=limit)
    res["ref"] = format_ref(book, chapter, vs, ve)
    return res


@router.get("/scriptures/{book}/{chapter}")
def chapter(book: str, chapter: int, conn=Depends(get_conn), _user=Depends(get_user)):
    canon = canonical_book(book)
    if not canon:
        raise HTTPException(404, f"unknown book {book!r}")
    verses = get_verses(conn, canon, chapter)
    if not verses:
        raise HTTPException(404, "chapter not found")
    return {
        "ref": format_ref(canon, chapter, None, None),
        "book": display_book(canon), "volume": BOOK_VOLUME.get(canon),
        "chapter": chapter, "chapters": chapter_count(conn, canon),
        "verses": [v.to_dict() for v in verses],
    }
