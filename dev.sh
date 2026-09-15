#!/usr/bin/env bash
# Run the API (uvicorn, port 8765) and the Vite dev server (port 5173) together.
set -euo pipefail
cd "$(dirname "$0")"

python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8765 --reload &
API=$!
trap 'kill $API 2>/dev/null || true' EXIT

cd web && npm run dev -- --host 127.0.0.1
