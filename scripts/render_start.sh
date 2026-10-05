#!/usr/bin/env bash
# Container start for Render: reseed an empty database, load the two demo lots, serve on $PORT.
# The frontend is already built into the image (see Dockerfile). Requires JWT_SECRET in the environment.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${JWT_SECRET:?JWT_SECRET must be set}"
export DATABASE_URL="${DATABASE_URL:-sqlite:////tmp/burnin.db}"
rm -f /tmp/burnin.db
python -m scripts.seed
python -m scripts.load_demo_lots
exec python -m uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
