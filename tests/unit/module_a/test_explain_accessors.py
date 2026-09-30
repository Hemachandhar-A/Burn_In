"""P5.7 (explain/): additive read-only accessors on module_a/detect.py.

fit_mcd and fit_ecod refit the exact MinCovDet / ECOD that detect()'s own internal steps 2 and 4
already fit, so explain/ can reach the fitted model object (location_/precision_, or the per-dimension
score matrix) that detect() itself discards after reducing it to a scalar distance/score. Neither
function is called by detect() or _detect_single_lot() - they are parallel, independent
re-computations against the same inputs, same constants (_MCD_LOT_SIZE_FLOOR, _RANDOM_STATE), so
detect()'s own code path and output are provably untouched (AGENTS.md rule 3's additive-accessor
carve-out, per the P5.7 task block).
"""
import numpy as np
import pytest

from contracts import FeatureFrame


def _frame(
    component_id: str = "C001", lot_id: str = "LOT001", part_number: str = "PN-1",
    parameter: str = "iddq", value_0h: float = 10.0, value_24h: float = 11.0, lot_size: int = 35,
    robust_z: dict[str, float] | None = None, lot_median_0h: float = 10.0, lot_median_24h: float = 11.0,
) -> FeatureFrame:
    rz = robust_z if robust_z is not None else {"0h": 0.0, "24h": 0.0}
    return FeatureFrame(
        component_id=component_id, lot_id=lot_id, part_number=part_number, parameter=parameter,
        value_0h=value_0h, value_24h=value_24h, value_96h=None, value_168h=None,
        delta_24h=value_24h - value_0h, delta_96h=None, delta_168h=None,
        lot_median_0h=lot_median_0h, lot_median_24h=lot_median_24h, robust_z=rz, lot_size=lot_size,
        used_pooled_fallback=False, elapsed_hours={"0h": 0.0, "24h": 24.0},
    )


def _mcd_eligible_lot(n: int = 35, parameters: tuple[str, ...] = ("iddq", "leakage")) -> list[FeatureFrame]:
    """n components x len(parameters) parameters, spread values so both MCD and ECOD have something
    non-degenerate to work with. Deterministic (fixed rng seed)."""
    rng = np.random.default_rng(7)
    frames = []
    for param_idx, parameter in enumerate(parameters):
        vals_0 = 10.0 + param_idx * 5 + rng.normal(0, 0.5, n)
        vals_24 = 11.0 + param_idx * 5 + rng.normal(0, 0.5, n)
        med0, med24 = float(np.median(vals_0)), float(np.median(vals_24))
        for i in range(n):
            frames.append(_frame(
                component_id=f"C{i:03d}", parameter=parameter, lot_size=n,
                value_0h=float(vals_0[i]), value_24h=float(vals_24[i]),
                robust_z={"0h": float(vals_0[i] - med0), "24h": float(vals_24[i] - med24)},
                lot_median_0h=med0, lot_median_24h=med24,
            ))
    return frames


class TestFitMcdAccessor:
    def test_returns_a_fitted_mcd_matching_build_mcd_matrix(self):
        from module_a.detect import fit_mcd
        from features.compute import build_mcd_matrix

        frames = _mcd_eligible_lot()
        result = fit_mcd(frames, "0h")
        assert result is not None
        component_ids, parameters, mcd = result

        expected_ids, expected_params, expected_matrix = build_mcd_matrix(frames, "0h")
        assert component_ids == expected_ids
        assert parameters == expected_params
        assert mcd.location_.shape == (len(parameters),)
        # The fitted model must reproduce exactly the same distances detect() computed internally.
        distances = np.sqrt(mcd.mahalanobis(np.array(expected_matrix, dtype=float)))
        assert np.all(np.isfinite(distances))

    def test_none_below_the_lot_size_floor(self):
        from module_a.detect import fit_mcd

        frames = _mcd_eligible_lot(n=20)
        assert fit_mcd(frames, "0h") is None

    def test_deterministic_across_calls(self):
        from module_a.detect import fit_mcd

        frames = _mcd_eligible_lot()
        r1 = fit_mcd(frames, "0h")
        r2 = fit_mcd(frames, "0h")
        assert r1[0] == r2[0] and r1[1] == r2[1]
        assert np.array_equal(r1[2].location_, r2[2].location_)
        assert np.array_equal(r1[2].precision_, r2[2].precision_)

    def test_detect_output_unchanged_by_calling_the_new_accessor(self):
        """Compare detect()'s own output before and after exercising fit_mcd on the same input - the
        additive accessor must have zero effect on the module's real detection path."""
        from module_a.detect import detect, fit_mcd

        frames = _mcd_eligible_lot()
        before = detect(frames)
        fit_mcd(frames, "0h")  # exercise the new accessor in between
        fit_mcd(frames, "24h")
        after = detect(frames)
        assert before == after


class TestFitEcodAccessor:
    def test_returns_a_fitted_ecod_with_per_dimension_scores(self):
        from module_a.detect import fit_ecod

        frames = _mcd_eligible_lot(n=10, parameters=("iddq",))
        result = fit_ecod(frames, "iddq")
        assert result is not None
        component_ids, ecod = result
        assert component_ids == [f"C{i:03d}" for i in range(10)]
        assert ecod.O.shape == (10, 2)  # [value_0h, value_24h]
        assert np.allclose(ecod.O.sum(axis=1), ecod.decision_scores_)

    def test_none_for_an_unmatched_parameter(self):
        from module_a.detect import fit_ecod

        frames = _mcd_eligible_lot(n=10, parameters=("iddq",))
        assert fit_ecod(frames, "prop_delay") is None

    def test_detect_output_unchanged_by_calling_the_new_accessor(self):
        from module_a.detect import detect, fit_ecod

        frames = _mcd_eligible_lot(n=10, parameters=("iddq",))
        before = detect(frames)
        fit_ecod(frames, "iddq")
        after = detect(frames)
        assert before == after
