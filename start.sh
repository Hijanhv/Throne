#!/usr/bin/env bash
# Starts the Throne API (port 8000) and the Next.js dashboard (port 3000).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "Starting Throne..."

[ -f "$ROOT/.env" ] || { cp "$ROOT/.env.example" "$ROOT/.env"; echo "Created .env from .env.example"; }

cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
if command -v uv >/dev/null; then
  uv pip install -q --python .venv/bin/python -r requirements.txt
else
  .venv/bin/python -m ensurepip -q 2>/dev/null || true
  .venv/bin/python -m pip install -q -r requirements.txt
fi
.venv/bin/uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npm run dev &
FRONTEND_PID=$!

trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null' EXIT INT TERM

if ! curl -s -m 2 "${OLLAMA_URL:-http://localhost:11434}/api/tags" >/dev/null; then
  echo "Ollama is not running. Throne will use its regex parser. Start it with: ollama serve && ollama pull tinyllama"
fi

echo "Backend:  http://localhost:8000  (docs at /docs)"
echo "Frontend: http://localhost:3000"
wait
