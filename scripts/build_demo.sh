#!/usr/bin/env bash
# Build and serve the demo from ONE process: reseed, load the two demo lots, build the frontend, prewarm, run
# uvicorn (no --reload). FastAPI serves frontend/dist itself (api/static.py), so there is one origin and one port.
#
#   scripts/build_demo.sh [--port N] [--no-reseed] [--no-demo-lots] [--dry-run]
#
# Env: JWT_SECRET (default: random 48 chars), DATABASE_URL (default sqlite:///./burnin.db), PYTHON.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PORT=8000
RESEED=1
DEMO_LOTS=1
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:?--port needs a value}"; shift 2 ;;
    --no-reseed) RESEED=0; shift ;;
    --no-demo-lots) DEMO_LOTS=0; shift ;;
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
[[ $DEMO_LOTS -eq 1 ]] && STEPS+=("$PY -m scripts.load_demo_lots")
STEPS+=("(cd frontend && npm ci && npm run build)")
STEPS+=("$PY -m scripts.prewarm")
STEPS+=("exec $PY -m uvicorn api.main:app --host 0.0.0.0 --port $PORT")

if [[ $DRY_RUN -eq 1 ]]; then
  echo "[dry-run] DATABASE_URL=$DATABASE_URL"
  echo "[dry-run] JWT_SECRET: $JWT_SECRET_SOURCE (value not printed)"
  for s in "${STEPS[@]}"; do echo "[dry-run] $s"; done
  exit 0
fi

if [[ $RESEED -eq 1 ]]; then
  if [[ -n "$DB_FILE" && -f "$DB_FILE" ]]; then mv "$DB_FILE" "$DB_FILE.bak-$STAMP"; echo "backed up $DB_FILE"; fi
  "$PY" -m scripts.seed
fi
[[ $DEMO_LOTS -eq 1 ]] && "$PY" -m scripts.load_demo_lots
(cd frontend && npm ci && npm run build)
if [[ ! -f frontend/dist/index.html ]]; then
  echo "error: frontend/dist/index.html is missing after the build - the API would serve no UI." >&2
  exit 1
fi
"$PY" -m scripts.prewarm

echo "Demo ready: http://localhost:${PORT}"
"$PY" -c "from scripts.seed import ACCOUNTS; [print(f'  {a[\"account_id\"]} / {a[\"pin\"]}  ({a[\"role\"]})') for a in ACCOUNTS]"
[[ $DEMO_LOTS -eq 1 ]] && "$PY" -c "from scripts.load_demo_lots import COMPLETE_LOT_ID, EARLY_LOT_ID; print(f'  demo lots: {COMPLETE_LOT_ID} (complete), {EARLY_LOT_ID} (in progress)')"
exec "$PY" -m uvicorn api.main:app --host 0.0.0.0 --port "$PORT"
