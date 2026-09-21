"""Index status and rebuild."""

from __future__ import annotations

import json
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import db as dbm
from ..config import TALKS_JSON, SCRIPTURES_JSON, CHUNKS_NPY
from ..deps import get_admin, get_conn

router = APIRouter(tags=["admin"])


@router.get("/admin/index/status")
def index_status(request: Request, conn=Depends(get_conn), _admin=Depends(get_admin)):
    job = request.app.state.index_job
    stats = dbm.get_meta(conn, "stats")
    return {
        "ready": dbm.index_ready(conn),
        "built_at": dbm.get_meta(conn, "built_at"),
        "embedding_model": dbm.get_meta(conn, "embedding_model"),
        "stats": json.loads(stats) if stats else None,
        "talks_json_exists": TALKS_JSON.exists(),
        "talks_json_mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(TALKS_JSON.stat().st_mtime))
        if TALKS_JSON.exists() else None,
        "scriptures_json_exists": SCRIPTURES_JSON.exists(),
        "embeddings_exist": CHUNKS_NPY.exists(),
        "job": job,
    }


@router.post("/admin/index/rebuild")
def rebuild(request: Request, skip_embeddings: bool = False, _admin=Depends(get_admin)):
    app = request.app
    if app.state.index_job and app.state.index_job.get("running"):
        raise HTTPException(409, "an index build is already running")
    if not TALKS_JSON.exists():
        raise HTTPException(400, f"talks JSON not found at {TALKS_JSON}")
    job = {"running": True, "stage": "starting", "done": 0, "total": 0, "error": None,
           "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "finished_at": None, "stats": None}
    app.state.index_job = job

    def progress(stage, done, total):
        job.update(stage=stage, done=done, total=total)

    def run():
        from ..indexer import build_index
        from ..settings import get_setting
        conn = dbm.connect()
        try:
            model = get_setting(conn, "embedding_model")
            stats = build_index(conn, embedding_model=model, progress=progress,
                                skip_embeddings=skip_embeddings)
            job["stats"] = stats.to_dict()
        except Exception as e:  # surfaced to the UI
            job["error"] = f"{type(e).__name__}: {e}"
        finally:
            conn.close()
            job["running"] = False
            job["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            app.state.engine.reload()

    threading.Thread(target=run, name="index-rebuild", daemon=True).start()
    return job
