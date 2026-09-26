"""Edge-case hardening for E2 steps 1-3 — beyond the Part 7.3 named checklist rows.

Session: P3.1 hardening (between P3.1 and P3.2)

Each test class documents the specific risk being probed and whether it was a
real finding (code needed fixing) or confirmed-already-correct.

Risks investigated:
  A. Determinism         — already covered in test_p31.py; confirmed here is moot.
  B. Single-parameter MCD (rank-deficient covariance) — mcd_tag correctness not
     previously asserted; added here.
  C. Lot of exactly 1 part — not tested at all; added.
  D. used_pooled_fallback=True frames — robust_z passthrough correctness; added.
  E. Mixed recognized + unrecognized parameters — MCD exclusion of components that
     lack all parameters at a checkpoint; added.
  F. Dead-code finding: mcd_ran variable in detect.py computed but never used —
     not a behavioural bug, but logged in a comment; no test needed (it's an
     unused variable, not an incorrect output).
"""

import math
import numpy as np
import pytest

from contracts import FeatureFrame, ModuleAResult


# ---------------------------------------------------------------------------
# Shared fixture helpers (kept minimal — no duplication with test_p31.py)
# ---------------------------------------------------------------------------

def _frame(
    component_id: str = "C001",
    lot_id: str = "LOT001",
    part_number: str = "PN-1",
    parameter: str = "iddq",
    value_0h: float = 10.0,
    value_24h: float = 11.0,
    lot_size: int = 50,
    used_pooled_fallback: bool = False,
    robust_z: dict[str, float] | None = None,
    lot_median_0h: float = 10.0,
    lot_median_24h: float = 11.0,
) -> FeatureFrame:
    rz = robust_z if robust_z is not None else {"0h": 0.0, "24h": 0.0}
    return FeatureFrame(
        component_id=component_id,
        lot_id=lot_id,
        part_number=part_number,
        parameter=parameter,
        value_0h=value_0h,
        value_24h=value_24h,
        value_96h=None,
        value_168h=None,
        delta_24h=value_24h - value_0h,
        delta_96h=None,
        delta_168h=None,
        lot_median_0h=lot_median_0h,
        lot_median_24h=lot_median_24h,
        robust_z=rz,
        lot_size=lot_size,
        used_pooled_fallback=used_pooled_fallback,
        elapsed_hours={"0h": 0.0, "24h": 24.0},
    )


def _lot_of(n: int, parameter: str = "iddq", lot_id: str = "LOT001",
            part_number: str = "PN-1", seed: int = 0) -> list[FeatureFrame]:
    """n frames with deterministic, spread values so IQR > 0."""
    rng = np.random.default_rng(seed)
    vals_0 = 10.0 + rng.normal(0, 0.5, n)
    vals_24 = 11.0 + rng.normal(0, 0.5, n)
    med0, med24 = float(np.median(vals_0)), float(np.median(vals_24))
    q75_0, q25_0 = np.percentile(vals_0, [75, 25])
    q75_24, q25_24 = np.percentile(vals_24, [75, 24])
    sig0 = max((q75_0 - q25_0) / 1.35, 1e-9)
    sig24 = max((q75_24 - q25_24) / 1.35, 1e-9)
    return [
        _frame(
            component_id=f"C{i:03d}",
            lot_id=lot_id,
            part_number=part_number,
            parameter=parameter,
            value_0h=float(vals_0[i]),
            value_24h=float(vals_24[i]),
            lot_size=n,
            robust_z={"0h": (vals_0[i] - med0) / sig0,
                      "24h": (vals_24[i] - med24) / sig24},
            lot_median_0h=med0,
            lot_median_24h=med24,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# B. Single-parameter lot — mcd_tag correctness (not previously asserted)
# ---------------------------------------------------------------------------

class TestSingleParameterMCD:
    """Risk B: When a lot has only one parameter, the MCD matrix is (n, 1).
    MinCovDet warns about rank-deficiency but completes. Previously only checked
    that mcd_distance is not None; now also assert mcd_tag is True.

    Finding: confirmed-already-correct. No code change needed."""

    def test_mcd_tag_true_for_single_parameter_large_lot(self):
        from module_a.detect import detect

        frames = _lot_of(35, parameter="iddq")
        results = detect(frames)
        # mcd ran (lot_size=35 >= 30, 1 parameter) → tag must be True
        assert all(r.explainable_tags["mcd"] is True for r in results), (
            "mcd_tag should be True when MCD ran on a single-parameter lot"
        )

    def test_mcd_distance_non_negative_single_parameter(self):
        from module_a.detect import detect

        frames = _lot_of(35, parameter="leakage")
        results = detect(frames)
        assert all(r.mcd_distance is not None for r in results)
        assert all(r.mcd_distance >= 0.0 for r in results)

    def test_mcd_tag_false_for_single_parameter_small_lot(self):
        from module_a.detect import detect

        frames = _lot_of(20, parameter="iddq")
        results = detect(frames)
        assert all(r.explainable_tags["mcd"] is False for r in results)
        assert all(r.mcd_distance is None for r in results)


# ---------------------------------------------------------------------------
# C. Lot of exactly 1 part
# ---------------------------------------------------------------------------

class TestSinglePartLot:
    """Risk C: lot_size=1 — not tested at all before this session.

    Finding: confirmed-already-correct. detect() handles it without crash:
    - lot_size < 30 → MCD skipped, mcd_distance=None
    - robust_z dict with 0.0 values (P2 returns 0 for zero-sigma lots) → scalar=0.0
    - IF: only matters if prior_frames is non-empty; cold start → None
    No code change needed."""

    def test_single_part_lot_does_not_crash(self):
        from module_a.detect import detect

        frame = _frame(lot_size=1, robust_z={"0h": 0.0, "24h": 0.0})
        results = detect([frame])
        assert len(results) == 1

    def test_single_part_lot_mcd_is_none(self):
        from module_a.detect import detect

        frame = _frame(lot_size=1, robust_z={"0h": 0.0})
        results = detect([frame])
        assert results[0].mcd_distance is None

    def test_single_part_lot_robust_z_scalar_is_zero(self):
        """P2 returns z=0 for an all-identical or single-part lot. Module A passes it through."""
        from module_a.detect import detect

        frame = _frame(lot_size=1, robust_z={"0h": 0.0, "24h": 0.0})
        results = detect([frame])
        assert results[0].robust_z == 0.0

    def test_single_part_lot_direction_is_above_median(self):
        """z=0 → above_median by convention (no deviation, non-negative)."""
        from module_a.detect import detect

        frame = _frame(lot_size=1, robust_z={"0h": 0.0})
        results = detect([frame])
        assert results[0].direction == "above_median"

    def test_single_part_lot_cold_start_iso_is_none(self):
        from module_a.detect import detect

        frame = _frame(lot_size=1, robust_z={"0h": 0.0})
        results = detect([frame])
        assert results[0].isolation_forest_score is None

    def test_single_part_lot_with_nonzero_z(self):
        """Even a single-part lot can have a non-zero z if pooled_reference was used."""
        from module_a.detect import detect

        frame = _frame(lot_size=1, used_pooled_fallback=True,
                       robust_z={"0h": 3.5, "24h": 1.2})
        results = detect([frame])
        assert math.isclose(results[0].robust_z, 3.5, rel_tol=1e-9)
        assert results[0].direction == "above_median"


# ---------------------------------------------------------------------------
# D. used_pooled_fallback=True — z-score passthrough correctness
# ---------------------------------------------------------------------------

class TestPooledFallbackFrames:
    """Risk D: When used_pooled_fallback=True, FeatureFrame.robust_z was computed by P2
    against the pooled cross-lot median/sigma, not this lot's own median.
    Module A reads robust_z directly from the frame dict — it never recomputes it.
    So the scalar should reflect the pooled z, not a re-derived lot-relative z.

    Finding: confirmed-already-correct. detect() has no recomputation code path;
    it only reads frame.robust_z[checkpoint]. No code change needed."""

    def test_pooled_fallback_z_is_read_not_recomputed(self):
        """If P2 stored a large pooled z, Module A should surface that exact value."""
        from module_a.detect import detect

        # Simulate a small lot where P2 computed pooled z = 4.7 at 24h
        # (4.7 std deviations above the cross-lot reference median)
        frame = _frame(
            lot_size=15,
            used_pooled_fallback=True,
            robust_z={"0h": 0.3, "24h": 4.7},
            value_0h=10.3,
            value_24h=11.0,
        )
        results = detect([frame])
        # The scalar must be 4.7 — the pooled z — not something recomputed
        assert math.isclose(results[0].robust_z, 4.7, rel_tol=1e-9)

    def test_pooled_fallback_direction_from_pooled_z(self):
        """direction reflects the pooled z's sign, not the lot-relative value."""
        from module_a.detect import detect

        frame = _frame(
            lot_size=10,
            used_pooled_fallback=True,
            robust_z={"0h": -2.8, "24h": -1.1},  # both negative → below_median
        )
        results = detect([frame])
        assert results[0].direction == "below_median"

    def test_pooled_fallback_frame_mcd_is_none(self):
        """A small lot that uses pooled fallback still has lot_size < 30 → MCD None."""
        from module_a.detect import detect

        frame = _frame(lot_size=20, used_pooled_fallback=True, robust_z={"0h": 1.0})
        results = detect([frame])
        assert results[0].mcd_distance is None

    def test_pooled_fallback_iso_cold_start(self):
        """Small lot, pooled fallback, no prior → cold start → iso_score None."""
        from module_a.detect import detect

        frame = _frame(lot_size=20, used_pooled_fallback=True, robust_z={"0h": 1.0})
        results = detect([frame])
        assert results[0].isolation_forest_score is None


# ---------------------------------------------------------------------------
# E. Mixed recognized + unrecognized parameters in the same lot
# ---------------------------------------------------------------------------

class TestMixedParameters:
    """Risk E: A lot where some components have parameter='iddq' and others have
    parameter='exotic_signal'. MCD groups all parameters together in build_mcd_matrix;
    a component must have ALL parameters' z-scores at a checkpoint to appear in the
    matrix. Components with only one parameter get excluded → mcd_distance=None even
    when lot_size >= 30.

    Finding: this is a REAL FINDING — components with only one parameter in a mixed
    lot DO get mcd_distance=None (correctly, because MCD can't score them without a
    complete feature vector). The existing code handles this correctly via the
    build_mcd_matrix exclusion logic + mcd_by_component.get() defaulting to None.
    But it was not previously tested. No code change needed — behaviour is correct."""

    def test_recognized_only_components_get_mcd_when_lot_single_param(self):
        """A lot with all components sharing one parameter: MCD runs normally."""
        from module_a.detect import detect

        frames = _lot_of(35, parameter="iddq")
        results = detect(frames)
        assert all(r.mcd_distance is not None for r in results)

    def test_shared_component_ids_across_params_get_mcd_with_multi_feature_matrix(self):
        """When the same component_id appears for both iddq and leakage, build_mcd_matrix
        groups them into a (n_components × 2) matrix — MCD runs normally.

        _lot_of() generates C000..C034 for every parameter, so the same IDs are shared.
        Both parameters' z-scores feed into the MCD feature vector per component.
        This is the normal multi-parameter lot case — confirmed-already-correct."""
        from module_a.detect import detect

        n = 35
        iddq_frames = _lot_of(n, parameter="iddq", lot_id="LOT001")
        leak_frames = _lot_of(n, parameter="leakage", lot_id="LOT001")
        all_frames = iddq_frames + leak_frames

        results = detect(all_frames)

        # Every component has both parameters → appears in the MCD matrix →
        # mcd_distance is a non-None float for all.
        assert all(r.mcd_distance is not None for r in results), (
            "Components with all parameters' z-scores should get a valid MCD distance"
        )

    def test_disjoint_component_ids_across_params_get_none_mcd(self):
        """When component IDs are disjoint across parameters (e.g. C000..C034 have only
        iddq and D000..D034 have only leakage), no component has a complete feature
        vector → excluded from MCD matrix → mcd_distance=None for all.

        Finding: REAL BUG PATH — components that genuinely lack a parameter's
        z-score at a checkpoint cannot be MCD-scored. Confirmed working correctly."""
        from module_a.detect import detect

        n = 35
        rng = np.random.default_rng(7)
        vals = 10.0 + rng.normal(0, 0.5, n)
        med = float(np.median(vals))
        q75, q25 = np.percentile(vals, [75, 25])
        sig = max((q75 - q25) / 1.35, 1e-9)

        # C000..C034: only iddq, no leakage row
        iddq_only = [
            _frame(component_id=f"C{i:03d}", parameter="iddq", lot_size=n,
                   robust_z={"0h": (vals[i] - med) / sig, "24h": (vals[i] - med) / sig})
            for i in range(n)
        ]
        # D000..D034: only leakage, no iddq row
        leak_only = [
            _frame(component_id=f"D{i:03d}", parameter="leakage", lot_size=n,
                   robust_z={"0h": (vals[i] - med) / sig, "24h": (vals[i] - med) / sig})
            for i in range(n)
        ]
        all_frames = iddq_only + leak_only

        results = detect(all_frames)

        # C* components have no leakage z → excluded. D* have no iddq z → excluded.
        # build_mcd_matrix: parameters = ["iddq", "leakage"], but no component has both
        # → component_ids = [] → len(component_ids) < 30 → MCD skipped.
        assert all(r.mcd_distance is None for r in results), (
            "Disjoint component IDs across parameters: no complete feature vector → "
            "all components excluded from MCD → mcd_distance=None"
        )

    def test_unrecognized_parameter_iso_cold_start_in_mixed_lot(self):
        """In a mixed lot, the 'exotic_signal' parameter has no prior IF model
        (cold start) while 'iddq' may have one. Each scored independently."""
        from module_a.detect import detect

        prior = _lot_of(50, parameter="iddq", lot_id="LOT000")
        # Current: iddq frames (will get IF score) + exotic frames (cold start)
        iddq_current = _lot_of(35, parameter="iddq", lot_id="LOT001")
        exotic_frame = _frame(
            component_id="EX001",
            parameter="exotic_signal",
            lot_size=35,
            robust_z={"0h": 0.5, "24h": 0.8},
        )
        current = iddq_current + [exotic_frame]
        results = detect(current, prior_frames=prior)

        iddq_results = [r for r in results if r.parameter == "iddq"]
        exotic_results = [r for r in results if r.parameter == "exotic_signal"]

        assert all(r.isolation_forest_score is not None for r in iddq_results), (
            "iddq has prior history → IF score available"
        )
        assert all(r.isolation_forest_score is None for r in exotic_results), (
            "exotic_signal has no prior → cold start, None"
        )

    def test_all_parameters_processed_uniformly_in_z_score(self):
        """Unrecognized parameters get the same robust_z scalar treatment as recognized ones."""
        from module_a.detect import detect

        frame_known = _frame(parameter="iddq", robust_z={"0h": 1.5, "24h": 2.2})
        frame_unknown = _frame(parameter="exotic_signal", robust_z={"0h": 1.5, "24h": 2.2})
        results = detect([frame_known, frame_unknown])

        known_z = next(r.robust_z for r in results if r.parameter == "iddq")
        unknown_z = next(r.robust_z for r in results if r.parameter == "exotic_signal")
        assert math.isclose(known_z, 2.2, rel_tol=1e-9)
        assert math.isclose(unknown_z, 2.2, rel_tol=1e-9), (
            "Unrecognized parameter must get the same z-score treatment"
        )
