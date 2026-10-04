"""module_a/fnfp.py - what the Settings "FN:FP cost ratio" does to Module A (session I3 Part 4).

Under the default (absolute, V1F) scoring the two tier cut-offs on the severity index s are constants tuned once by the cost-sensitive
optimizer: REVIEW 2.956 (FN:FP 20:1), REJECT 3.419 (10:1). This module makes the Settings ratio R select them again: REJECT is the
cost-optimal cut at FN:FP = R, REVIEW the one at 2R (the same 2:1 pairing the constants have), read from the table below by
interpolation on log(R). R = 10 returns the shipped constants exactly.

PROVENANCE: `harness.scoring.tune_threshold` on the TUNING side only (seed 6101, five generator families, 38,500 parts, V1F scores), run by
`python -m scripts.fnfp_threshold_table` on 2026-10-04; output kept in docs/evidence_data/fnfp/threshold_table.csv. The R = 10 row below is the
shipped constants (the optimizer gives REVIEW 2.9561, REJECT 3.4414 on these saved scores: within 0.05 of the constants, so the table
reproduces them). SYNTHETIC labels; the table says what the optimizer picks on synthetic tuning data, not what a real fab's costs would pick.
Ratios outside [FN_FP_RATIO_MIN, FN_FP_RATIO_MAX] are not supported (the tuning table stops there: at 100:1 REVIEW is s = 0.99 and flags 44%
of tuning parts).
"""
from __future__ import annotations

import math

from module_a.settings import ABSOLUTE_REJECT_THRESHOLD, ABSOLUTE_REVIEW_THRESHOLD

FN_FP_RATIO_MIN: float = 2.0
FN_FP_RATIO_MAX: float = 50.0
DEFAULT_FN_FP_RATIO: float = 10.0

# (ratio R, REVIEW s (optimizer at 2R), REJECT s (optimizer at R)); higher R -> lower or equal cut-offs.
FN_FP_THRESHOLD_TABLE: tuple[tuple[float, float, float], ...] = (
    (2.0, 4.3268, 5.4574),
    (3.0, 4.0935, 4.8228),
    (5.0, 3.4414, 4.0935),
    (7.0, 3.1413, 3.7741),
    (10.0, ABSOLUTE_REVIEW_THRESHOLD, ABSOLUTE_REJECT_THRESHOLD),  # the shipped constants (optimizer: 2.9561 / 3.4414)
    (15.0, 2.8104, 3.1413),
    (20.0, 2.4677, 2.9561),
    (30.0, 2.1115, 2.8104),
    (50.0, 1.7234, 2.4522),
)


def thresholds_for_ratio(ratio: float) -> tuple[float, float]:
    """(REVIEW s, REJECT s) for a FN:FP ratio, interpolated linearly on log(ratio) between table rows."""
    r = float(ratio)
    if not math.isfinite(r) or not (FN_FP_RATIO_MIN <= r <= FN_FP_RATIO_MAX):
        raise ValueError(f"fn_fp_cost_ratio must be between {FN_FP_RATIO_MIN:g} and {FN_FP_RATIO_MAX:g}, got {ratio!r}")
    rows = FN_FP_THRESHOLD_TABLE
    for row_r, row_review, row_reject in rows:  # a table row is returned exactly (the default 10 is the shipped constants)
        if r == row_r:
            return row_review, row_reject
    for (r0, v0, j0), (r1, v1, j1) in zip(rows, rows[1:]):
        if r0 <= r <= r1:
            w = (math.log(r) - math.log(r0)) / (math.log(r1) - math.log(r0))
            return v0 + w * (v1 - v0), j0 + w * (j1 - j0)
    raise AssertionError("unreachable: the table spans the supported range")
