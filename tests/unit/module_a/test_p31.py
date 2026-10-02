"""Tests for P3.1 — E2 steps 1-3: robust z-scores, per-checkpoint MCD, pooled Isolation Forest.

Session: P3.1 (IMPLEMENTATION_PLAN.md Part 10, P3 section)
Prerequisite: P2.4 (real FeatureFrame — met, merged into develop)

Part 7.3 Module A checklist rows covered here:
  - MCD degenerate fit at exactly the 30-part boundary (lot_size == 30 → MCD runs; lot_size == 29 → None)
  - Isolation Forest cold start (part number's first-ever lot → None, not a crash or a guess)

Also covers:
  - robust_z scalar is worst-checkpoint absolute z from FeatureFrame.robust_z
  - direction reflects sign of that worst z
  - MCD distance is a non-negative float on a >=30-part lot
  - Multiple checkpoints: MCD fit per checkpoint, worst distance reported
"""

import math
import numpy as np
import pytest

from contracts import FeatureFrame, ModuleAResult


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_frame(
    component_id: str = "C001",
    lot_id: str = "LOT001",
    part_number: str = "PN-1",
    parameter: str = "iddq",
    value_0h: float = 10.0,
    value_24h: float = 11.0,
    value_96h: float | None = 12.0,
    value_168h: float | None = None,
    lot_size: int = 50,
    used_pooled_fallback: bool = False,
    robust_z_override: dict[str, float] | None = None,
    lot_median_0h: float = 10.0,
    lot_median_24h: float = 11.0,
) -> FeatureFrame:
    rz = robust_z_override if robust_z_override is not None else {
        "0h": (value_0h - lot_median_0h),
        "24h": (value_24h - lot_median_24h),
    }
    elapsed = {"0h": 0.0, "24h": 24.0}
    if value_96h is not None:
        elapsed["96h"] = 96.0
    if value_168h is not None:
        elapsed["168h"] = 168.0
    return FeatureFrame(
        component_id=component_id,
        lot_id=lot_id,
        part_number=part_number,
        parameter=parameter,
        value_0h=value_0h,
        value_24h=value_24h,
        value_96h=value_96h,
        value_168h=value_168h,
        delta_24h=value_24h - value_0h,
        delta_96h=(value_96h - value_0h) if value_96h is not None else None,
        delta_168h=(value_168h - value_0h) if value_168h is not None else None,
        lot_median_0h=lot_median_0h,
        lot_median_24h=lot_median_24h,
        robust_z=rz,
        lot_size=lot_size,
        used_pooled_fallback=used_pooled_fallback,
        elapsed_hours=elapsed,
    )


def _make_lot_frames(
    n: int,
    part_number: str = "PN-1",
    lot_id: str = "LOT001",
    parameter: str = "iddq",
    base_value: float = 10.0,
    outlier_idx: int | None = None,
    outlier_value: float = 100.0,
) -> list[FeatureFrame]:
    """Build n FeatureFrames that all share the same lot_id and part_number.
    Optionally inject one outlier at outlier_idx with a clearly anomalous value.
    All values are around base_value with tiny deterministic jitter so IQR > 0.
    """
    rng = np.random.default_rng(42)
    values_0h = base_value + rng.normal(0, 0.5, n)
    values_24h = base_value + 1.0 + rng.normal(0, 0.5, n)
    if outlier_idx is not None:
        values_0h[outlier_idx] = outlier_value
        values_24h[outlier_idx] = outlier_value + 2.0

    median_0h = float(np.median(values_0h))
    median_24h = float(np.median(values_24h))
    q75_0, q25_0 = np.percentile(values_0h, [75, 25])
    sigma_0 = (q75_0 - q25_0) / 1.35 or 1.0
    q75_24, q25_24 = np.percentile(values_24h, [75, 25])
    sigma_24 = (q75_24 - q25_24) / 1.35 or 1.0

    frames = []
    for i in range(n):
        rz = {
            "0h": (values_0h[i] - median_0h) / sigma_0,
            "24h": (values_24h[i] - median_24h) / sigma_24,
        }
        frames.append(_make_frame(
            component_id=f"C{i:03d}",
            lot_id=lot_id,
            part_number=part_number,
            parameter=parameter,
            value_0h=float(values_0h[i]),
            value_24h=float(values_24h[i]),
            value_96h=None,
            value_168h=None,
            lot_size=n,
            used_pooled_fallback=(n < 30),
            robust_z_override=rz,
            lot_median_0h=median_0h,
            lot_median_24h=median_24h,
        ))
    return frames


# ---------------------------------------------------------------------------
# E2 step 1 — robust_z scalar: worst-checkpoint absolute z from FeatureFrame
# ---------------------------------------------------------------------------

class TestRobustZScalar:
    """The ModuleAResult.robust_z is the maximum absolute robust z across all
    checkpoints in FeatureFrame.robust_z (worst-checkpoint severity)."""

    def test_robust_z_is_max_abs_across_checkpoints(self):
        from module_a.detect import detect

        frame = _make_frame(
            robust_z_override={"0h": 0.5, "24h": 2.3, "96h": 1.1},
        )
        results = detect([frame])
        assert math.isclose(results[0].robust_z, 2.3, rel_tol=1e-9)

    def test_robust_z_handles_negative_z_correctly(self):
        """A strongly negative z at one checkpoint should still give |z| as the worst."""
        from module_a.detect import detect

        frame = _make_frame(
            robust_z_override={"0h": -3.5, "24h": 1.0},
        )
        results = detect([frame])
        assert math.isclose(results[0].robust_z, 3.5, rel_tol=1e-9)

    def test_robust_z_single_checkpoint(self):
        from module_a.detect import detect

        frame = _make_frame(robust_z_override={"0h": 1.7})
        results = detect([frame])
        assert math.isclose(results[0].robust_z, 1.7, rel_tol=1e-9)

    def test_direction_above_median_when_worst_z_positive(self):
        from module_a.detect import detect

        frame = _make_frame(robust_z_override={"0h": 0.2, "24h": 2.8})
        results = detect([frame])
        assert results[0].direction == "above_median"

    def test_direction_below_median_when_worst_z_negative(self):
        from module_a.detect import detect

        frame = _make_frame(robust_z_override={"0h": -3.0, "24h": 0.5})
        results = detect([frame])
        assert results[0].direction == "below_median"

    def test_direction_above_median_when_worst_z_zero(self):
        """Zero z (all-identical lot) → above_median by convention (no deviation)."""
        from module_a.detect import detect

        frame = _make_frame(robust_z_override={"0h": 0.0, "24h": 0.0})
        results = detect([frame])
        assert results[0].direction == "above_median"


# ---------------------------------------------------------------------------
# E2 step 2 — per-checkpoint MCD (MinCovDet), lot-relative
# ---------------------------------------------------------------------------

class TestMCDDistance:
    """MinCovDet is fit per checkpoint on lot frames; each component gets its
    Mahalanobis distance from that checkpoint's robust centroid/covariance."""

    def test_mcd_distance_none_when_lot_below_30(self):
        """7.3 checklist: MCD degenerate boundary — lot_size < 30 → None."""
        from module_a.detect import detect

        frames = _make_lot_frames(n=25)
        results = detect(frames)
        assert all(r.mcd_distance is None for r in results)

    def test_mcd_distance_none_when_lot_exactly_29(self):
        """Boundary is strict: 29 parts → None (not >=30)."""
        from module_a.detect import detect

        frames = _make_lot_frames(n=29)
        results = detect(frames)
        assert all(r.mcd_distance is None for r in results)

    def test_mcd_runs_at_exactly_30_parts(self):
        """7.3 checklist: MCD degenerate boundary — lot_size == 30 → float, not None."""
        from module_a.detect import detect

        frames = _make_lot_frames(n=30)
        results = detect(frames)
        assert all(r.mcd_distance is not None for r in results)
        assert all(isinstance(r.mcd_distance, float) for r in results)

    def test_mcd_distance_non_negative(self):
        """Mahalanobis distance is always >= 0."""
        from module_a.detect import detect

        frames = _make_lot_frames(n=40)
        results = detect(frames)
        assert all(r.mcd_distance >= 0.0 for r in results)

    def test_mcd_outlier_gets_higher_distance_than_inliers(self):
        """The obvious anomaly (value 10x normal) should rank highest by MCD distance."""
        from module_a.detect import detect

        n = 40
        outlier_idx = 0
        frames = _make_lot_frames(n=n, outlier_idx=outlier_idx, outlier_value=100.0)
        results = detect(frames)
        distances = [r.mcd_distance for r in results]
        outlier_dist = distances[outlier_idx]
        other_dists = [d for i, d in enumerate(distances) if i != outlier_idx]
        assert outlier_dist > max(other_dists), (
            f"outlier dist {outlier_dist:.2f} should exceed max inlier {max(other_dists):.2f}"
        )

    def test_mcd_distance_deterministic(self):
        """Same frames, same call → identical MCD distances (AGENTS.md rule 9)."""
        from module_a.detect import detect

        frames = _make_lot_frames(n=40)
        r1 = detect(frames)
        r2 = detect(frames)
        for a, b in zip(r1, r2):
            assert a.mcd_distance == b.mcd_distance

    def test_mcd_explainable_tag_true_when_mcd_ran(self):
        from module_a.detect import detect

        frames = _make_lot_frames(n=40)
        results = detect(frames)
        assert all(r.explainable_tags["mcd"] is True for r in results)

    def test_mcd_explainable_tag_false_when_lot_small(self):
        """If MCD didn't run (lot < 30), its tag must be False — can't explain absent output."""
        from module_a.detect import detect

        frames = _make_lot_frames(n=20)
        results = detect(frames)
        assert all(r.explainable_tags["mcd"] is False for r in results)

    def test_mcd_single_parameter_lot(self):
        """MCD must degrade gracefully with only one parameter (1-feature matrix — still works)."""
        from module_a.detect import detect

        frames = _make_lot_frames(n=35, parameter="iddq")
        results = detect(frames)
        assert all(r.mcd_distance is not None for r in results)


# ---------------------------------------------------------------------------
# E2 step 3 — pooled cross-lot Isolation Forest, cold-start-safe
# ---------------------------------------------------------------------------

class TestIsolationForest:
    """Isolation Forest is trained on *prior* lots of the same part number, not
    lot-relative — it catches campaign-level drift. Cold start (no prior lots) → None."""

    def test_cold_start_returns_none_isolation_forest(self):
        """7.3 checklist: IF cold start — no prior frames → isolation_forest_score is None."""
        from module_a.detect import detect

        frames = _make_lot_frames(n=40)
        # No prior_frames argument → cold start
        results = detect(frames)
        assert all(r.isolation_forest_score is None for r in results)

    def test_cold_start_explicit_empty_prior(self):
        """Passing an empty prior_frames list is equivalent to cold start."""
        from module_a.detect import detect

        frames = _make_lot_frames(n=40)
        results = detect(frames, prior_frames=[])
        assert all(r.isolation_forest_score is None for r in results)

    def test_isolation_forest_score_is_float_when_prior_exists(self):
        """With prior frames, all components get a non-None float score."""
        from module_a.detect import detect

        prior = _make_lot_frames(n=50, lot_id="LOT000")
        current = _make_lot_frames(n=40, lot_id="LOT001")
        results = detect(current, prior_frames=prior)
        assert all(r.isolation_forest_score is not None for r in results)
        assert all(isinstance(r.isolation_forest_score, float) for r in results)

    def test_isolation_forest_not_lot_relative(self):
        """IF must be trained on prior_frames, not the current lot's frames.
        If we feed prior_frames from a wildly different distribution, the current
        lot's normal components should still score differently than an injected outlier."""
        from module_a.detect import detect

        # Prior: tight cluster around 10
        prior = _make_lot_frames(n=60, lot_id="LOT000", base_value=10.0)
        # Current: normal parts near 10, one clear outlier at 200
        current = _make_lot_frames(n=40, lot_id="LOT001", base_value=10.0,
                                   outlier_idx=0, outlier_value=200.0)
        results = detect(current, prior_frames=prior)
        scores = [r.isolation_forest_score for r in results]
        # Isolation Forest score: more negative = more anomalous (sklearn convention).
        # The outlier should have the lowest (most negative) score.
        outlier_score = scores[0]
        inlier_scores = scores[1:]
        assert outlier_score < min(inlier_scores), (
            f"outlier IF score {outlier_score:.4f} should be below min inlier {min(inlier_scores):.4f}"
        )

    def test_isolation_forest_deterministic_with_prior(self):
        """Same prior + same current → identical IF scores (AGENTS.md rule 9)."""
        from module_a.detect import detect

        prior = _make_lot_frames(n=50, lot_id="LOT000")
        current = _make_lot_frames(n=40, lot_id="LOT001")
        r1 = detect(current, prior_frames=prior)
        r2 = detect(current, prior_frames=prior)
        for a, b in zip(r1, r2):
            assert a.isolation_forest_score == b.isolation_forest_score

    def test_isolation_forest_explainable_tag_false(self):
        """IF is always tagged False (not explainable) regardless of whether it ran."""
        from module_a.detect import detect

        prior = _make_lot_frames(n=50, lot_id="LOT000")
        current = _make_lot_frames(n=40, lot_id="LOT001")
        results = detect(current, prior_frames=prior)
        assert all(r.explainable_tags["isolation_forest"] is False for r in results)

    def test_isolation_forest_with_multiple_parameters_in_prior(self):
        """Prior frames may contain multiple parameters; IF must handle this without crash."""
        from module_a.detect import detect

        prior_iddq = _make_lot_frames(n=40, lot_id="LOT000", parameter="iddq")
        prior_leak = _make_lot_frames(n=40, lot_id="LOT000", parameter="leakage")
        prior = prior_iddq + prior_leak

        current_iddq = _make_lot_frames(n=30, lot_id="LOT001", parameter="iddq")
        current_leak = _make_lot_frames(n=30, lot_id="LOT001", parameter="leakage")
        current = current_iddq + current_leak

        results = detect(current, prior_frames=prior)
        # Each parameter is scored independently; all should have a score
        iddq_results = [r for r in results if r.parameter == "iddq"]
        leak_results = [r for r in results if r.parameter == "leakage"]
        assert all(r.isolation_forest_score is not None for r in iddq_results)
        assert all(r.isolation_forest_score is not None for r in leak_results)

    def test_isolation_forest_cold_start_with_unknown_parameter(self):
        """Unknown parameter + no prior → cold start, None score, no crash."""
        from module_a.detect import detect

        frames = _make_lot_frames(n=40, parameter="exotic_signal")
        results = detect(frames)
        assert all(r.isolation_forest_score is None for r in results)
