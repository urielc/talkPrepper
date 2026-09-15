"""Command line entry points.

    python -m server.cli download-scriptures
    python -m server.cli index [--skip-embeddings] [--talks PATH]
    python -m server.cli serve [--host 127.0.0.1] [--port 8765] [--reload]
"""

from __future__ import annotations

import argparse
import sys
import time

from . import db as dbm
from .config import TALKS_JSON, SCRIPTURES_JSON, DEFAULT_EMBEDDING_MODEL
from pathlib import Path


def cmd_download(args: argparse.Namespace) -> None:
    from .scriptures import download_scriptures
    p = download_scriptures(SCRIPTURES_JSON, force=args.force)
    print(f"scriptures: {p} ({p.stat().st_size/1e6:.1f} MB)")


def cmd_index(args: argparse.Namespace) -> None:
    from .indexer import build_index
    conn = dbm.connect()
    dbm.ensure_schema(conn)
    last = {"stage": None, "t": 0.0}

    def progress(stage: str, done: int, total: int) -> None:
        now = time.time()
        if stage != last["stage"] or now - last["t"] > 2 or (total and done == total):
            pct = f" {done}/{total}" if total else ""
            print(f"  [{stage}]{pct}", flush=True)
            last["stage"], last["t"] = stage, now

    talks = Path(args.talks) if args.talks else TALKS_JSON
    if not talks.exists():
        sys.exit(f"talks JSON not found: {talks}")
    stats = build_index(conn, talks_json=talks, embedding_model=args.model,
                        progress=progress, skip_embeddings=args.skip_embeddings)
    for k, v in stats.to_dict().items():
        print(f"{k:20s} {v}")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn
    uvicorn.run("server.main:app", host=args.host, port=args.port, reload=args.reload)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m server.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download-scriptures", help="fetch the standard works JSON")
    d.add_argument("--force", action="store_true")
    d.set_defaults(fn=cmd_download)

    i = sub.add_parser("index", help="(re)build the search index")
    i.add_argument("--talks", help="path to talks JSON (default data/general_conference_talks.json)")
    i.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    i.add_argument("--skip-embeddings", action="store_true")
    i.set_defaults(fn=cmd_index)

    s = sub.add_parser("serve", help="run the API + web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=cmd_serve)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
