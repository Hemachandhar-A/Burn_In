"""Serve the built frontend (frontend/dist) from the API process - the single-process demo (Part 5.6).

Called once by api/main.py AFTER every router is registered: Starlette matches routes in registration order, so a
"/" mount placed last only catches what no API route, /docs, /openapi.json or /health claimed. The screens use a
HashRouter, so no SPA history fallback is needed. Assets are public; API routes keep their own auth.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

DEFAULT_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def mount_frontend(app: FastAPI, dist_dir: Path = DEFAULT_DIST_DIR) -> bool:
    """Mount `dist_dir` at "/" (html=True). Returns False, mounting nothing, unless it holds an index.html."""
    dist_dir = Path(dist_dir)
    if not (dist_dir / "index.html").is_file():
        return False
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
    return True
