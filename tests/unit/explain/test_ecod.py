"""P5.7 (explain/ecod.py): per-dimension ECOD tail scores for one part.

Identity used: PyOD's ECOD aggregates its per-dimension score matrix `.O` by summing across
dimensions - decision_scores_ = O.sum(axis=1) (pyod/models/ecod.py:152/154/216, both the sequential
and the parallel decision_function path). Per-dimension contributions must reproduce that sum.
"""
import numpy as np
import pytest

from contracts import FeatureFrame
from explain.ecod import explain_ecod
from explain.models import EcodExplanation


def _frame(component_id: str, value_0h: float, value_24h: float, lot_size: int) -> FeatureFrame:
    return FeatureFrame(
        component_id=component_id, lot_id="LOT001", part_number="PN-1", parameter="iddq",
        value_0h=value_0h, value_24h=value_24h, value_96h=None, value_168h=None,
        delta_24h=value_24h - value_0h, delta_96h=None, delta_168h=None,
        lot_median_0h=10.0, lot_median_24h=11.0, robust_z={"0h": 0.0, "24h": 0.0},
        lot_size=lot_size, used_pooled_fallback=False, elapsed_hours={"0h": 0.0, "24h": 24.0},
    )


def _lot(n: int = 10) -> list[FeatureFrame]:
    rng = np.random.default_rng(3)
    vals_0 = 10.0 + rng.normal(0, 0.5, n)
    vals_24 = 11.0 + rng.normal(0, 0.5, n)
    frames = [_frame(f"C{i:03d}", float(vals_0[i]), float(vals_24[i]), n) for i in range(n)]
    frames.append(_frame("OUTLIER", 100.0, 110.0, n + 1))  # extreme right-tail on both dimensions
    return frames


def test_returns_an_ecod_explanation():
    frames = _lot()
    result = explain_ecod(frames, "iddq", "OUTLIER")
    assert isinstance(result, EcodExplanation)
    assert result.component_id == "OUTLIER"
    assert result.parameter == "iddq"
    assert [c.dimension for c in result.contributions] == ["value_0h", "value_24h"]


def test_per_dimension_scores_reproduce_the_aggregated_ecod_score():
    """The identity PyOD itself uses: decision_scores_ = O.sum(axis=1)."""
    frames = _lot()
    result = explain_ecod(frames, "iddq", "OUTLIER")
    total = sum(c.score for c in result.contributions)
    assert total == pytest.approx(result.aggregated_score, abs=1e-9)


def test_matches_the_module_a_computed_ecod_score():
    """Cross-check against module_a.detect's own ecod_score for the same part - fit_ecod must
    reproduce exactly what detect() computed internally, not a different fit."""
    from module_a.detect import detect

    frames = _lot()
    results = detect(frames)
    outlier_result = next(r for r in results if r.component_id == "OUTLIER")
    explanation = explain_ecod(frames, "iddq", "OUTLIER")
    assert explanation.aggregated_score == pytest.approx(outlier_result.ecod_score, abs=1e-9)


def test_deterministic_across_calls():
    frames = _lot()
    r1 = explain_ecod(frames, "iddq", "OUTLIER")
    r2 = explain_ecod(frames, "iddq", "OUTLIER")
    assert r1 == r2


def test_raises_for_an_unmatched_parameter():
    frames = _lot()
    with pytest.raises(ValueError):
        explain_ecod(frames, "prop_delay", "OUTLIER")


def test_raises_for_an_unknown_component():
    frames = _lot()
    with pytest.raises(ValueError):
        explain_ecod(frames, "iddq", "NOT-A-REAL-COMPONENT")
