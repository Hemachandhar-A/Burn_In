"""FastAPI application instance (Lead-owned).

App instance, CORS for the Vite dev origin, /health, and router registration. A router is
registered here in the same merge that introduces it (IMPLEMENTATION_PLAN.md Part 8) - a merged
session is not a reachable route. The built frontend (frontend/dist) is mounted last, by api/static.py,
when it exists (scripts/build_demo.sh).
"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from capa.router import planned_router as capa_router
from fusion.router import router as fusion_router
from identity.auth import get_current_account
from identity.router import router as identity_router
from ingestion.router import router as ingestion_router
from report.router import router as report_router
from api.static import mount_frontend
from storage.repository import init_db
from storage.router import router as storage_router

VITE_DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Safety net, not the primary path: scripts/seed.py is what every developer is documented to run first
# (AGENTS.md), and it already creates the schema. Base.metadata.create_all() is idempotent (CREATE TABLE
# IF NOT EXISTS), so calling it again here costs nothing when seed.py already ran, and closes the gap
# structurally for any code path - the app itself, a test, a script - that imports api.main without
# seed.py having run first (CONTRACT_CHANGES.md, 2026-09-27 Lead entry).
init_db()

app = FastAPI(title="Burn-In Screening API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=VITE_DEV_ORIGINS,
    allow_credentials=False,  # JWT travels in the Authorization header, never a cookie (AGENTS.md rule 13)
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth policy (G5 findings 1/3/4): these four routers are registered behind get_current_account here, at
# app level, so router-only unit tests keep working without a token. /auth/login (identity router) and
# /health stay open; identity/capa routes already declare the dependency per route.
_auth = [Depends(get_current_account)]
app.include_router(ingestion_router, dependencies=_auth)
app.include_router(storage_router, dependencies=_auth)
app.include_router(report_router, dependencies=_auth)
app.include_router(fusion_router, dependencies=_auth)
app.include_router(identity_router)
app.include_router(capa_router)


@app.api_route("/health", methods=["GET", "HEAD"], tags=["meta"])  # HEAD: uptime monitors (deploy-demo)
def health() -> dict[str, str]:
    return {"status": "ok"}


# LAST registration, after every router and /health: serves frontend/dist when it has been built (scripts/
# build_demo.sh). No-op otherwise, so the dev loop (Vite on :5173) and the tests are unaffected.
mount_frontend(app)
