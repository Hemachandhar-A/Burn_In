"""G0 smoke tests: contracts import cleanly and the API skeleton answers /health."""
from fastapi.testclient import TestClient

import contracts
from api.main import app


def test_health_returns_ok():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_vite_dev_origin():
    response = TestClient(app).options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_screening_config_defaults_match_plan():
    cfg = contracts.ScreeningConfig()
    assert cfg.fn_fp_cost_ratio == 10.0
    assert cfg.pda_threshold == 0.05
    assert cfg.small_lot_fallback_threshold == 30
    assert cfg.lot_size_default == 77


def test_verdict_vocabularies_are_closed():
    # AGENTS.md rule 10: never invent new status words.
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        contracts.RiskAssessment(
            component_id="c", lot_id="l", verdict="MAYBE", module_a_rank=0, module_b_rank=0, worst_parameter="iddq"
        )
