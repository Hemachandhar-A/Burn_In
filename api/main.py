"""FastAPI application instance (Lead-owned).

Skeleton only: app instance, CORS for the Vite dev origin, and /health. Routers are
registered here by the Lead as each one lands (session L2); the StaticFiles mount for
the built frontend is added in L3 (scripts/build_demo.sh).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

VITE_DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

app = FastAPI(title="Burn-In Screening API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=VITE_DEV_ORIGINS,
    allow_credentials=False,  # JWT travels in the Authorization header, never a cookie (AGENTS.md rule 13)
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
