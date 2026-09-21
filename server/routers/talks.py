"""Conferences, talk index, talk detail, related talks."""

from __future__ import annotations

import json
import sqlite3

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_conn, get_engine, get_user
from ..search import SearchEngine, fts_query
from ..scriptures import format_ref, display_book

router = APIRouter(tags=["talks"])


def talk_row_to_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "conference_id": r["conference_id"],
        "conference": r["conference_label"] if "conference_label" in r.keys() else None,
        "year": r["year"] if "year" in r.keys() else None,
        "speaker": r["speaker"],
        "title": r["title"],
        "url": r["url"],
        "word_count": r["word_count"],
    }


TALK_SELECT = (
    "SELECT t.id, t.conference_id, t.speaker, t.title, t.url, t.word_count, t.ord, "
    "c.label AS conference_label, c.year FROM talks t JOIN conferences c ON c.id=t.conference_id "
)


def fetch_talks(conn: sqlite3.Connection, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ",".join("?" * len(chunk))
        for r in conn.execute(TALK_SELECT + f"WHERE t.id IN ({q})", chunk):
            out[r["id"]] = talk_row_to_dict(r)
    return out


def get_talk_or_404(conn: sqlite3.Connection, talk_id: str) -> sqlite3.Row:
    r = conn.execute(TALK_SELECT + "WHERE t.id=?", (talk_id,)).fetchone()
    if not r:
        raise HTTPException(404, f"talk not found: {talk_id}")
    return r


class MyLessonBody(BaseModel):
    talk_id: str


class ReorderMine(BaseModel):
    talk_ids: list[str]


def my_lessons(conn: sqlite3.Connection, uid: int) -> list[dict]:
    rows = conn.execute(
        "SELECT w.talk_id, w.added_at, w.ord, "
        "COALESCE((SELECT LENGTH(notes_md) FROM lessons l WHERE l.user_id=w.user_id AND l.talk_id=w.talk_id), 0) AS notes_len, "
        "(SELECT COUNT(*) FROM pins p WHERE p.user_id=w.user_id AND p.talk_id=w.talk_id) AS pin_count, "
        "EXISTS(SELECT 1 FROM digests d WHERE d.talk_id=w.talk_id) AS has_digest, "
        "(SELECT updated_at FROM lessons l WHERE l.user_id=w.user_id AND l.talk_id=w.talk_id) AS updated_at "
        "FROM working_on w WHERE w.user_id=? ORDER BY w.ord, w.added_at", (uid,)).fetchall()
    talks = fetch_talks(conn, [r["talk_id"] for r in rows])
    return [{"talk": talks[r["talk_id"]], "added_at": r["added_at"], "notes_len": r["notes_len"],
             "pin_count": r["pin_count"], "has_digest": bool(r["has_digest"]), "updated_at": r["updated_at"]}
            for r in rows if r["talk_id"] in talks]


@router.get("/my-lessons")
def list_my_lessons(conn=Depends(get_conn), user=Depends(get_user)):
    """The talks this user is working on."""
    return my_lessons(conn, user["id"])


@router.put("/my-lessons")
def add_my_lesson(body: MyLessonBody, conn=Depends(get_conn), user=Depends(get_user)):
    get_talk_or_404(conn, body.talk_id)
    nxt = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM working_on WHERE user_id=?", (user["id"],)).fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO working_on(user_id, talk_id, ord) VALUES(?,?,?)", (user["id"], body.talk_id, nxt))
    conn.commit()
    return my_lessons(conn, user["id"])


@router.post("/my-lessons/reorder")
def reorder_my_lessons(body: ReorderMine, conn=Depends(get_conn), user=Depends(get_user)):
    for i, tid in enumerate(body.talk_ids):
        conn.execute("UPDATE working_on SET ord=? WHERE user_id=? AND talk_id=?", (i, user["id"], tid))
    conn.commit()
    return my_lessons(conn, user["id"])


@router.delete("/my-lessons/{talk_id:path}")
def remove_my_lesson(talk_id: str, conn=Depends(get_conn), user=Depends(get_user)):
    conn.execute("DELETE FROM working_on WHERE user_id=? AND talk_id=?", (user["id"], talk_id))
    conn.commit()
    return my_lessons(conn, user["id"])


@router.get("/conferences")
def list_conferences(conn=Depends(get_conn), _user=Depends(get_user)):
    rows = conn.execute(
        "SELECT c.id, c.year, c.month, c.label, c.url, COUNT(t.id) AS talk_count "
        "FROM conferences c LEFT JOIN talks t ON t.conference_id=c.id "
        "GROUP BY c.id ORDER BY c.year DESC, c.month DESC").fetchall()
    return [dict(r) for r in rows]


@router.get("/conferences/{conference_id}/talks")
def conference_talks(conference_id: str, conn=Depends(get_conn), user=Depends(get_user)):
    rows = conn.execute(TALK_SELECT + "WHERE t.conference_id=? ORDER BY t.ord", (conference_id,)).fetchall()
    if not rows:
        raise HTTPException(404, "conference not found")
    lessons = {r["talk_id"]: r for r in conn.execute(
        "SELECT l.talk_id, LENGTH(l.notes_md) AS notes_len, "
        "(SELECT COUNT(*) FROM pins p WHERE p.talk_id=l.talk_id AND p.user_id=l.user_id) AS pin_count "
        "FROM lessons l WHERE l.user_id=?", (user["id"],))}
    out = []
    for r in rows:
        d = talk_row_to_dict(r)
        les = lessons.get(r["id"])
        d["has_lesson"] = bool(les and (les["notes_len"] or les["pin_count"]))
        out.append(d)
    return out


@router.get("/talks")
def list_talks(q: str = "", conference: str | None = None, limit: int = Query(50, le=500),
               conn=Depends(get_conn), _user=Depends(get_user)):
    """Talk picker: match title/speaker (and exact phrases in the text)."""
    q = q.strip()
    if not q:
        sql = TALK_SELECT + ("WHERE t.conference_id=? " if conference else "") + \
              "ORDER BY c.year DESC, c.month DESC, t.ord LIMIT ?"
        args = ([conference] if conference else []) + [limit]
        return [talk_row_to_dict(r) for r in conn.execute(sql, args)]
    match = fts_query(q)
    ids: list[str] = []
    if match:
        rows = conn.execute(
            "SELECT id FROM talks_fts WHERE talks_fts MATCH ? ORDER BY bm25(talks_fts) LIMIT ?",
            (match, limit)).fetchall()
        ids = [r["id"] for r in rows]
    if len(ids) < limit:
        # substring fallback (handles partial words like "Renl")
        like = f"%{q}%"
        rows = conn.execute(
            "SELECT id FROM talks WHERE (title LIKE ? OR speaker LIKE ?) "
            + ("AND conference_id=? " if conference else "") + "LIMIT ?",
            ([like, like] + ([conference] if conference else []) + [limit])).fetchall()
        for r in rows:
            if r["id"] not in ids:
                ids.append(r["id"])
    talks = fetch_talks(conn, ids)
    out = [talks[i] for i in ids if i in talks]
    if conference:
        out = [t for t in out if t["conference_id"] == conference]
    out.sort(key=lambda t: (-(t["year"] or 0), t["conference_id"]), reverse=False)
    return out[:limit]


# NB: sub-resource routes must come before the greedy "/talks/{talk_id:path}".

@router.get("/talks/{talk_id:path}/related")
def related(talk_id: str, limit: int = Query(20, le=100), conn=Depends(get_conn),
            engine: SearchEngine = Depends(get_engine), _user=Depends(get_user)):
    get_talk_or_404(conn, talk_id)
    hits, terms = engine.related_talks(talk_id, limit)
    talks = fetch_talks(conn, [h.talk_id for h in hits])
    shared = shared_ref_counts(conn, talk_id)
    out = []
    for h in hits:
        d = h.to_dict()
        d["talk"] = talks.get(h.talk_id)
        d["shared_scriptures"] = shared.get(h.talk_id, 0)
        out.append(d)
    return {"terms": terms, "results": out, "semantic": engine.semantic_available}


def shared_ref_counts(conn: sqlite3.Connection, talk_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT o.talk_id, COUNT(DISTINCT o.book || ':' || o.chapter || ':' || COALESCE(o.verse_start, 0)) AS n "
        "FROM scripture_refs s JOIN scripture_refs o "
        "  ON o.book=s.book AND o.chapter=s.chapter AND o.talk_id != s.talk_id "
        "  AND (s.verse_start IS NULL OR o.verse_start IS NULL OR "
        "       (COALESCE(o.verse_end, o.verse_start) >= s.verse_start AND o.verse_start <= COALESCE(s.verse_end, s.verse_start))) "
        "WHERE s.talk_id=? GROUP BY o.talk_id", (talk_id,)).fetchall()
    return {r["talk_id"]: r["n"] for r in rows}


@router.get("/talks/{talk_id:path}/shared-scriptures")
def shared_scriptures(talk_id: str, limit_per_passage: int = 12, conn=Depends(get_conn), _user=Depends(get_user)):
    """For each passage this talk cites, the other talks that cite it too."""
    get_talk_or_404(conn, talk_id)
    refs = conn.execute(
        "SELECT DISTINCT book, chapter, verse_start, verse_end FROM scripture_refs WHERE talk_id=? "
        "ORDER BY id", (talk_id,)).fetchall()
    out = []
    seen = set()
    for r in refs:
        key = (r["book"], r["chapter"], r["verse_start"], r["verse_end"])
        if key in seen:
            continue
        seen.add(key)
        others = talks_citing(conn, r["book"], r["chapter"], r["verse_start"], r["verse_end"],
                              exclude=talk_id, limit=limit_per_passage)
        out.append({
            "ref": format_ref(*key),
            "book": display_book(r["book"]), "chapter": r["chapter"],
            "verse_start": r["verse_start"], "verse_end": r["verse_end"],
            "count": others["total"],
            "talks": others["talks"],
        })
    out.sort(key=lambda x: -x["count"])
    return out


def talks_citing(conn: sqlite3.Connection, book: str, chapter: int, vs: int | None, ve: int | None,
                 exclude: str | None = None, limit: int = 50) -> dict:
    if vs is None:
        where = "book=? AND chapter=?"
        args: list = [book, chapter]
    else:
        ve = ve if ve is not None else vs
        where = ("book=? AND chapter=? AND (verse_start IS NULL OR "
                 "(COALESCE(verse_end, verse_start) >= ? AND verse_start <= ?))")
        args = [book, chapter, vs, ve]
    if exclude:
        where += " AND talk_id != ?"
        args.append(exclude)
    rows = conn.execute(
        f"SELECT talk_id, COUNT(*) AS n, MIN(raw) AS raw FROM scripture_refs WHERE {where} "
        "GROUP BY talk_id ORDER BY n DESC", args).fetchall()
    ids = [r["talk_id"] for r in rows]
    talks = fetch_talks(conn, ids[:limit])
    ordered = [dict(talks[i], mentions=r["n"]) for i, r in zip(ids[:limit], rows[:limit]) if i in talks]
    ordered.sort(key=lambda t: (-t["mentions"], -(t["year"] or 0)))
    return {"total": len(ids), "talks": ordered}


@router.get("/talks/{talk_id:path}")
def talk_detail(talk_id: str, conn=Depends(get_conn), user=Depends(get_user)):
    r = get_talk_or_404(conn, talk_id)
    talk = talk_row_to_dict(r)
    paras = conn.execute(
        "SELECT id, idx, text, is_note, marker, note_refs FROM paragraphs WHERE talk_id=? ORDER BY idx",
        (talk_id,)).fetchall()
    refs_by_para: dict[int, list[dict]] = {}
    for s in conn.execute(
            "SELECT paragraph_id, book, chapter, verse_start, verse_end, raw, char_start, char_end "
            "FROM scripture_refs WHERE talk_id=? ORDER BY paragraph_id, char_start", (talk_id,)):
        refs_by_para.setdefault(s["paragraph_id"], []).append({
            "ref": format_ref(s["book"], s["chapter"], s["verse_start"], s["verse_end"]),
            "book": display_book(s["book"]), "chapter": s["chapter"],
            "verse_start": s["verse_start"], "verse_end": s["verse_end"],
            "start": s["char_start"], "end": s["char_end"], "raw": s["raw"],
        })
    talk["paragraphs"] = [
        {"id": p["id"], "idx": p["idx"], "text": p["text"], "is_note": bool(p["is_note"]),
         "marker": p["marker"],
         "note_refs": json.loads(p["note_refs"]) if p["note_refs"] else [],
         "refs": refs_by_para.get(p["id"], [])}
        for p in paras
    ]
    # distinct scripture passages
    seen = set()
    passages = []
    for lst in refs_by_para.values():
        for x in lst:
            k = x["ref"]
            if k not in seen:
                seen.add(k)
                passages.append({k2: x[k2] for k2 in ("ref", "book", "chapter", "verse_start", "verse_end")})
    talk["scriptures"] = passages

    # talks this talk cites
    cites = conn.execute(
        "SELECT cited_talk_id, raw_title, raw_year, raw_month, raw FROM talk_refs WHERE talk_id=?",
        (talk_id,)).fetchall()
    cited_ids = [c["cited_talk_id"] for c in cites if c["cited_talk_id"]]
    cited_talks = fetch_talks(conn, cited_ids)
    talk["cites"] = []
    seen_c = set()
    for c in cites:
        key = c["cited_talk_id"] or (c["raw_title"], c["raw_year"])
        if key in seen_c:
            continue
        seen_c.add(key)
        talk["cites"].append({
            "talk": cited_talks.get(c["cited_talk_id"]) if c["cited_talk_id"] else None,
            "title": c["raw_title"], "year": c["raw_year"], "month": c["raw_month"], "raw": c["raw"],
        })
    # talks citing this talk
    by = conn.execute(
        "SELECT DISTINCT talk_id FROM talk_refs WHERE cited_talk_id=?", (talk_id,)).fetchall()
    by_talks = fetch_talks(conn, [b["talk_id"] for b in by])
    talk["cited_by"] = sorted(by_talks.values(), key=lambda t: -(t["year"] or 0))

    # neighbours in the same conference
    sib = conn.execute(TALK_SELECT + "WHERE t.conference_id=? ORDER BY t.ord", (r["conference_id"],)).fetchall()
    ids = [s["id"] for s in sib]
    i = ids.index(talk_id)
    talk["prev"] = talk_row_to_dict(sib[i - 1]) if i > 0 else None
    talk["next"] = talk_row_to_dict(sib[i + 1]) if i + 1 < len(sib) else None

    uid = user["id"]
    les = conn.execute("SELECT notes_md FROM lessons WHERE user_id=? AND talk_id=?", (uid, talk_id)).fetchone()
    pins = conn.execute("SELECT COUNT(*) FROM pins WHERE user_id=? AND talk_id=?", (uid, talk_id)).fetchone()[0]
    mine = conn.execute("SELECT 1 FROM working_on WHERE user_id=? AND talk_id=?", (uid, talk_id)).fetchone()
    talk["lesson"] = {"has_notes": bool(les and les["notes_md"]), "pin_count": pins, "mine": bool(mine)}
    return talk
