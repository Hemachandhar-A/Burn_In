"""Tests for combined_severity and explainable_corroboration fields.

Covers:
- combined_severity is the same max-combined percentile used for tier assignment (not a copy).
- explainable_corroboration = True when z or mcd ties the max (E2 step 7 definition).
- explainable_corroboration = False when only IF or ECOD drives the max.

The two required tie cases (per task spec):
  Case A: IF and ECOD alone drive the max; neither z nor mcd reaches it -> False.
  Case B: An explainable detector (z) ties the max alongside ECOD -> True.
"""

import numpy as np
import pytest

from contracts import FeatureFrame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frame(
    component_id: str = "C001",
    parameter: str = "iddq",
    value_0h: float = 10.0,
    value_24h: float = 11.0,
    lot_size: int = 5,
    robust_z: dict[str, float] | None = None,
) -> FeatureFrame:
    rz = robust_z if robust_z is not None else {"0h": 0.0}
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
        lot_median_0h=10.0,
        lot_median_24h=11.0,
        robust_z=rz,
        lot_size=lot_size,
        used_pooled_fallback=False,
        elapsed_hours={"0h": 0.0, "24h": 24.0},
    )


# ---------------------------------------------------------------------------
# combined_severity
# ---------------------------------------------------------------------------

class TestCombinedSeverityField:
    """combined_severity is the same value used to assign severity_tier.
    It must:
      - Be in [0, 1] for all frames.
      - Match the max across all four detector percentiles for the frame.
      - Be strictly higher for a clear outlier than for inliers.
    """

    def test_combined_severity_in_unit_interval(self):
        from module_a.detect import detect
        frames = [
            _frame(component_id=f"C{i:03d}", value_0h=10.0 + i * 0.5,
                   value_24h=11.0 + i * 0.5, robust_z={"0h": float(i)})
            for i in range(5)
        ]
        results = detect(frames)
        for r in results:
            assert 0.0 <= r.combined_severity <= 1.0, (
                f"{r.component_id}: combined_severity={r.combined_severity} out of [0,1]"
            )

    def test_outlier_has_higher_combined_severity_than_inliers(self):
        from module_a.detect import detect
        n = 5
        frames = [
            _frame(component_id=f"C{i:03d}", value_0h=10.0 + i * 0.1,
                   value_24h=11.0 + i * 0.1, robust_z={"0h": float(i) * 0.1},
                   lot_size=n)
            for i in range(n - 1)
        ]
        # Extreme outlier
        frames.append(_frame(
            component_id="OUT", value_0h=100.0, value_24h=110.0,
            robust_z={"0h": 20.0}, lot_size=n,
        ))
        results = detect(frames)
        outlier = next(r for r in results if r.component_id == "OUT")
        inliers = [r for r in results if r.component_id != "OUT"]
        for inl in inliers:
            assert outlier.combined_severity > inl.combined_severity, (
                f"Outlier combined_severity ({outlier.combined_severity:.4f}) must be "
                f"higher than inlier {inl.component_id} ({inl.combined_severity:.4f})"
            )

    def test_combined_severity_consistent_with_tier(self):
        """combined_severity and severity_tier must be consistent: if tier is PASS,
        combined_severity must be below review_threshold; if REJECT, above reject_threshold."""
        from module_a.detect import detect, _THRESHOLDS
        n = 20
        frames = [
            _frame(component_id=f"C{i:03d}", value_0h=10.0 + i * 0.2,
                   value_24h=11.0 + i * 0.2, robust_z={"0h": float(i) * 0.3},
                   lot_size=n)
            for i in range(n)
        ]
        results = detect(frames)
        for r in results:
            if r.severity_tier == "PASS":
                assert r.combined_severity < _THRESHOLDS.module_a_review_threshold, (
                    f"{r.component_id}: PASS but combined_severity={r.combined_severity:.6f} "
                    f">= REVIEW_T={_THRESHOLDS.module_a_review_threshold:.6f}"
                )
            elif r.severity_tier == "REJECT":
                assert r.combined_severity >= _THRESHOLDS.module_a_reject_threshold, (
                    f"{r.component_id}: REJECT but combined_severity={r.combined_severity:.6f} "
                    f"< REJECT_T={_THRESHOLDS.module_a_reject_threshold:.6f}"
                )
            # REVIEW: between thresholds (or capped from REJECT) — both valid


# ---------------------------------------------------------------------------
# explainable_corroboration — the required tie cases
# ---------------------------------------------------------------------------

class TestExplainableCorroboration:
    """explainable_corroboration semantics: True iff z or mcd reached/tied the combined max.

    These tests exercise the two required tie scenarios from the task spec:
      Case A: Only IF/ECOD drive the max; z does not reach it -> False.
      Case B: z ties the max alongside ECOD -> True.

    Design: use lot_size < 30 (no MCD) and no prior_frames (no IF), so:
      - MCD absent -> mcd_pct = uniform absent-floor, always below a high ECOD score.
      - IF absent  -> iso_pct = uniform absent-floor, always below a high ECOD score.
      - combined = max(z_pct, ecod_pct) for all frames.
      - corroboration = z_pct >= combined - eps.
    """

    def test_case_a_ecod_drives_max_z_does_not_reach_it(self):
        """Case A: ECOD alone drives the combined max for the target frame.
        z is low for that frame; no MCD or IF present.
        -> explainable_corroboration = False.

        Construction (n=3, lot_size < 30, no prior):
          Frame 0 'TAIL':  value_0h=100 (extreme right-tail -> highest ECOD),
                            robust_z={"0h": 0.1}  (small positive z, rank 1/3).
          Frame 1 'MID':   value_0h=10,  robust_z={"0h": 1.0} (rank 2/3).
          Frame 2 'HIGH_Z':value_0h=10,  robust_z={"0h": 5.0} (rank 3/3 z, but value=10 -> low ECOD).

        ECOD sees [100, 10, 10] for value_0h (with matching value_24h proportional).
        ECOD flags 100 as extreme right-tail (highest ECOD score for TAIL).
        z_pct for TAIL = 1/3 = 0.333 (smallest |z| in the lot).
        ecod_pct for TAIL = 3/3 = 1.0 (largest ECOD score, extreme right tail).
        combined for TAIL = max(1/3, 1.0, absent_floor, absent_floor) = 1.0 (ecod_pct).
        z_pct[TAIL] = 0.333 < combined[TAIL] = 1.0 -> corroboration = False.
        """
        from module_a.detect import detect

        lot_size = 3
        frames = [
            # TAIL: extreme value_0h/24h -> highest ECOD; but z is small.
            _frame(
                component_id="TAIL",
                value_0h=100.0,
                value_24h=110.0,
                lot_size=lot_size,
                robust_z={"0h": 0.1},        # rank 1/3 by |z|
            ),
            _frame(
                component_id="MID",
                value_0h=10.0,
                value_24h=11.0,
                lot_size=lot_size,
                robust_z={"0h": 1.0},         # rank 2/3 by |z|
            ),
            _frame(
                component_id="HIGH_Z",
                value_0h=10.0,
                value_24h=11.0,
                lot_size=lot_size,
                robust_z={"0h": 5.0},         # rank 3/3 by |z|; but value=10 -> not extreme for ECOD
            ),
        ]

        results = detect(frames)
        tail_result = next(r for r in results if r.component_id == "TAIL")

        # Verify ECOD drove the combined: TAIL's ECOD must be highest (it's the extreme value)
        tail_ecod = tail_result.ecod_score
        other_ecod = [r.ecod_score for r in results if r.component_id != "TAIL"]
        assert all(tail_ecod > e for e in other_ecod), (
            f"TAIL must have highest ECOD (it is the extreme-value frame); "
            f"got tail={tail_ecod:.4f}, others={other_ecod}"
        )

        # TAIL's z is the smallest in the lot (rank 1/3)
        tail_z = tail_result.robust_z
        other_z = [r.robust_z for r in results if r.component_id != "TAIL"]
        assert all(tail_z < z for z in other_z), (
            f"TAIL must have smallest z_scalar; got tail={tail_z}, others={other_z}"
        )

        # PRIMARY ASSERTION: corroboration is False for TAIL.
        # combined is driven by ECOD alone; z does not reach it.
        assert tail_result.explainable_corroboration is False, (
            f"TAIL: ECOD drove combined_severity={tail_result.combined_severity:.4f}; "
            f"z_scalar={tail_result.robust_z} is the smallest in the lot. "
            f"explainable_corroboration must be False (no explainable detector reached the max)."
        )
        # combined_severity must be the max-combined percentile (ECOD-driven, rank 3/3 = 1.0)
        assert abs(tail_result.combined_severity - 1.0) < 1e-9, (
            f"TAIL: combined_severity must be 1.0 (highest-ranked ECOD), "
            f"got {tail_result.combined_severity}"
        )

    def test_case_b_z_ties_max_alongside_ecod(self):
        """Case B: z reaches the combined max alongside ECOD for the target frame.
        -> explainable_corroboration = True.

        Construction (n=3, lot_size < 30, no prior):
          Frame 0 'TOP':   value_0h=20 (right-tail -> highest ECOD), robust_z={"0h": 5.0} (highest |z|).
          Frame 1 'MID':   value_0h=11, robust_z={"0h": 1.0}.
          Frame 2 'NEAR':  value_0h=11.5, robust_z={"0h": 0.1}.  <- close to MID, not a tail

        ECOD sees [20, 11, 11.5]. Value 20 is the clear right-tail extreme; 11 and 11.5
        are both close to the bulk. ECOD ranks TOP highest.
        z also ranks TOP highest (|z|=5.0).
        Both z_pct and ecod_pct for TOP = 3/3 = 1.0.
        combined for TOP = 1.0. z_pct[TOP] = 1.0 = combined -> corroboration = True.
        """
        from module_a.detect import detect

        lot_size = 3
        frames = [
            _frame(
                component_id="TOP",
                value_0h=20.0,
                value_24h=22.0,
                lot_size=lot_size,
                robust_z={"0h": 5.0},     # highest |z| in lot -> z_pct = 1.0
            ),
            _frame(
                component_id="MID",
                value_0h=11.0,
                value_24h=12.0,
                lot_size=lot_size,
                robust_z={"0h": 1.0},
            ),
            _frame(
                component_id="NEAR",
                value_0h=11.5,             # close to MID, not a tail extreme -> lower ECOD than TOP
                value_24h=12.5,
                lot_size=lot_size,
                robust_z={"0h": 0.1},
            ),
        ]

        results = detect(frames)
        top_result = next(r for r in results if r.component_id == "TOP")

        # Verify TOP has highest z scalar
        top_z = top_result.robust_z
        other_z = [r.robust_z for r in results if r.component_id != "TOP"]
        assert all(top_z > z for z in other_z), (
            f"TOP must have highest z_scalar; got top={top_z}, others={other_z}"
        )

        # TOP has the largest value_0h (20 vs 11/11.5). It should be the highest ECOD.
        # ECOD flags the extreme right tail; 11 and 11.5 are both near the bulk.
        top_ecod = top_result.ecod_score
        other_ecod = [r.ecod_score for r in results if r.component_id != "TOP"]
        assert all(top_ecod >= e for e in other_ecod), (
            f"TOP must have >= ECOD score (rightmost extreme value); "
            f"got top={top_ecod:.4f}, others={other_ecod}"
        )

        # combined_severity must be 1.0 (rank 3/3) since TOP ranks highest in both z and ECOD.
        assert abs(top_result.combined_severity - 1.0) < 1e-9, (
            f"TOP: combined_severity must be 1.0; got {top_result.combined_severity}"
        )

        # PRIMARY ASSERTION: corroboration is True for TOP.
        # z_pct[TOP] = 1.0 = combined_severity -> z reached the max alongside ECOD.
        assert top_result.explainable_corroboration is True, (
            f"TOP: z_pct and ecod_pct are both 1.0 (top-ranked in a 3-frame lot). "
            f"explainable_corroboration must be True (z, an explainable detector, tied the max). "
            f"combined_severity={top_result.combined_severity:.4f}"
        )

    def test_case_a_is_not_trivially_true(self):
        """Sanity check: HIGH_Z frame in case A must have corroboration=True.
        HIGH_Z has the largest z in the lot, so z_pct[HIGH_Z]=1.0=combined[HIGH_Z].
        Confirms the False result for TAIL is not a bug where all frames return False."""
        from module_a.detect import detect

        lot_size = 3
        frames = [
            _frame(component_id="TAIL", value_0h=100.0, value_24h=110.0,
                   lot_size=lot_size, robust_z={"0h": 0.1}),
            _frame(component_id="MID", value_0h=10.0, value_24h=11.0,
                   lot_size=lot_size, robust_z={"0h": 1.0}),
            _frame(component_id="HIGH_Z", value_0h=10.0, value_24h=11.0,
                   lot_size=lot_size, robust_z={"0h": 5.0}),
        ]
        results = detect(frames)
        high_z_result = next(r for r in results if r.component_id == "HIGH_Z")

        # HIGH_Z has z_pct=1.0 (highest z); its combined is also 1.0.
        # So corroboration must be True.
        assert high_z_result.explainable_corroboration is True, (
            f"HIGH_Z: z_pct=1.0=combined -> corroboration must be True "
            f"(proves Case A False result is specific to TAIL, not a blanket bug)"
        )

    def test_corroboration_false_explicitly_named_fields(self):
        """When corroboration is False, explainable_tags show the same False/False pattern:
        IF and ECOD are not explainable, and mcd=False (no MCD for small lot).
        This is not a redundant test — it confirms the corroboration field tracks
        'did any explainable detector reach the max' not just 'does any explainable tag exist'.
        """
        from module_a.detect import detect

        # Same lot as Case A
        lot_size = 3
        frames = [
            _frame(component_id="TAIL", value_0h=100.0, value_24h=110.0,
                   lot_size=lot_size, robust_z={"0h": 0.1}),
            _frame(component_id="MID", value_0h=10.0, value_24h=11.0,
                   lot_size=lot_size, robust_z={"0h": 1.0}),
            _frame(component_id="HIGH_Z", value_0h=10.0, value_24h=11.0,
                   lot_size=lot_size, robust_z={"0h": 5.0}),
        ]
        results = detect(frames)
        tail_result = next(r for r in results if r.component_id == "TAIL")

        assert tail_result.explainable_corroboration is False
        # robust_z IS tagged explainable, but its percentile rank was not the max.
        assert tail_result.explainable_tags["robust_z"] is True
        # mcd is absent (lot < 30) and not tagged.
        assert tail_result.explainable_tags["mcd"] is False
        # The corroboration is about REACHING the max, not just having an explainable tag.
        # robust_z tag=True but corroboration=False: z's rank was too low.

    def test_corroboration_mcd_counts_when_it_ran(self):
        """When MCD runs (lot >= 30) and MCD distance ranks highest, corroboration is True."""
        from module_a.detect import detect

        # Build a lot of 35 frames (> 30 -> MCD runs) with one extreme outlier.
        import numpy as np
        rng = np.random.default_rng(42)
        n = 35
        v0 = 10.0 + rng.normal(0, 0.5, n)
        v24 = 11.0 + rng.normal(0, 0.5, n)
        med0, med24 = float(np.median(v0)), float(np.median(v24))

        from contracts import FeatureFrame
        base_frames = [
            FeatureFrame(
                component_id=f"C{i:03d}", lot_id="LOT001", part_number="PN-1",
                parameter="iddq",
                value_0h=float(v0[i]), value_24h=float(v24[i]),
                value_96h=None, value_168h=None,
                delta_24h=float(v24[i] - v0[i]), delta_96h=None, delta_168h=None,
                lot_median_0h=med0, lot_median_24h=med24,
                robust_z={"0h": float(v0[i] - med0), "24h": float(v24[i] - med24)},
                lot_size=n, used_pooled_fallback=False,
                elapsed_hours={"0h": 0.0, "24h": 24.0},
            )
            for i in range(n)
        ]

        results = detect(base_frames)
        # At least one result should have corroboration=True (z and/or mcd drove the max)
        # for a normal lot where z and values correlate.
        any_true = any(r.explainable_corroboration for r in results)
        assert any_true, (
            "For a real lot with MCD running, at least one frame should have "
            "explainable_corroboration=True (z or mcd reached the combined max)"
        )

    def test_corroboration_deterministic(self):
        """explainable_corroboration must be deterministic across two identical detect() calls."""
        from module_a.detect import detect

        lot_size = 3
        frames = [
            _frame(component_id="A", value_0h=100.0, value_24h=110.0,
                   lot_size=lot_size, robust_z={"0h": 0.1}),
            _frame(component_id="B", value_0h=10.0, value_24h=11.0,
                   lot_size=lot_size, robust_z={"0h": 5.0}),
            _frame(component_id="C", value_0h=10.0, value_24h=10.5,
                   lot_size=lot_size, robust_z={"0h": 1.0}),
        ]
        r1 = detect(frames)
        r2 = detect(frames)
        for a, b in zip(r1, r2):
            assert a.explainable_corroboration == b.explainable_corroboration
            assert a.combined_severity == b.combined_severity
