"""Guards the L2 rule: a merged router is not a live route until api/main.py registers it.
Checks the OpenAPI schema the frontend's client is generated from, not the routers' own modules."""
from api.main import app


def _paths() -> dict:
    return app.openapi()["paths"]


def test_ingestion_routes_are_in_the_openapi_schema():
    paths = _paths()
    assert "post" in paths["/lots"]
    assert "post" in paths["/lots/demo"]
    assert "post" in paths["/lots/{lot_id}/checkpoints"]


def test_storage_and_report_routes_are_in_the_openapi_schema():
    paths = _paths()
    # NOTE: Part 5.6 specifies global GET /events and GET /disposition-signoffs; P2.8 built them
    # per-project. Open decision logged in CONTRACT_CHANGES.md - update this test when it is settled.
    assert {"/projects", "/projects/{project_id}"} <= set(paths)
    assert "/projects/{project_id}/events" in paths
    assert "/projects/{project_id}/disposition-signoffs" in paths
    assert "post" in paths["/lots/{lot_id}/report"]
