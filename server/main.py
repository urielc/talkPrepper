"""FastAPI application: JSON API under /api, Vue build served at /."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db as dbm
from .config import DATA_DIR, WEB_DIST
from .middleware import SecurityHeadersMiddleware
from .search import SearchEngine
from .migrate import apply_schema
from .settings import migrate_plaintext_secrets
from .routers import talks, search, scriptures, lessons, settings, chat, admin, digest, auth, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = dbm.connect()
    dbm.ensure_schema(conn)
    apply_schema(conn)
    migrate_plaintext_secrets(conn)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
    app.state.conn = conn
    app.state.engine = SearchEngine(conn)
    app.state.index_job = None
    try:
        yield
    finally:
        conn.close()


app = FastAPI(title="Lesson Prep", version="0.1.0", lifespan=lifespan)

app.add_middleware(SecurityHeadersMiddleware)
# No CORS middleware: the Vite dev server proxies /api to this app (see
# web/vite.config.ts), so the frontend never makes a cross-origin request; the
# production build is served from this same origin. Nothing needs allow_origins.

for r in (auth.router, users.router, digest.router, talks.router, search.router, scriptures.router,
          lessons.router, settings.router, chat.router, admin.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
def health():
    conn = app.state.conn
    return {
        "ok": True,
        "has_users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0,
        "index_ready": dbm.index_ready(conn),
        "built_at": dbm.get_meta(conn, "built_at"),
        "semantic": app.state.engine.semantic_available,
    }


# ---- static SPA (production build). In dev, Vite serves the app instead.
if WEB_DIST.exists():
    WEB_DIST_RESOLVED = WEB_DIST.resolve()

    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path:
            try:
                candidate = (WEB_DIST_RESOLVED / full_path).resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                candidate = None
            if candidate and candidate.is_file() and candidate.is_relative_to(WEB_DIST_RESOLVED):
                return FileResponse(candidate)
        # The entry page must never be cached: it names the hashed asset files,
        # so a stale copy keeps loading an old bundle after a rebuild.
        return FileResponse(WEB_DIST_RESOLVED / "index.html",
                            headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
