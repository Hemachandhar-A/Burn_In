#!/usr/bin/env bash
# Build and serve the demo from ONE process: reseed, build the frontend, prewarm, run uvicorn (no --reload).
#
#   scripts/build_demo.sh [--port N] [--no-reseed] [--dry-run]
#
# Env: JWT_SECRET (default: random 48 chars), DATABASE_URL (default sqlite:///./burnin.db).
#
# TODO (chunk 2): requires api/main.py to serve frontend/dist (StaticFiles mount) - not there yet, so until
# then this serves the API only and the built frontend is not reachable from the same port.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PORT=8000
RESEED=1
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:?--port needs a value}"; shift 2 ;;
    --no-reseed) RESEED=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

if [[ -n "${PYTHON:-}" ]]; then PY="$PYTHON"
elif [[ -x .venv/Scripts/python.exe ]]; then PY=.venv/Scripts/python.exe
elif [[ -x .venv/bin/python ]]; then PY=.venv/bin/python
else PY=python; fi

export DATABASE_URL="${DATABASE_URL:-sqlite:///./burnin.db}"
if [[ -z "${JWT_SECRET:-}" ]]; then
  JWT_SECRET="$("$PY" -c "import secrets,string; a=string.ascii_letters+string.digits; print(''.join(secrets.choice(a) for _ in range(48)))")"
  JWT_SECRET_SOURCE="random 48-character value generated for this run"
else
  JWT_SECRET_SOURCE="from the environment"
fi
export JWT_SECRET

# The sqlite file behind DATABASE_URL (only for sqlite:///path URLs).
DB_FILE=""
[[ "$DATABASE_URL" == sqlite:///* ]] && DB_FILE="${DATABASE_URL#sqlite:///}"

STAMP="$(date +%Y%m%d-%H%M%S)"
STEPS=()
if [[ $RESEED -eq 1 ]]; then
  [[ -n "$DB_FILE" ]] && STEPS+=("mv $DB_FILE $DB_FILE.bak-$STAMP   (only if it exists)")
  STEPS+=("$PY -m scripts.seed")
fi
STEPS+=("(cd frontend && npm ci && npm run build)")
STEPS+=("$PY -m scripts.prewarm")
STEPS+=("exec $PY -m uvicorn api.main:app --host 0.0.0.0 --port $PORT")

SERVES_DIST=0
grep -q "StaticFiles(" api/main.py && SERVES_DIST=1

if [[ $DRY_RUN -eq 1 ]]; then
  echo "[dry-run] DATABASE_URL=$DATABASE_URL"
  echo "[dry-run] JWT_SECRET: $JWT_SECRET_SOURCE (value not printed)"
  for s in "${STEPS[@]}"; do echo "[dry-run] $s"; done
  if [[ $SERVES_DIST -eq 0 ]]; then
    echo "!!! WARNING: api/main.py does not mount StaticFiles, so frontend/dist would NOT be served (chunk 2)." >&2
  fi
  exit 0
fi

if [[ $RESEED -eq 1 ]]; then
  if [[ -n "$DB_FILE" && -f "$DB_FILE" ]]; then mv "$DB_FILE" "$DB_FILE.bak-$STAMP"; echo "backed up $DB_FILE"; fi
  "$PY" -m scripts.seed
fi
(cd frontend && npm ci && npm run build)
"$PY" -m scripts.prewarm

echo "Demo: http://localhost:${PORT}"
"$PY" -c "from scripts.seed import ACCOUNTS; [print(f'  {a[\"account_id\"]} / {a[\"pin\"]}  ({a[\"role\"]})') for a in ACCOUNTS]"
if [[ $SERVES_DIST -eq 0 ]]; then
  echo "!!! WARNING: api/main.py does not mount StaticFiles - frontend/dist is built but NOT served yet (chunk 2)." >&2
fi
exec "$PY" -m uvicorn api.main:app --host 0.0.0.0 --port "$PORT"
