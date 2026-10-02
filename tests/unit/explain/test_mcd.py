"""P5.7 (explain/mcd.py): per-parameter contribution to squared Mahalanobis distance."""
import numpy as np
import pytest

from contracts import FeatureFrame
from explain.mcd import explain_mcd
from explain.models import MCDExplanation
from module_a.detect import fit_mcd


def _frame(
    component_id: str, parameter: str, value_0h: float, lot_median_0h: float, lot_size: int = 35,
) -> FeatureFrame:
    return FeatureFrame(
        component_id=component_id, lot_id="LOT001", part_number="PN-1", parameter=parameter,
        value_0h=value_0h, value_24h=value_0h + 1.0, value_96h=None, value_168h=None,
        delta_24h=1.0, delta_96h=None, delta_168h=None,
        lot_median_0h=lot_median_0h, lot_median_24h=lot_median_0h + 1.0,
        robust_z={"0h": value_0h - lot_median_0h, "24h": value_0h - lot_median_0h},
        lot_size=lot_size, used_pooled_fallback=False, elapsed_hours={"0h": 0.0, "24h": 24.0},
    )


def _mcd_eligible_lot(n: int = 35, parameters: tuple[str, ...] = ("iddq", "leakage")) -> list[FeatureFrame]:
    rng = np.random.default_rng(11)
    frames = []
    for param_idx, parameter in enumerate(parameters):
        vals = 10.0 + param_idx * 5 + rng.normal(0, 0.5, n)
        med = float(np.median(vals))
        for i in range(n):
            frames.append(_frame(f"C{i:03d}", parameter, float(vals[i]), med, lot_size=n))
    # An extra outlier component, present on every parameter, with an extreme value on one of them.
    for parameter in parameters:
        offset = 20.0 if parameter == parameters[0] else 0.0
        frames.append(_frame("OUTLIER", parameter, 10.0 + offset, 10.0, lot_size=n + 1))
    return frames


def test_returns_an_mcd_explanation_for_a_known_component():
    frames = _mcd_eligible_lot()
    result = explain_mcd(frames, "0h", "OUTLIER")
    assert isinstance(result, MCDExplanation)
    assert result.component_id == "OUTLIER"
    assert result.checkpoint == "0h"
    assert {c.parameter for c in result.contributions} == {"iddq", "leakage"}


def test_contributions_sum_to_the_mcd_squared_mahalanobis_distance():
    """d^2 = sum_i (x_i - mu_i) * [Sigma^-1 (x - mu)]_i, using the fitted MCD's own location_/precision_ -
    contributions must sum to mcd.mahalanobis(x) for that row, within 1e-9."""
    frames = _mcd_eligible_lot()
    component_ids, parameters, mcd = fit_mcd(frames, "0h")
    idx = component_ids.index("OUTLIER")
    from features.compute import build_mcd_matrix

    _, _, matrix = build_mcd_matrix(frames, "0h")
    expected_d2 = float(mcd.mahalanobis(np.array([matrix[idx]], dtype=float))[0])

    result = explain_mcd(frames, "0h", "OUTLIER")
    total = sum(c.contribution for c in result.contributions)
    assert total == pytest.approx(expected_d2, abs=1e-9)
    assert result.mahalanobis_distance_squared == pytest.approx(expected_d2, abs=1e-9)


def test_outlier_parameter_has_the_largest_contribution():
    frames = _mcd_eligible_lot()
    result = explain_mcd(frames, "0h", "OUTLIER")
    top = result.contributions[0]
    assert top.parameter == "iddq"  # the parameter OUTLIER was perturbed on


def test_contributions_sorted_by_absolute_value_descending():
    frames = _mcd_eligible_lot()
    result = explain_mcd(frames, "0h", "OUTLIER")
    magnitudes = [abs(c.contribution) for c in result.contributions]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_raises_when_mcd_did_not_run():
    frames = _mcd_eligible_lot(n=10)  # below the lot-size floor
    with pytest.raises(ValueError):
        explain_mcd(frames, "0h", "C000")


def test_raises_for_an_unknown_component():
    frames = _mcd_eligible_lot()
    with pytest.raises(ValueError):
        explain_mcd(frames, "0h", "NOT-A-REAL-COMPONENT")
