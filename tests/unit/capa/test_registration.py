"""Block 4a Part 6a: api/main.py registers capa.router.planned_router (the four E13 routes
IMPLEMENTATION_PLAN.md's route table actually names for capa/router.py) and only that - the three
pre-existing, unplanned TEMP_ routes on capa.router.router (GET /capa, POST /capa/{id}/resolve,
GET /audit/export) stay unregistered, and no TEMP_ schema name reaches the OpenAPI schema."""
from api.main import app


def _paths() -> dict:
    return app.openapi()["paths"]


def _schema_names() -> set[str]:
    return set(app.openapi()["components"]["schemas"].keys())


def test_the_four_planned_capa_routes_are_registered():
    paths = _paths()
    assert "post" in paths["/parts/{component_id}/confirmed-outcome"]
    assert "get" in paths["/settings/worklist"]
    assert "get" in paths["/settings/corrective-status"]
    assert "post" in paths["/lots/{lot_id}/dpa-work-order"]


def test_the_unplanned_temp_capa_routes_are_not_registered():
    paths = _paths()
    assert "/capa" not in paths
    assert "/capa/{id}/resolve" not in paths
    assert "/audit/export" not in paths


def test_no_temp_schema_name_reaches_the_openapi_schema():
    names = _schema_names()
    assert not any(name.startswith("TEMP_") for name in names)
