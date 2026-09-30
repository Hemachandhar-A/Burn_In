"""Tests for P3.3 — E2 steps 7-8: real severity tier assignment.

Session: P3.3 (IMPLEMENTATION_PLAN.md Part 10, P3 section)
Prerequisite: P1.7 — met (harness_thresholds.yaml verified present and populated)

Thresholds (from config/harness_thresholds.yaml, P1.7 output):
  module_a_review_threshold: 0.9556277056277056
  module_a_reject_threshold: 0.9642857142857142
  (REVIEW < REJECT — correct strict ordering, confirmed distinct)

Part 7.3 Module A checklist rows covered here:
  - E2 step 7: explainable tags — confirmed unchanged from P3.2 (still correct)
  - E2 step 8: PASS/REVIEW/REJECT assignment from real thresholds
  - Direction-awareness cap with real tier: below_median + would-be-REJECT -> REVIEW

New coverage (not possible in P3.1/P3.2, REVIEW and REJECT were identical placeholders):
  - A score strictly between REVIEW and REJECT thresholds gets REVIEW (not PASS, not REJECT)
  - Confirmed with exact percentile arithmetic on a controlled lot
"""

import math
import numpy as np
import pytest

from contracts import FeatureFrame


# ---------------------------------------------------------------------------
# Import real thresholds for use in assertions
# ---------------------------------------------------------------------------

from module_a.detect import _THRESHOLDS

REVIEW_T = _THRESHOLDS.module_a_review_threshold
REJECT_T = _THRESHOLDS.module_a_reject_threshold


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _frame(
    component_id: str = "C001",
    parameter: str = "iddq",
    value_0h: float = 10.0,
    value_24h: float = 11.0,
    lot_size: int = 50,
    robust_z: dict[str, float] | None = None,
    lot_median_0h: float = 10.0,
    lot_median_24h: float = 11.0,
) -> FeatureFrame:
    rz = robust_z if robust_z is not None else {"0h": 0.0, "24h": 0.0}
    return FeatureFrame(
        component_id=component_id,
        lot_id="LOT001",
        part_number="PN-1",
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
        used_pooled_fallback=False,
        elapsed_hours={"0h": 0.0, "24h": 24.0},
    )


def _lot_of(
    n: int,
    seed: int = 0,
    spread: float = 0.5,
) -> list[FeatureFrame]:
    """n realistic FeatureFrames (IQR > 0)."""
    rng = np.random.default_rng(seed)
    v0 = 10.0 + rng.normal(0, spread, n)
    v24 = 11.0 + rng.normal(0, spread, n)
    med0, med24 = float(np.median(v0)), float(np.median(v24))
    q75_0, q25_0 = np.percentile(v0, [75, 25])
    q75_24, q25_24 = np.percentile(v24, [75, 25])
    sig0 = max((q75_0 - q25_0) / 1.35, 1e-9)
    sig24 = max((q75_24 - q25_24) / 1.35, 1e-9)
    return [
        _frame(
            component_id=f"C{i:03d}",
            value_0h=float(v0[i]),
            value_24h=float(v24[i]),
            lot_size=n,
            robust_z={"0h": (v0[i] - med0) / sig0, "24h": (v24[i] - med24) / sig24},
            lot_median_0h=med0,
            lot_median_24h=med24,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Threshold sanity — confirm the file is correctly loaded
# ---------------------------------------------------------------------------

class TestThresholdSanity:
    """Verify the loaded thresholds have the correct relative ordering and values."""

    def test_review_threshold_loaded(self):
        assert math.isclose(REVIEW_T, 0.9556277056277056, rel_tol=1e-9)

    def test_reject_threshold_loaded(self):
        assert math.isclose(REJECT_T, 0.9642857142857142, rel_tol=1e-9)

    def test_review_strictly_less_than_reject(self):
        """REVIEW < REJECT — mandatory for the tier assignment logic to be correct."""
        assert REVIEW_T < REJECT_T, (
            f"REVIEW threshold ({REVIEW_T}) must be strictly less than "
            f"REJECT threshold ({REJECT_T})"
        )

    def test_both_thresholds_in_unit_interval(self):
        assert 0.0 < REVIEW_T < 1.0
        assert 0.0 < REJECT_T < 1.0


# ---------------------------------------------------------------------------
# E2 step 7 — Explainable tags (confirm still correct from P3.2)
# ---------------------------------------------------------------------------

class TestExplainableTags:
    """E2 step 7: tags confirmed correct since P3.2 — un-changed by P3.3."""

    def test_robust_z_is_explainable(self):
        from module_a.detect import detect
        results = detect(_lot_of(20))
        assert all(r.explainable_tags["robust_z"] is True for r in results)

    def test_isolation_forest_not_explainable(self):
        from module_a.detect import detect
        results = detect(_lot_of(20))
        assert all(r.explainable_tags["isolation_forest"] is False for r in results)

    def test_ecod_not_explainable(self):
        from module_a.detect import detect
        results = detect(_lot_of(20))
        assert all(r.explainable_tags["ecod"] is False for r in results)

    def test_mcd_tag_false_when_lot_small(self):
        from module_a.detect import detect
        frames = _lot_of(20)  # n < 30, MCD absent
        results = detect(frames)
        assert all(r.explainable_tags["mcd"] is False for r in results)

    def test_mcd_tag_true_when_lot_large_and_mcd_ran(self):
        from module_a.detect import detect
        frames = _lot_of(40)  # n >= 30, MCD should run
        results = detect(frames)
        # At least some components should have mcd=True (MCD ran)
        assert any(r.explainable_tags["mcd"] is True for r in results)


# ---------------------------------------------------------------------------
# E2 step 8 — PASS / REVIEW / REJECT tier assignment
# ---------------------------------------------------------------------------

class TestSeverityTierAssignment:
    """E2 step 8: severity_tier uses real thresholds, not a PASS placeholder."""

    def test_severity_tier_is_not_always_pass(self):
        """With real thresholds and a clear outlier, tier must not always be PASS."""
        from module_a.detect import detect

        # Large lot with one extreme outlier — should get REVIEW or REJECT.
        n = 50
        frames = _lot_of(n, seed=11)
        frames.append(_frame(
            component_id="OUTLIER",
            lot_size=n + 1,
            value_0h=200.0,
            value_24h=220.0,
            robust_z={"0h": 15.0, "24h": 14.0},
        ))
        results = detect(frames)
        outlier_result = next(r for r in results if r.component_id == "OUTLIER")
        assert outlier_result.severity_tier in ("REVIEW", "REJECT"), (
            f"Clear outlier must not be PASS (got {outlier_result.severity_tier})"
        )

    def test_clear_inlier_is_pass(self):
        """A component with modest z-scores in a normal lot must be PASS."""
        from module_a.detect import detect

        frames = _lot_of(50, seed=5)
        results = detect(frames)
        # The bottom-quartile inliers must be PASS
        min_z_result = min(results, key=lambda r: r.robust_z)
        assert min_z_result.severity_tier == "PASS", (
            f"Bottom-z inlier must be PASS (got {min_z_result.severity_tier})"
        )

    def test_valid_tier_literals(self):
        """All returned severity_tier values must be valid Literal values."""
        from module_a.detect import detect

        frames = _lot_of(50)
        results = detect(frames)
        for r in results:
            assert r.severity_tier in ("PASS", "REVIEW", "REJECT"), (
                f"Invalid severity_tier: {r.severity_tier!r}"
            )


# ---------------------------------------------------------------------------
# BETWEEN-THRESHOLDS TEST (new — only meaningful with distinct REVIEW/REJECT)
# ---------------------------------------------------------------------------

class TestBetweenThresholds:
    """A score strictly between REVIEW and REJECT must be REVIEW, not PASS or REJECT.

    This scenario is new in P3.3 — REVIEW and REJECT were both 'PASS' in P3.2,
    so it could not have been tested before.

    REVIEW_T = 0.9556277056277056
    REJECT_T = 0.9642857142857142

    We construct a lot of n frames such that one target frame has combined percentile
    exactly between the two thresholds. The percentile is rank/n. We need:
        REVIEW_T <= rank/n < REJECT_T

    With n frames (no prior → IF absent; lot < 30 → MCD absent; only z and ECOD drive
    the ranking). For a strictly-ordered lot, z_pct and ecod_pct are both rank/n.
    Combined = max(z_pct, ecod_pct, absent_floor, absent_floor) = rank/n for the top
    frame's detectors when ECOD also ranks it top.

    Simplest approach: use the percentile math directly.
    REJECT_T ≈ 0.9643 → rank >= 0.9643 * n → for n=28: rank >= 26.99 → rank 27 → pct 0.9643 (REJECT)
                                                 rank 26 → pct 26/28 = 0.9286 (< REVIEW_T, PASS)
    For n=28 there's no integer rank that falls between REVIEW_T and REJECT_T exactly.

    Better: use a larger lot. The gap between thresholds is ~0.0087.
    We need k/n in [0.9556, 0.9643). For n=113: REVIEW needs k/113 >= 0.9556 → k >= 107.98 → k=108
    → 108/113 = 0.9558. And 108/113 < 0.9643. That's our target: rank 108/113.

    So: build 113 frames sorted by z-score. Frame at position 107 (0-indexed) has rank 108/113 = 0.9558.
    Its combined (driven by z and ECOD both ranking it 108th out of 113) should be ~0.9558,
    which is >= REVIEW_T and < REJECT_T → tier must be REVIEW.
    """

    def test_score_between_thresholds_is_review(self):
        """A combined score in [REVIEW_T, REJECT_T) must produce REVIEW, not PASS or REJECT.

        Constructs a deterministic lot of 113 frames with strictly increasing values.
        The 108th-ranked frame (0-indexed: position 107) gets percentile 108/113 ≈ 0.9558,
        which falls strictly between REVIEW_T (0.9556) and REJECT_T (0.9643).
        """
        from module_a.detect import detect

        n = 113
        # Strictly increasing values → strict rank order for both z and ECOD.
        # Lot < 30 → no MCD. No prior → no IF. Only z_pct and ecod_pct drive combined.
        # The absent detectors contribute (n+1)/(2n) ≈ 0.504 to all (uniform floor).
        # For frame at 0-indexed position 107:
        #   z_pct ≈ 108/113 ≈ 0.9558 (rank 108 out of 113 — highest |z|)
        #   combined = max(0.9558, ~0.504, ~0.504, ecod_pct_107) ≈ 0.9558

        # Use n < 30 so MCD is absent (confirmed simpler arithmetic).
        n_small = 20  # small lot, no MCD, no IF

        # Re-derive target percentile for n=20:
        # We need rank/n in [REVIEW_T, REJECT_T).
        # REVIEW_T = 0.9556 → rank >= 0.9556 * 20 = 19.11 → rank 20 (max rank) → 20/20 = 1.0 → REJECT
        # No integer rank in [0.9556*20, 0.9643*20) = [19.11, 19.28) exists.

        # For n=100: ranks in [95.56, 96.43) → k=96 → 96/100 = 0.96 > REJECT_T. No.
        # For n=115: [109.9, 110.9) → k=110 → 110/115 = 0.9565 ∈ [REVIEW_T, REJECT_T). Yes!
        # Verify: 0.9556 <= 110/115=0.9565 < 0.9643. ✓

        n = 115

        # Build 115 frames with strictly increasing z (small lot for simplicity, MCD absent).
        # We need lot_size to match n.
        frames = [
            _frame(
                component_id=f"C{i:03d}",
                value_0h=10.0 + i * 0.1,
                value_24h=11.0 + i * 0.1,
                lot_size=n,
                robust_z={"0h": (i + 1) * 0.1, "24h": (i + 1) * 0.09},
                lot_median_0h=10.0 + n / 2 * 0.1,
                lot_median_24h=11.0 + n / 2 * 0.1,
            )
            for i in range(n)
        ]

        # Frame at index 109 (0-indexed) has rank 110 out of 115:
        #   z_pct = 110/115 ≈ 0.9565
        # ECOD also sees strictly increasing values → likely ranks it 110th as well.
        # combined ≈ max(0.9565, absent_floor, absent_floor, ecod_pct_109) ≈ 0.9565
        # which is >= REVIEW_T (0.9556) and < REJECT_T (0.9643) → REVIEW

        results = detect(frames)
        target_result = next(r for r in results if r.component_id == "C109")

        # Verify the target is above_median (positive z → above median)
        assert target_result.direction == "above_median"

        # Combined percentile for C109 should be >= REVIEW_T and < REJECT_T.
        # We assert the outcome: must be REVIEW, not PASS or REJECT.
        assert target_result.severity_tier == "REVIEW", (
            f"C109 (combined ≈ 110/115 = 0.9565, between REVIEW_T={REVIEW_T:.6f} and "
            f"REJECT_T={REJECT_T:.6f}) must be REVIEW (got {target_result.severity_tier}). "
            f"This test proves REVIEW and REJECT are distinct and correctly separated."
        )
        # Must not be capped (above_median)
        assert target_result.severity_cap_reason is None

    def test_score_at_reject_threshold_is_reject(self):
        """A combined score at or above REJECT_T must be REJECT (for above_median)."""
        from module_a.detect import detect

        # n=115, top frame C114 has rank 115/115 = 1.0 > REJECT_T → REJECT
        n = 115
        frames = [
            _frame(
                component_id=f"C{i:03d}",
                value_0h=10.0 + i * 0.1,
                value_24h=11.0 + i * 0.1,
                lot_size=n,
                robust_z={"0h": (i + 1) * 0.1, "24h": (i + 1) * 0.09},
            )
            for i in range(n)
        ]
        results = detect(frames)
        top_result = next(r for r in results if r.component_id == "C114")
        assert top_result.direction == "above_median"
        assert top_result.severity_tier == "REJECT", (
            f"Top-ranked above_median frame (combined=1.0) must be REJECT "
            f"(got {top_result.severity_tier})"
        )
        assert top_result.severity_cap_reason is None

    def test_score_below_review_threshold_is_pass(self):
        """A combined score below REVIEW_T must be PASS.

        Uses a middle-of-lot frame: ECOD is symmetric (flags both tails), so C000
        (left extreme) and C114 (right extreme) both get high ECOD. The middle frame
        C057 has low z-score rank and is not a tail extreme for ECOD -> PASS.
        """
        from module_a.detect import detect

        n = 115
        frames = [
            _frame(
                component_id=f"C{i:03d}",
                value_0h=10.0 + i * 0.1,
                value_24h=11.0 + i * 0.1,
                lot_size=n,
                robust_z={"0h": (i + 1) * 0.1, "24h": (i + 1) * 0.09},
            )
            for i in range(n)
        ]
        results = detect(frames)
        # C057 is near the middle: low z-rank (~50th/115), not a tail for ECOD -> PASS
        middle_result = next(r for r in results if r.component_id == "C057")
        assert middle_result.severity_tier == "PASS", (
            f"Middle-of-lot frame must be PASS "
            f"(got {middle_result.severity_tier})"
        )


# ---------------------------------------------------------------------------
# Direction-awareness cap with real tier
# ---------------------------------------------------------------------------

class TestCapWithRealTiers:
    """Direction-awareness cap now fires at the real REJECT threshold.

    The cap converts a would-be REJECT to REVIEW for below_median components.
    severity_cap_reason is populated only when this conversion actually occurs.
    A below_median component that would be PASS or REVIEW (not REJECT) must
    have no cap reason even with real thresholds.
    """

    def test_below_median_reject_becomes_review(self):
        """A below_median component that would be REJECT must be capped to REVIEW."""
        from module_a.detect import detect

        # n=115; frame at C114 is the top-ranked (combined=1.0 > REJECT_T).
        # Make it below_median by using negative z values.
        n = 115
        frames = [
            _frame(
                component_id=f"C{i:03d}",
                value_0h=10.0 + i * 0.1,
                value_24h=11.0 + i * 0.1,
                lot_size=n,
                # Frame C114 (i=114) has largest |z| → rank 115/115 → combined=1.0
                robust_z={"0h": -(i + 1) * 0.1, "24h": -(i + 1) * 0.09},
            )
            for i in range(n)
        ]
        results = detect(frames)
        top_result = next(r for r in results if r.component_id == "C114")

        # C114 is below_median (all z are negative, C114 has largest magnitude)
        assert top_result.direction == "below_median"
        # Would have been REJECT (combined=1.0) but cap converts to REVIEW
        assert top_result.severity_tier == "REVIEW", (
            f"below_median REJECT must be capped to REVIEW (got {top_result.severity_tier})"
        )
        assert top_result.severity_cap_reason == "below_median_direction_cap"

    def test_below_median_review_not_capped(self):
        """A below_median component in the REVIEW zone (not REJECT zone) must NOT be capped."""
        from module_a.detect import detect

        # n=115; frame C109 has combined≈0.9565 (between REVIEW_T and REJECT_T) → REVIEW.
        # It's above_median in the earlier test; make a matching below_median version.
        # Use absolute-value ascending z but negative sign for below_median.
        n = 115
        frames = [
            _frame(
                component_id=f"C{i:03d}",
                value_0h=10.0 + i * 0.1,
                value_24h=11.0 + i * 0.1,
                lot_size=n,
                robust_z={"0h": -(i + 1) * 0.1, "24h": -(i + 1) * 0.09},
            )
            for i in range(n)
        ]
        results = detect(frames)
        target = next(r for r in results if r.component_id == "C109")

        # C109 is below_median (negative z); rank 110/115 ≈ 0.9565 (REVIEW zone)
        assert target.direction == "below_median"
        # REVIEW zone: cap must NOT fire (cap fires only at REJECT zone)
        assert target.severity_tier == "REVIEW", (
            f"below_median in REVIEW zone must remain REVIEW (got {target.severity_tier})"
        )
        assert target.severity_cap_reason is None, (
            "below_median in REVIEW zone must not have cap reason — cap only fires at REJECT"
        )

    def test_cap_does_not_fire_for_below_median_pass(self):
        """A below_median component that is PASS must have no cap reason.

        Uses a middle-of-lot frame: ECOD is symmetric (flags both tails), so the
        bottom frame C000 gets high ECOD. The middle frame C057 has low combined
        score and is PASS.
        """
        from module_a.detect import detect

        n = 115
        frames = [
            _frame(
                component_id=f"C{i:03d}",
                value_0h=10.0 + i * 0.1,
                value_24h=11.0 + i * 0.1,
                lot_size=n,
                robust_z={"0h": -(i + 1) * 0.1, "24h": -(i + 1) * 0.09},
            )
            for i in range(n)
        ]
        results = detect(frames)
        # C057: negative z but small magnitude (middle rank) and not a tail for ECOD -> PASS
        middle = next(r for r in results if r.component_id == "C057")

        assert middle.direction == "below_median"
        assert middle.severity_tier == "PASS"
        assert middle.severity_cap_reason is None, (
            "PASS-tier below_median must not have severity_cap_reason"
        )
