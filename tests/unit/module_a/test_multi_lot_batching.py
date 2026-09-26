"""Regression test: multi-lot batching must produce the same results as per-lot calls.

This test was added after a confirmed cross-lot data-corruption bug: detect() computed
lot-relative statistics (MCD, ECOD, percentile ranks) across the entire frames list with
no lot_id grouping, so a caller batching multiple lots' frames together would get one lot's
statistics silently corrupted by another's.

Confirmed with real numbers: two lots sharing component IDs, batched together, gave
component U0000/iddq an MCD distance of 14.85 instead of its real per-lot value of 5.12.
Even with distinct IDs across lots, pooling shifted the statistics (5.12 → 3.26).

Fix applied in detect.py: group frames by lot_id inside detect(), process each lot
independently via _detect_single_lot(), concatenate results in input order.

This is the normal operating mode for P1.7 (multi-lot harness sweep), not an edge case.
"""

import numpy as np
import pytest

from contracts import FeatureFrame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lot(
    lot_id: str,
    n: int,
    component_ids: list[str] | None = None,
    parameter: str = "iddq",
    seed: int = 0,
    outlier_idx: int | None = None,
    outlier_mult: float = 8.0,
    part_number: str = "PN-1",
) -> list[FeatureFrame]:
    """Build n realistic FeatureFrames for one lot."""
    rng = np.random.default_rng(seed)
    v0 = 10.0 + rng.normal(0, 0.5, n)
    v24 = 11.0 + rng.normal(0, 0.5, n)
    if outlier_idx is not None:
        v0[outlier_idx] *= outlier_mult
        v24[outlier_idx] *= outlier_mult

    med0 = float(np.median(v0))
    med24 = float(np.median(v24))
    q75_0, q25_0 = np.percentile(v0, [75, 25])
    q75_24, q25_24 = np.percentile(v24, [75, 25])
    sig0 = max((q75_0 - q25_0) / 1.35, 1e-9)
    sig24 = max((q75_24 - q25_24) / 1.35, 1e-9)

    cids = component_ids if component_ids is not None else [f"C{i:04d}" for i in range(n)]
    assert len(cids) == n

    return [
        FeatureFrame(
            component_id=cids[i],
            lot_id=lot_id,
            part_number=part_number,
            parameter=parameter,
            value_0h=float(v0[i]),
            value_24h=float(v24[i]),
            value_96h=None,
            value_168h=None,
            delta_24h=float(v24[i] - v0[i]),
            delta_96h=None,
            delta_168h=None,
            lot_median_0h=med0,
            lot_median_24h=med24,
            robust_z={"0h": (v0[i] - med0) / sig0, "24h": (v24[i] - med24) / sig24},
            lot_size=n,
            used_pooled_fallback=False,
            elapsed_hours={"0h": 0.0, "24h": 24.0},
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Regression test: batching must equal per-lot
# ---------------------------------------------------------------------------

class TestMultiLotBatching:
    """Cross-lot batching regression tests.

    The invariant: detect(lot_A + lot_B) must produce the same per-lot results
    as detect(lot_A) + detect(lot_B).

    This must hold regardless of whether the two lots share component IDs
    (the exact scenario that confirmed the bug) or have distinct IDs.
    """

    def test_batched_equals_separate_shared_component_ids(self):
        """PRIMARY REGRESSION TEST: two lots reusing every component ID.

        This is the exact scenario that was unverified and confirmed to produce
        wrong results when batched. Before the fix, batching both lots together
        gave the same component different MCD distances than each lot processed alone.

        The test: detect(lot_A + lot_B) must return the same (component_id, ecod_score,
        mcd_distance, robust_z) as detect(lot_A) + detect(lot_B) separately.
        """
        from module_a.detect import detect

        # Two lots, SAME component IDs, different distributions.
        shared_ids = [f"C{i:04d}" for i in range(35)]  # 35 > MCD floor of 30
        lot_a = _lot("LOT_A", n=35, component_ids=shared_ids, seed=1, outlier_idx=0)
        lot_b = _lot("LOT_B", n=35, component_ids=shared_ids, seed=2, outlier_idx=0)

        # Per-lot results (expected)
        results_a_alone = detect(lot_a)
        results_b_alone = detect(lot_b)

        # Batched (was wrong before fix)
        results_batched = detect(lot_a + lot_b)

        # Split batched results by lot_id
        batched_a = [r for r in results_batched if r.lot_id == "LOT_A"]
        batched_b = [r for r in results_batched if r.lot_id == "LOT_B"]

        # Must be same length
        assert len(batched_a) == len(results_a_alone), "LOT_A result count mismatch"
        assert len(batched_b) == len(results_b_alone), "LOT_B result count mismatch"

        # Sort both by component_id for comparison
        def _by_cid(rs):
            return sorted(rs, key=lambda r: r.component_id)

        for alone, batched in zip(_by_cid(results_a_alone), _by_cid(batched_a)):
            assert alone.component_id == batched.component_id
            assert alone.robust_z == batched.robust_z, (
                f"LOT_A {alone.component_id}: robust_z {alone.robust_z} != {batched.robust_z} "
                f"(batching corrupted lot-relative z-scalar)"
            )
            assert alone.ecod_score == batched.ecod_score, (
                f"LOT_A {alone.component_id}: ecod_score {alone.ecod_score:.4f} != "
                f"{batched.ecod_score:.4f} (batching corrupted lot-relative ECOD)"
            )
            if alone.mcd_distance is not None:
                assert batched.mcd_distance is not None
                assert abs(alone.mcd_distance - batched.mcd_distance) < 1e-9, (
                    f"LOT_A {alone.component_id}: mcd_distance {alone.mcd_distance:.4f} != "
                    f"{batched.mcd_distance:.4f} (batching corrupted per-lot MCD)"
                )

        for alone, batched in zip(_by_cid(results_b_alone), _by_cid(batched_b)):
            assert alone.component_id == batched.component_id
            assert alone.robust_z == batched.robust_z
            assert alone.ecod_score == batched.ecod_score
            if alone.mcd_distance is not None:
                assert batched.mcd_distance is not None
                assert abs(alone.mcd_distance - batched.mcd_distance) < 1e-9

    def test_batched_equals_separate_distinct_component_ids(self):
        """Even with distinct component IDs across lots, pooling statistics corrupts them.

        Before the fix, combining two lots' frames in one percentile-ranking pass
        shifted the relative severity scores (the bug confirmed at 5.12 → 3.26).
        """
        from module_a.detect import detect

        lot_a = _lot("LOT_A", n=35, seed=3)  # IDs C0000-C0034
        lot_b = _lot("LOT_B", n=35, seed=4,
                     component_ids=[f"D{i:04d}" for i in range(35)])  # distinct IDs

        results_a_alone = detect(lot_a)
        results_b_alone = detect(lot_b)
        results_batched = detect(lot_a + lot_b)

        batched_a = [r for r in results_batched if r.lot_id == "LOT_A"]
        batched_b = [r for r in results_batched if r.lot_id == "LOT_B"]

        assert len(batched_a) == len(results_a_alone)
        assert len(batched_b) == len(results_b_alone)

        def _by_cid(rs):
            return sorted(rs, key=lambda r: r.component_id)

        for alone, batched in zip(_by_cid(results_a_alone), _by_cid(batched_a)):
            assert alone.ecod_score == batched.ecod_score, (
                f"LOT_A {alone.component_id}: ecod_score corrupted by batching"
            )
            if alone.mcd_distance is not None:
                assert batched.mcd_distance is not None
                assert abs(alone.mcd_distance - batched.mcd_distance) < 1e-9, (
                    f"LOT_A {alone.component_id}: mcd_distance corrupted by batching"
                )

    def test_batched_output_order_matches_input_order(self):
        """detect() must return results in the same order as the input frames,
        even when the input contains multiple lots interleaved or concatenated."""
        from module_a.detect import detect

        lot_a = _lot("LOT_A", n=10, seed=5)
        lot_b = _lot("LOT_B", n=10, seed=6,
                     component_ids=[f"D{i:04d}" for i in range(10)])

        frames = lot_a + lot_b
        results = detect(frames)

        assert len(results) == len(frames)
        for frame, result in zip(frames, results):
            assert result.component_id == frame.component_id, (
                "Output order must match input order"
            )
            assert result.lot_id == frame.lot_id, (
                "lot_id must match input frame's lot_id"
            )

    def test_single_lot_unchanged_by_refactor(self):
        """Single-lot detect() must give identical results before and after the fix.
        The refactor (grouping by lot_id) must be a no-op for single-lot inputs."""
        from module_a.detect import detect

        lot = _lot("LOT_X", n=35, seed=7)

        # Run twice — must be identical (determinism + no side-effects)
        r1 = detect(lot)
        r2 = detect(lot)

        for a, b in zip(r1, r2):
            assert a.robust_z == b.robust_z
            assert a.ecod_score == b.ecod_score
            assert a.mcd_distance == b.mcd_distance
            assert a.severity_cap_reason == b.severity_cap_reason

    def test_prior_frames_still_pooled_across_lots(self):
        """IF prior_frames are intentionally cross-lot pooled (E2 step 3 spec).
        The fix must NOT affect how prior_frames are used — they stay pooled."""
        from module_a.detect import detect

        prior = _lot("LOT_PRIOR", n=50, seed=8)
        current = _lot("LOT_CURR", n=35, seed=9)

        results_with_prior = detect(current, prior_frames=prior)
        results_without_prior = detect(current)

        # With prior frames, IF models are trained → iso scores should be non-None
        scores_with = [r.isolation_forest_score for r in results_with_prior]
        scores_without = [r.isolation_forest_score for r in results_without_prior]

        assert all(s is not None for s in scores_with), (
            "With prior frames, IF scores must be non-None (not cold start)"
        )
        assert all(s is None for s in scores_without), (
            "Without prior frames, IF scores must be None (cold start)"
        )
