#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/.runtime/node/bin:$PATH"
if [ -x "$ROOT/.runtime/postgres/bin/pg_ctl" ] && [ -d "$ROOT/.runtime/pgdata" ]; then
  if ! "$ROOT/.runtime/postgres/bin/pg_ctl" -D "$ROOT/.runtime/pgdata" status >/dev/null 2>&1; then
    "$ROOT/.runtime/postgres/bin/pg_ctl" -D "$ROOT/.runtime/pgdata" -l "$ROOT/.runtime/postgres.log" start
  fi
fi
if [ ! -x backend/.venv/bin/python ]; then
  echo "Backend virtual environment missing. Follow README.md setup instructions." >&2
  exit 1
fi
backend/.venv/bin/python - <<'PY'
import socket
for port in (8001,5173):
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',port))
        except OSError:raise SystemExit(f'Port {port} is already in use. If Polaris is already running, open http://127.0.0.1:5173 instead.')
PY
backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001 --reload --reload-dir backend/app &
API_PID=$!
npm --prefix frontend run dev &
UI_PID=$!
cleanup() { kill "$API_PID" "$UI_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
echo "Polaris MIS: http://127.0.0.1:5173 | API: http://127.0.0.1:8001/api/docs"
wait
