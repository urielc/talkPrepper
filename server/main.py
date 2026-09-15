"""FastAPI application: JSON API under /api, Vue build served at /."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db as dbm
from .config import WEB_DIST
from .search import SearchEngine
from .routers import talks, search, scriptures, lessons, settings, chat, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = dbm.connect()
    dbm.ensure_schema(conn)
    app.state.conn = conn
    app.state.engine = SearchEngine(conn)
    app.state.index_job = None
    try:
        yield
    finally:
        conn.close()


app = FastAPI(title="Lesson Prep", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (talks.router, search.router, scriptures.router, lessons.router,
          settings.router, chat.router, admin.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
def health():
    conn = app.state.conn
    return {
        "ok": True,
        "index_ready": dbm.index_ready(conn),
        "built_at": dbm.get_meta(conn, "built_at"),
        "semantic": app.state.engine.semantic_available,
    }


# ---- static SPA (production build). In dev, Vite serves the app instead.
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
