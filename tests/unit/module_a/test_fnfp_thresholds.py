"""Session I3 Part 4: the Settings FN:FP ratio selects Module A's REVIEW / REJECT cut-offs."""
import math

import numpy as np
import pytest

from module_a import fnfp
from module_a.fnfp import FN_FP_THRESHOLD_TABLE, thresholds_for_ratio
from module_a.settings import (ABSOLUTE_REJECT_THRESHOLD, ABSOLUTE_REVIEW_THRESHOLD, module_a_scoring_config)

GRID = np.geomspace(fnfp.FN_FP_RATIO_MIN, fnfp.FN_FP_RATIO_MAX, 200)


def test_default_ratio_returns_the_shipped_constants_exactly():
    assert thresholds_for_ratio(10.0) == (ABSOLUTE_REVIEW_THRESHOLD, ABSOLUTE_REJECT_THRESHOLD) == (2.956, 3.419)
    cfg = module_a_scoring_config()
    assert (cfg.review_threshold, cfg.reject_threshold) == (2.956, 3.419)
    cfg10 = module_a_scoring_config(10.0)
    assert (cfg10.review_threshold, cfg10.reject_threshold) == (2.956, 3.419)


def test_table_rows_are_monotone_and_review_never_exceeds_reject():
    ratios = [r for r, _, _ in FN_FP_THRESHOLD_TABLE]
    assert ratios == sorted(ratios) and ratios[0] == fnfp.FN_FP_RATIO_MIN and ratios[-1] == fnfp.FN_FP_RATIO_MAX
    for (_, v0, j0), (_, v1, j1) in zip(FN_FP_THRESHOLD_TABLE, FN_FP_THRESHOLD_TABLE[1:]):
        assert v1 <= v0 and j1 <= j0
    assert all(v <= j for _, v, j in FN_FP_THRESHOLD_TABLE)


def test_monotone_and_ordered_on_a_fine_grid():
    prev = None
    for r in GRID:
        review, reject = thresholds_for_ratio(float(r))
        assert review <= reject
        if prev is not None:
            assert review <= prev[0] + 1e-12 and reject <= prev[1] + 1e-12  # higher ratio: lower or equal thresholds
        prev = (review, reject)


def test_interpolation_is_linear_in_log_ratio():
    (r0, v0, j0), (r1, v1, j1) = FN_FP_THRESHOLD_TABLE[2], FN_FP_THRESHOLD_TABLE[3]  # 5 and 7
    mid = math.sqrt(r0 * r1)
    review, reject = thresholds_for_ratio(mid)
    assert review == pytest.approx((v0 + v1) / 2) and reject == pytest.approx((j0 + j1) / 2)
    for r, v, j in FN_FP_THRESHOLD_TABLE:  # table rows are hit exactly
        assert thresholds_for_ratio(r) == pytest.approx((v, j))


@pytest.mark.parametrize("bad", [0, -1, 1.99, 50.01, 100, float("nan"), float("inf")])
def test_unsupported_ratios_are_rejected(bad):
    with pytest.raises(ValueError):
        thresholds_for_ratio(bad)


def test_the_table_is_what_the_optimizer_gives_on_tuning_data():
    """Reproduces the constants (4a): within 0.05 in s at the default; and the stored table equals a fresh optimizer run."""
    from scripts.fnfp_threshold_table import table

    t = table().set_index("ratio")
    assert abs(t.loc[10, "review_s"] - ABSOLUTE_REVIEW_THRESHOLD) < 0.05
    assert abs(t.loc[10, "reject_s"] - ABSOLUTE_REJECT_THRESHOLD) < 0.05
    for r, review, reject in FN_FP_THRESHOLD_TABLE:
        if r == 10.0:
            continue
        assert t.loc[int(r), "review_s"] == pytest.approx(review, abs=1e-4)
        assert t.loc[int(r), "reject_s"] == pytest.approx(reject, abs=1e-4)
