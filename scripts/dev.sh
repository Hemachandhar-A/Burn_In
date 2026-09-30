#!/usr/bin/env bash
# Two-process dev loop: uvicorn --reload (backend) + Vite (frontend). Ctrl-C stops both.
#
#   scripts/dev.sh [--dry-run]
#
# Env: BACKEND_PORT (default 8000), FRONTEND_PORT (default 5173), DATABASE_URL, JWT_SECRET.
# The backend's CORS allows exactly http://localhost:5173 (api/main.py), so Vite runs with --strictPort on
# 5173: if that port is taken it fails instead of silently moving to one the backend would reject.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///./burnin.db}"

if [[ -n "${PYTHON:-}" ]]; then PY="$PYTHON"
elif [[ -x .venv/Scripts/python.exe ]]; then PY=.venv/Scripts/python.exe
elif [[ -x .venv/bin/python ]]; then PY=.venv/bin/python
else PY=python; fi

if [[ "$FRONTEND_PORT" != "5173" ]]; then
  echo "note: FRONTEND_PORT=$FRONTEND_PORT, but backend CORS only allows http://localhost:5173 - forcing 5173." >&2
  FRONTEND_PORT=5173
fi
if [[ -z "${JWT_SECRET:-}" ]]; then
  echo "warning: JWT_SECRET is unset - the insecure dev default is in use (fine for local dev only)." >&2
fi

BACKEND_CMD=("$PY" -m uvicorn api.main:app --reload --port "$BACKEND_PORT")
FRONTEND_CMD=(npm run dev -- --port 5173 --strictPort)

if [[ $DRY_RUN -eq 1 ]]; then
  echo "[dry-run] DATABASE_URL=$DATABASE_URL"
  echo "[dry-run] (root)      ${BACKEND_CMD[*]}"
  echo "[dry-run] (frontend/) ${FRONTEND_CMD[*]}"
  exit 0
fi

echo "Backend : http://localhost:${BACKEND_PORT}   (docs: /docs)"
echo "Frontend: http://localhost:${FRONTEND_PORT}   (Vite --strictPort)"
echo "Demo logins (from scripts/seed.py; run 'python -m scripts.seed' once if the database is new):"
"$PY" -c "from scripts.seed import ACCOUNTS; [print(f'  {a[\"account_id\"]} / {a[\"pin\"]}  ({a[\"role\"]})') for a in ACCOUNTS]"

PIDS=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${PIDS[@]:-}"; do [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"${BACKEND_CMD[@]}" & PIDS+=($!)
(cd frontend && "${FRONTEND_CMD[@]}") & PIDS+=($!)
wait -n
