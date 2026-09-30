"""api.static.mount_frontend: the built SPA is served at "/" as the LAST registration, never shadowing an API route,
/docs, /openapi.json or /health, and never adding auth to (or removing it from) anything."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.static import mount_frontend


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><html><body>SPA-INDEX</body></html>", encoding="utf-8")
    (d / "assets" / "app-abc123.js").write_text("console.log('asset')", encoding="utf-8")
    return d


def _real_routes_without_frontend() -> FastAPI:
    """The real app's routes, minus any frontend mount api/main.py made at import (it mounts frontend/dist when
    that has been built on this machine), so these tests do not depend on whether a build exists."""
    from api.main import app as real
    fresh = FastAPI(routes=[r for r in real.routes if getattr(r, "name", None) != "frontend"], title=real.title)
    fresh.user_middleware = list(real.user_middleware)
    return fresh


def _app_with_dist(dist_dir) -> FastAPI:
    """Those routes, then the same mount call api/main.py makes."""
    fresh = _real_routes_without_frontend()
    assert mount_frontend(fresh, dist_dir) is True
    return fresh


def test_index_and_assets_are_public(dist):
    client = TestClient(_app_with_dist(dist))
    root = client.get("/")
    assert root.status_code == 200 and "text/html" in root.headers["content-type"] and "SPA-INDEX" in root.text
    asset = client.get("/assets/app-abc123.js")
    assert asset.status_code == 200 and "asset" in asset.text


def test_api_routes_are_not_shadowed(dist):
    client = TestClient(_app_with_dist(dist))
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"]
    assert client.get("/projects").status_code == 401  # API auth untouched
    assert client.post("/lots").status_code == 401
    assert client.post("/auth/login", json={}).status_code == 422  # reaches the real route


def test_missing_dist_dir_mounts_nothing(tmp_path):
    app = FastAPI()
    before = len(app.routes)
    assert mount_frontend(app, tmp_path / "nope") is False
    assert len(app.routes) == before


def test_missing_index_html_mounts_nothing(tmp_path):
    (tmp_path / "empty").mkdir()
    assert mount_frontend(FastAPI(), tmp_path / "empty") is False


def test_app_without_dist_is_json_404_and_starts():
    client = TestClient(_real_routes_without_frontend())
    assert client.get("/health").status_code == 200
    r = client.get("/definitely-not-a-route")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_mount_is_registered_last(dist):
    app = FastAPI()

    @app.get("/x")
    def x():
        return {}

    mount_frontend(app, dist)
    assert app.routes[-1].name == "frontend"
