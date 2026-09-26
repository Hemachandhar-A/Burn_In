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
        """Single-lot detect() must give the same numbers before and after the multi-lot fix.

        The literals below were computed with the PRE-fix detect.py (commit a1607a7) and confirmed
        identical on the fixed one, so this pins the actual behavior, not just that two calls agree.
        A fixed single lot (35 parts, one outlier at index 3) scored against a fixed prior lot."""
        from module_a.detect import detect

        lot = _lot("LOT_GOLD", n=35, seed=7, outlier_idx=3, outlier_mult=6.0)
        prior = _lot("LOT_PRIOR", n=50, seed=8)
        by_cid = {r.component_id: r for r in detect(lot, prior_frames=prior)}

        golden = {
            # component: (robust_z, mcd_distance, isolation_forest_score, ecod_score, direction)
            "C0000": (0.8933193100139069, 0.9055357703836712, -0.4552403815725375, 2.7539872962892358, "below_median"),
            "C0003": (117.62599037028066, 127.91611700524372, -0.669326490777558, 7.110696122978827, "above_median"),
            "C0017": (0.22734264148941802, 0.2686678720633663, -0.4150706054324596, 1.4477356428428816, "below_median"),
            "C0034": (1.6542085459380502, 1.7778269366319832, -0.5125330137648394, 4.0661736852554045, "above_median"),
        }
        for cid, (z, mcd, iso, ecod, direction) in golden.items():
            r = by_cid[cid]
            assert r.robust_z == pytest.approx(z, rel=1e-6), cid
            assert r.mcd_distance == pytest.approx(mcd, rel=1e-6), cid
            assert r.isolation_forest_score == pytest.approx(iso, rel=1e-6), cid
            assert r.ecod_score == pytest.approx(ecod, rel=1e-6), cid
            assert r.direction == direction, cid
            assert r.severity_cap_reason is None, cid

        # And it stays deterministic run to run.
        again = {r.component_id: r for r in detect(lot, prior_frames=prior)}
        assert all(by_cid[c].ecod_score == again[c].ecod_score for c in by_cid)

    def test_prior_frames_still_pooled_across_lots(self):
        """IF prior_frames are intentionally cross-lot pooled (E2 step 3 spec).

        A single prior lot cannot prove that, so the prior spans two distinct lots. If prior_frames
        were scoped per lot, (a) relabelling the same frames as one lot would change the scores, or
        (b) one lot's history would stand in for the pool."""
        from module_a.detect import detect

        prior_a = _lot("PRIOR_A", n=40, seed=11)
        prior_b = _lot("PRIOR_B", n=40, seed=12, component_ids=[f"D{i:04d}" for i in range(40)])
        current = _lot("LOT_CURR", n=35, seed=9)

        def iso(prior):
            return [r.isolation_forest_score for r in detect(current, prior_frames=prior)]

        together = iso(prior_a + prior_b)
        assert all(s is not None for s in together), "With prior frames, IF scores must be non-None"
        assert all(s is None for s in iso([])), "Without prior frames, IF scores must be None (cold start)"

        # (a) The same frames under one lot_id: identical scores, so lot_id plays no part in the pooling.
        one_lot = [f.model_copy(update={"lot_id": "ONE_POOLED_LOT"}) for f in prior_a + prior_b]
        assert iso(one_lot) == together

        # (b) Both lots contribute: dropping either one changes the scores.
        assert iso(prior_a) != together
        assert iso(prior_b) != together

    def test_per_lot_grouping_and_pooled_prior_hold_together(self):
        """Current frames spanning two lots AND prior_frames spanning two other lots, at once.

        Each current lot must score exactly as it does alone against the same pooled prior (per-lot
        grouping), and that prior must be the pool of both prior lots, not one of them (pooled IF)."""
        from module_a.detect import detect

        shared_ids = [f"C{i:04d}" for i in range(35)]
        lot_a = _lot("LOT_A", n=35, component_ids=shared_ids, seed=1, outlier_idx=0)
        lot_b = _lot("LOT_B", n=35, component_ids=shared_ids, seed=2, outlier_idx=0)
        prior_a = _lot("PRIOR_A", n=40, seed=11)
        prior_b = _lot("PRIOR_B", n=40, seed=12, component_ids=[f"D{i:04d}" for i in range(40)])
        prior = prior_a + prior_b

        batched = detect(lot_a + lot_b, prior_frames=prior)
        alone = detect(lot_a, prior_frames=prior) + detect(lot_b, prior_frames=prior)
        assert [(r.lot_id, r.component_id) for r in batched] == [(f.lot_id, f.component_id) for f in lot_a + lot_b]

        def key(r):
            return (r.lot_id, r.component_id)

        want = {key(r): r for r in alone}
        for r in batched:
            w = want[key(r)]
            assert r.robust_z == w.robust_z, key(r)
            assert r.ecod_score == w.ecod_score, key(r)
            assert r.mcd_distance == pytest.approx(w.mcd_distance, abs=1e-9), key(r)
            assert r.isolation_forest_score == w.isolation_forest_score, key(r)
            assert r.severity_cap_reason == w.severity_cap_reason, key(r)

        # The pooled history, not a single prior lot, is what the IF scored against.
        only_a = {key(r): r.isolation_forest_score for r in detect(lot_a + lot_b, prior_frames=prior_a)}
        assert any(only_a[key(r)] != r.isolation_forest_score for r in batched)
