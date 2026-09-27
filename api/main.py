"""FastAPI application instance (Lead-owned).

App instance, CORS for the Vite dev origin, /health, and router registration. A router is
registered here in the same merge that introduces it (IMPLEMENTATION_PLAN.md Part 8) - a merged
session is not a reachable route. The StaticFiles mount for the built frontend is added in L3
(scripts/build_demo.sh).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ingestion.router import router as ingestion_router
from report.router import router as report_router
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

app.include_router(ingestion_router)
app.include_router(storage_router)
app.include_router(report_router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
