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


def test_unrecognized_parameter_is_a_valid_reading():
    # context.md 5.9: an unknown parameter must be accepted, never rejected by the type.
    r = contracts.Reading(
        component_id="c1", lot_id="L1", part_number="P", manufacturer="m", date_code="2601",
        parameter="gain", checkpoint_hour=0.0, value=1.0, unit="dB",
    )
    assert r.parameter == "gain"


def test_feature_frame_is_scoped_to_one_component_parameter_pair():
    frame = contracts.FeatureFrame(
        component_id="c1", lot_id="L1", part_number="P", parameter="iddq",
        value_0h=1.0, value_24h=1.1, value_96h=None, delta_24h=0.1, delta_96h=None,
        lot_median_0h=1.0, lot_median_24h=1.05,
        robust_z={"0h": 0.0, "24h": 0.4}, lot_size=77, used_pooled_fallback=False,
        elapsed_hours={"0h": 0.0, "24h": 24.5},
    )
    assert (frame.part_number, frame.parameter) == ("P", "iddq")
    assert frame.elapsed_hours["24h"] == 24.5
