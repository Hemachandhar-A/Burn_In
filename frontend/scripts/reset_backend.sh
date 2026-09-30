#!/usr/bin/env bash
# Fresh own-backend for live smoke/screenshot runs: port 8001, burnin_front.db (gitignored).
# Run from the worktree root. Uses the main repo's interpreter by absolute path.
set -e
PY=D:/PS1_SIH2026/.venv/Scripts/python.exe
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | % { Stop-Process -Id \$_.OwningProcess -Force }" || true
sleep 2
rm -f burnin_front.db
export DATABASE_URL=sqlite:///./burnin_front.db
export JWT_SECRET="$(grep ^JWT_SECRET .env | cut -d= -f2)"
$PY -m scripts.seed >/dev/null
nohup $PY -m uvicorn api.main:app --port 8001 > uvicorn.log 2>&1 &
for i in $(seq 1 30); do curl -sf localhost:8001/health >/dev/null && break; sleep 1; done
curl -s -w " /health %{http_code}\n" localhost:8001/health
