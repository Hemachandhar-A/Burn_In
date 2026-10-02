"""E5 step 1: the three named industry baselines (context.md 1.6) - static absolute limits, fixed delta
limits (space-spec style), and AEC-Q001 static/dynamic PAT (robust mean +/- 6 robust sigma, robust mean =
median, robust sigma = IQR/1.35).

Every formula is checked against hand-computed inputs/outputs, not against a second copy of itself: the
point of benchmarking against named industry methods is that a reviewer can check the baseline math by hand
(context.md 3.4 (3)).
"""
import math

import numpy as np
import pandas as pd
import pytest

from contracts import LotDataset, Reading, ScreeningConfig
from generator.lot import generate_lot
from generator.parameters import PARAMETERS
from harness.industry_baselines import (
    PAT_SIGMA_MULTIPLIER,
    ROBUST_SIGMA_DIVISOR,
    DeltaLimit,
    Limit,
    checkpoint_frame,
    default_datasheet_limits,
    default_delta_limits,
    dynamic_pat_scores,
    fit_static_pat,
    fixed_delta_scores,
    part_level,
    robust_center_sigma,
    static_limit_scores,
    static_pat_scores,
)

SCORE_COLUMNS = ["component_id", "parameter", "score", "flagged", "worst_checkpoint", "evaluable"]


def _reading(**fields) -> Reading:
    """Reading rejects NaN/inf at construction since 5363f4a (CONTRACT_CHANGES.md, 2026-09-27 Lead). A
    non-finite value can then only arrive by bypassing validation (model_construct), which is what these
    tests simulate: the baselines' own non-finite handling stays a second line of defence."""
    if all(math.isfinite(fields[k]) for k in ("value", "checkpoint_hour")):
        return Reading(**fields)
    return Reading.model_construct(**fields)


def _lot(rows, lot_id="L1", part_number="PN-1", status="COMPLETE"):
    """rows: (component_id, parameter, checkpoint_hour, value)."""
    return LotDataset(
        lot_id=lot_id, part_number=part_number, status=status, account_id="acct-test",
        readings=[_reading(component_id=c, lot_id=lot_id, part_number=part_number, manufacturer="M",
                           date_code="2601", parameter=p, checkpoint_hour=h, value=v, unit="uA")
                  for c, p, h, v in rows],
    )


def _single_checkpoint_lot(values, hour=0.0, parameter="iddq", **kwargs):
    return _lot([(f"C{i:03d}", parameter, hour, v) for i, v in enumerate(values)], **kwargs)


def _row(frame, component_id, parameter="iddq"):
    match = frame[(frame.component_id == component_id) & (frame.parameter == parameter)]
    assert len(match) == 1
    return match.iloc[0]


# 10 parts at 9, 20 at 10, 9 at 11, and one at 45 - 40 parts, above the 30-part AEC-Q001 minimum.
# Sorted: idx 0-9 = 9, idx 10-29 = 10, idx 30-38 = 11, idx 39 = 45.
# median = 10; q25 at position 0.25*39 = 9.75 -> 9 + 0.75*(10-9) = 9.75; q75 at 29.25 -> 10 + 0.25*(11-10) = 10.25
# IQR = 0.5, robust sigma = 0.5/1.35, 6 sigma = 3/1.35 = 2.2222..., limits = [7.7778, 12.2222]
PAT_VALUES = [9.0] * 10 + [10.0] * 20 + [11.0] * 9 + [45.0]
PAT_SIX_SIGMA = 6 * 0.5 / 1.35


# --- the named constants are the published ones -------------------------------------

def test_pat_constants_match_the_published_formula():
    assert PAT_SIGMA_MULTIPLIER == 6.0
    assert ROBUST_SIGMA_DIVISOR == 1.35


# --- robust statistics ---------------------------------------------------------------

def test_robust_center_is_median_and_sigma_is_iqr_over_1_35():
    center, sigma = robust_center_sigma([1, 2, 3, 4, 5, 6, 7, 8, 9])
    assert center == 5.0
    assert sigma == pytest.approx((7.0 - 3.0) / 1.35)


def test_robust_stats_on_the_hand_worked_pat_population():
    center, sigma = robust_center_sigma(PAT_VALUES)
    assert center == 10.0
    assert sigma == pytest.approx(0.5 / 1.35)


def test_robust_stats_resist_the_outlier_they_are_meant_to_catch():
    clean = robust_center_sigma([9.0] * 10 + [10.0] * 20 + [11.0] * 10)
    contaminated = robust_center_sigma(PAT_VALUES)
    assert clean == pytest.approx(contaminated)


def test_robust_stats_ignore_non_finite_values():
    assert robust_center_sigma([1, 2, 3, float("nan"), 4, 5]) == robust_center_sigma([1, 2, 3, 4, 5])


def test_robust_stats_reject_empty_input():
    with pytest.raises(ValueError):
        robust_center_sigma([])
    with pytest.raises(ValueError):
        robust_center_sigma([float("nan")])


# --- dynamic PAT (per lot) -----------------------------------------------------------

def test_dpat_flags_the_outlier_and_only_the_outlier():
    frame = dynamic_pat_scores(_single_checkpoint_lot(PAT_VALUES))
    assert list(frame.columns[:6]) == SCORE_COLUMNS
    flagged = set(frame[frame.flagged].component_id)
    assert flagged == {"C039"}


def test_dpat_score_is_deviation_over_six_robust_sigma():
    frame = dynamic_pat_scores(_single_checkpoint_lot(PAT_VALUES))
    assert _row(frame, "C039").score == pytest.approx((45.0 - 10.0) / PAT_SIX_SIGMA)  # 15.75
    assert _row(frame, "C039").score == pytest.approx(15.75)
    assert _row(frame, "C000").score == pytest.approx(1.0 / PAT_SIX_SIGMA)  # 9 vs median 10
    assert _row(frame, "C015").score == 0.0  # exactly at the median


def test_dpat_limit_boundary_is_inclusive_pass():
    # A value exactly on median + 6 sigma is inside the limit - flagged means strictly outside.
    edge = 10.0 + PAT_SIX_SIGMA
    frame = dynamic_pat_scores(_single_checkpoint_lot([9.0] * 10 + [10.0] * 20 + [11.0] * 9 + [edge]))
    row = _row(frame, "C039")
    assert row.score == pytest.approx(1.0)
    assert not row.flagged


def test_dpat_flags_low_side_outliers_too():
    frame = dynamic_pat_scores(_single_checkpoint_lot([9.0] * 10 + [10.0] * 20 + [11.0] * 9 + [1.0]))
    assert _row(frame, "C039").flagged


def test_dpat_limits_are_recomputed_per_lot():
    # The same part value is normal in one lot and an outlier in another - the whole point of dynamic PAT.
    low_lot = dynamic_pat_scores(_single_checkpoint_lot(PAT_VALUES[:-1] + [13.0]))
    shifted = [v + 3.0 for v in PAT_VALUES[:-1]] + [13.0]
    high_lot = dynamic_pat_scores(_single_checkpoint_lot(shifted))
    assert _row(low_lot, "C039").flagged
    assert not _row(high_lot, "C039").flagged


def test_dpat_computes_limits_per_checkpoint_and_parameter_separately():
    rows = []
    for i, v in enumerate(PAT_VALUES[:-1] + [10.0]):
        rows.append((f"C{i:03d}", "iddq", 0.0, v))
        rows.append((f"C{i:03d}", "iddq", 24.0, v * 2))  # different scale at 24h
        rows.append((f"C{i:03d}", "leakage", 0.0, v))
    rows[-2] = ("C039", "iddq", 24.0, 45.0)  # outlier only at 24h (2x-scale median is 20)
    frame = dynamic_pat_scores(_lot(rows))
    row = _row(frame, "C039")
    assert row.flagged
    assert row.worst_checkpoint == 24.0
    assert not _row(frame, "C039", "leakage").flagged
    assert len(frame) == 40 * 2  # one row per (component, parameter)


def test_dpat_part_score_is_its_worst_checkpoint():
    rows = [(f"C{i:03d}", "iddq", h, v) for i, v in enumerate(PAT_VALUES) for h in (0.0, 24.0)]
    rows = [r if not (r[0] == "C039" and r[2] == 0.0) else ("C039", "iddq", 0.0, 10.0) for r in rows]
    frame = dynamic_pat_scores(_lot(rows))
    assert _row(frame, "C039").worst_checkpoint == 24.0
    assert _row(frame, "C039").score == pytest.approx(15.75)


def test_dpat_zero_robust_sigma_flags_any_deviation():
    # Quantized lots can have IQR = 0. The literal formula then collapses the limits onto the median:
    # anything off-median is outside them, anything on it is not. No invented sigma floor.
    frame = dynamic_pat_scores(_single_checkpoint_lot([10.0] * 39 + [10.5]))
    assert _row(frame, "C039").flagged
    assert math.isinf(_row(frame, "C039").score)
    assert _row(frame, "C000").score == 0.0
    assert not _row(frame, "C000").flagged


def test_dpat_small_lot_without_fallback_is_unevaluable():
    # 29 parts is below the AEC-Q001 30-part minimum (ScreeningConfig.small_lot_fallback_threshold). Without
    # pooled limits the lot is not judged at all - neither flagged nor passed - rather than judged on robust
    # statistics too small to hold (and without one short group crashing the whole lot).
    frame = dynamic_pat_scores(_single_checkpoint_lot([10.0] * 28 + [45.0]))
    assert not frame.evaluable.any() and not frame.flagged.any()
    assert set(frame.limit_source) == {"none"}


def test_dpat_small_lot_uses_pooled_static_pat_fallback():
    reference = [_single_checkpoint_lot(PAT_VALUES[:-1] + [10.0], lot_id=f"R{k}") for k in range(2)]
    pooled = fit_static_pat(reference)
    small = _single_checkpoint_lot([10.0] * 28 + [45.0], lot_id="SMALL")
    frame = dynamic_pat_scores(small, fallback=pooled)
    assert set(frame.limit_source) == {"pooled"}
    assert _row(frame, "C028").flagged
    big = dynamic_pat_scores(_single_checkpoint_lot(PAT_VALUES))
    assert set(big.limit_source) == {"lot"}


def test_dpat_small_lot_threshold_comes_from_config():
    lot = _single_checkpoint_lot([9.0, 10.0, 10.0, 11.0, 45.0] * 4)  # 20 parts
    frame = dynamic_pat_scores(lot, config=ScreeningConfig(small_lot_fallback_threshold=20))
    assert set(frame.limit_source) == {"lot"}
    too_small = dynamic_pat_scores(lot, config=ScreeningConfig(small_lot_fallback_threshold=21))
    assert set(too_small.limit_source) == {"none"} and not too_small.evaluable.any()


def test_dpat_excludes_nan_readings_from_the_limits_without_flagging_them():
    rows = [(f"C{i:03d}", "iddq", 0.0, v) for i, v in enumerate(PAT_VALUES)]
    rows.append(("C040", "iddq", 0.0, float("nan")))
    frame = dynamic_pat_scores(_lot(rows))
    nan_row = _row(frame, "C040")
    assert not nan_row.evaluable
    assert not nan_row.flagged
    assert math.isnan(nan_row.score)
    assert _row(frame, "C039").score == pytest.approx(15.75)  # limits unchanged by the NaN


# --- static PAT (pooled reference population) ----------------------------------------

def test_static_pat_limits_come_from_the_pooled_reference_not_the_lot():
    reference = [_single_checkpoint_lot(PAT_VALUES[:-1] + [10.0], lot_id=f"R{k}") for k in range(3)]
    limits = fit_static_pat(reference)
    center, sigma = limits.center_sigma("iddq", 0.0)
    assert center == 10.0
    assert sigma == pytest.approx(robust_center_sigma((PAT_VALUES[:-1] + [10.0]) * 3)[1])
    # A lot shifted up by 3 is entirely outside pooled static limits, though DPAT would accept it.
    shifted = _single_checkpoint_lot([v + 3.0 for v in PAT_VALUES[:-1]] + [13.0], lot_id="T1")
    static = static_pat_scores(shifted, limits)
    assert static.flagged.mean() > 0.9
    assert dynamic_pat_scores(shifted).flagged.sum() == 0


def test_static_pat_hand_worked_limits():
    # Pooled reference = PAT_VALUES without its outlier, twice: 20 at 9, 40 at 10, 20 at 11 (n = 80).
    # q25 at 0.25*79 = 19.75 -> 9 + 0.75 = 9.75; q75 at 59.25 -> 10 + 0.25 = 10.25; sigma = 0.5/1.35.
    base = [9.0] * 10 + [10.0] * 20 + [11.0] * 10
    limits = fit_static_pat([_single_checkpoint_lot(base, lot_id=f"R{k}") for k in range(2)])
    center, sigma = limits.center_sigma("iddq", 0.0)
    assert (center, sigma) == (10.0, pytest.approx(0.5 / 1.35))
    frame = static_pat_scores(_single_checkpoint_lot([12.0, 12.3] + [10.0] * 30, lot_id="T"), limits)
    assert not _row(frame, "C000").flagged  # 12.0 < 12.222
    assert _row(frame, "C001").flagged  # 12.3 > 12.222


def test_static_pat_refuses_to_score_a_lot_from_its_own_reference_population():
    # Split by lot (AGENTS.md rule 8): a reference lot scored by limits it helped fit is leaked data.
    reference = [_single_checkpoint_lot(PAT_VALUES, lot_id=f"R{k}") for k in range(2)]
    limits = fit_static_pat(reference)
    with pytest.raises(ValueError, match="reference"):
        static_pat_scores(reference[0], limits)


def test_static_pat_is_scoped_to_one_part_number():
    a = _single_checkpoint_lot(PAT_VALUES, lot_id="R1", part_number="PN-A")
    b = _single_checkpoint_lot(PAT_VALUES, lot_id="R2", part_number="PN-B")
    with pytest.raises(ValueError, match="part number"):
        fit_static_pat([a, b])
    limits = fit_static_pat([a])
    with pytest.raises(ValueError, match="part number"):
        static_pat_scores(_single_checkpoint_lot(PAT_VALUES, lot_id="T", part_number="PN-B"), limits)


def test_static_pat_rejects_bad_reference_populations():
    with pytest.raises(ValueError):
        fit_static_pat([])
    lot = _single_checkpoint_lot(PAT_VALUES, lot_id="R1")
    with pytest.raises(ValueError, match="duplicate"):
        fit_static_pat([lot, lot])
    with pytest.raises(ValueError, match="30"):  # no group reaches the minimum -> nothing to fit at all
        fit_static_pat([_single_checkpoint_lot([10.0] * 29, lot_id="R1")])
    with pytest.raises(TypeError):
        fit_static_pat([{"lot_id": "R1"}])


def test_static_pat_marks_parameters_it_has_no_limits_for_as_unevaluable():
    limits = fit_static_pat([_single_checkpoint_lot(PAT_VALUES, lot_id="R1")])
    frame = static_pat_scores(_single_checkpoint_lot(PAT_VALUES, lot_id="T", parameter="vth"), limits)
    assert not frame.evaluable.any()
    assert not frame.flagged.any()
    assert len(frame) == len(PAT_VALUES)  # present, not silently dropped (context.md 5.9)


def test_static_pat_limits_are_read_only():
    limits = fit_static_pat([_single_checkpoint_lot(PAT_VALUES, lot_id="R1")])
    with pytest.raises(TypeError):
        limits.center[("iddq", 0.0)] = 0.0


# --- static absolute (datasheet) limits ----------------------------------------------

def test_static_limit_misses_the_in_spec_anomaly_by_construction():
    # The problem statement's worked example: lot median 10, part at 45, datasheet limit 50. A static limit
    # passes it - exactly the gap Module A exists to close; DPAT catches it.
    lot = _single_checkpoint_lot(PAT_VALUES)
    static = static_limit_scores(lot, {"iddq": Limit(upper=50.0)})
    assert not static.flagged.any()
    assert _row(static, "C039").score == pytest.approx(45.0 / 50.0)
    assert _row(dynamic_pat_scores(lot), "C039").flagged


def test_static_upper_limit_score_and_boundary():
    lot = _single_checkpoint_lot([50.0, 51.0, 10.0])
    frame = static_limit_scores(lot, {"iddq": Limit(upper=50.0)})
    assert not _row(frame, "C000").flagged  # exactly on the limit passes
    assert _row(frame, "C000").score == 1.0
    assert _row(frame, "C001").flagged
    assert _row(frame, "C001").score == pytest.approx(51.0 / 50.0)
    assert _row(frame, "C002").score == pytest.approx(0.2)


def test_static_lower_limit_score():
    lot = _single_checkpoint_lot([4.0, 5.0, 2.0])
    frame = static_limit_scores(lot, {"iddq": Limit(lower=4.0, upper=50.0)})
    assert not _row(frame, "C000").flagged
    assert _row(frame, "C002").flagged
    assert _row(frame, "C002").score == pytest.approx(4.0 / 2.0)
    assert _row(frame, "C001").score == pytest.approx(max(5.0 / 50.0, 4.0 / 5.0))


def test_static_limit_applies_at_every_checkpoint():
    rows = [("C0", "iddq", 0.0, 10.0), ("C0", "iddq", 24.0, 20.0), ("C0", "iddq", 168.0, 60.0)]
    frame = static_limit_scores(_lot(rows), {"iddq": Limit(upper=50.0)})
    row = _row(frame, "C0")
    assert row.flagged and row.worst_checkpoint == 168.0 and row.score == pytest.approx(1.2)


def test_static_limit_non_positive_reading_below_a_lower_limit_is_flagged():
    frame = static_limit_scores(_single_checkpoint_lot([0.0, -1.0]), {"iddq": Limit(lower=1.0)})
    assert frame.flagged.all()


def test_static_limit_without_a_limit_for_a_parameter_is_unevaluable_not_passed():
    lot = _lot([("C0", "iddq", 0.0, 10.0), ("C0", "vth", 0.0, 0.4)])
    frame = static_limit_scores(lot, {"iddq": Limit(upper=50.0)})
    assert _row(frame, "C0").evaluable
    vth = _row(frame, "C0", "vth")
    assert not vth.evaluable and not vth.flagged


@pytest.mark.parametrize("kwargs, error", [
    ({}, ValueError),
    ({"upper": 0.0}, ValueError),
    ({"lower": -1.0}, ValueError),
    ({"lower": 5.0, "upper": 5.0}, ValueError),
    ({"lower": 6.0, "upper": 5.0}, ValueError),
    ({"upper": float("inf")}, ValueError),
    ({"upper": float("nan")}, ValueError),
    ({"upper": "50"}, TypeError),
    ({"upper": True}, TypeError),
])
def test_limit_validation(kwargs, error):
    with pytest.raises(error):
        Limit(**kwargs)


# --- fixed delta limits (space-spec style) -------------------------------------------

def test_delta_relative_limit_hand_worked():
    # 0h = 10, allowed = 20% of 10 = 2. 24h delta 1.5 passes; 168h delta 2.5 fails with score 1.25.
    rows = [("C0", "iddq", 0.0, 10.0), ("C0", "iddq", 24.0, 11.5), ("C0", "iddq", 168.0, 12.5)]
    frame = fixed_delta_scores(_lot(rows), {"iddq": DeltaLimit(relative=0.2)})
    row = _row(frame, "C0")
    assert row.flagged and row.score == pytest.approx(1.25) and row.worst_checkpoint == 168.0


def test_delta_is_two_sided():
    rows = [("C0", "iddq", 0.0, 10.0), ("C0", "iddq", 24.0, 7.0)]
    frame = fixed_delta_scores(_lot(rows), {"iddq": DeltaLimit(relative=0.2)})
    assert _row(frame, "C0").flagged
    assert _row(frame, "C0").score == pytest.approx(1.5)


def test_delta_absolute_and_relative_take_whichever_is_greater():
    # "+/-20% or +/-3 uA, whichever is greater": at 0h = 10 the absolute 3 governs, at 0h = 100 the 20 does.
    rows = [("A", "iddq", 0.0, 10.0), ("A", "iddq", 168.0, 12.5),
            ("B", "iddq", 0.0, 100.0), ("B", "iddq", 168.0, 125.0)]
    frame = fixed_delta_scores(_lot(rows), {"iddq": DeltaLimit(absolute=3.0, relative=0.2)})
    assert _row(frame, "A").score == pytest.approx(2.5 / 3.0) and not _row(frame, "A").flagged
    assert _row(frame, "B").score == pytest.approx(25.0 / 20.0) and _row(frame, "B").flagged


def test_delta_boundary_is_inclusive_pass():
    rows = [("C0", "iddq", 0.0, 10.0), ("C0", "iddq", 168.0, 13.0)]
    frame = fixed_delta_scores(_lot(rows), {"iddq": DeltaLimit(absolute=3.0)})
    assert _row(frame, "C0").score == pytest.approx(1.0) and not _row(frame, "C0").flagged


def test_delta_is_measured_from_the_pre_burn_in_read_not_the_previous_checkpoint():
    # Two +1.5 steps: each step is within the absolute 2, the cumulative 3 from 0h is not.
    rows = [("C0", "iddq", 0.0, 10.0), ("C0", "iddq", 24.0, 11.5), ("C0", "iddq", 96.0, 13.0)]
    frame = fixed_delta_scores(_lot(rows), {"iddq": DeltaLimit(absolute=2.0)})
    assert _row(frame, "C0").flagged and _row(frame, "C0").worst_checkpoint == 96.0


def test_delta_without_a_pre_burn_in_read_is_unevaluable_never_imputed():
    # AGENTS.md rule 7: no 0h read means no delta, not a delta from a guessed 0h value.
    rows = [("C0", "iddq", 24.0, 11.0), ("C0", "iddq", 168.0, 99.0),
            ("C1", "iddq", 0.0, float("nan")), ("C1", "iddq", 168.0, 99.0)]
    frame = fixed_delta_scores(_lot(rows), {"iddq": DeltaLimit(relative=0.2)})
    for cid in ("C0", "C1"):
        row = _row(frame, cid)
        assert not row.evaluable and not row.flagged and math.isnan(row.score)


def test_delta_with_only_a_pre_burn_in_read_is_unevaluable():
    frame = fixed_delta_scores(_lot([("C0", "iddq", 0.0, 10.0)]), {"iddq": DeltaLimit(relative=0.2)})
    assert not _row(frame, "C0").evaluable


def test_delta_relative_limit_on_a_zero_initial_read():
    rows = [("A", "iddq", 0.0, 0.0), ("A", "iddq", 24.0, 0.0),
            ("B", "iddq", 0.0, 0.0), ("B", "iddq", 24.0, 0.1)]
    frame = fixed_delta_scores(_lot(rows), {"iddq": DeltaLimit(relative=0.2)})
    assert _row(frame, "A").score == 0.0 and not _row(frame, "A").flagged
    assert math.isinf(_row(frame, "B").score) and _row(frame, "B").flagged


@pytest.mark.parametrize("kwargs, error", [
    ({}, ValueError),
    ({"absolute": 0.0}, ValueError),
    ({"relative": -0.1}, ValueError),
    ({"absolute": float("inf")}, ValueError),
    ({"relative": "0.2"}, TypeError),
])
def test_delta_limit_validation(kwargs, error):
    with pytest.raises(error):
        DeltaLimit(**kwargs)


# --- checkpoint alignment ------------------------------------------------------------

def test_jittered_readout_hours_align_to_their_nominal_checkpoint():
    rows = [("C0", "iddq", 0.0, 10.0), ("C0", "iddq", 23.4, 11.0), ("C0", "iddq", 97.1, 12.0)]
    frame = checkpoint_frame(_lot(rows))
    assert list(frame.checkpoint) == [0.0, 24.0, 96.0]
    assert list(frame.checkpoint_hour) == [0.0, 23.4, 97.1]


def test_readout_hour_between_nominal_checkpoints_is_rejected():
    with pytest.raises(ValueError, match="checkpoint"):
        checkpoint_frame(_lot([("C0", "iddq", 60.0, 10.0)]))


def test_custom_nominal_schedule():
    frame = checkpoint_frame(_lot([("C0", "iddq", 49.0, 10.0)]), nominal_hours=(0.0, 48.0, 168.0))
    assert list(frame.checkpoint) == [48.0]


def test_duplicate_reading_for_one_checkpoint_is_rejected():
    rows = [("C0", "iddq", 24.0, 10.0), ("C0", "iddq", 24.5, 11.0)]
    with pytest.raises(ValueError, match="duplicate"):
        checkpoint_frame(_lot(rows))


def test_non_dataset_input_is_rejected():
    with pytest.raises(TypeError):
        dynamic_pat_scores({"readings": []})


def test_empty_dataset_gives_an_empty_frame():
    frame = static_limit_scores(_lot([]), {"iddq": Limit(upper=50.0)})
    assert frame.empty and list(frame.columns[:6]) == SCORE_COLUMNS


# --- part-level rollup ---------------------------------------------------------------

def test_part_level_takes_the_worst_parameter():
    frame = pd.DataFrame({
        "component_id": ["A", "A", "B", "B"],
        "parameter": ["iddq", "leakage", "iddq", "leakage"],
        "score": [0.5, 1.5, 0.2, float("nan")],
        "flagged": [False, True, False, False],
        "worst_checkpoint": [24.0, 168.0, 0.0, float("nan")],
        "evaluable": [True, True, True, False],
    })
    parts = part_level(frame).set_index("component_id")
    assert parts.loc["A"].flagged and parts.loc["A"].worst_parameter == "leakage"
    assert parts.loc["A"].score == 1.5
    assert not parts.loc["B"].flagged and parts.loc["B"].worst_parameter == "iddq"
    assert parts.loc["B"].evaluable


def test_part_level_part_with_nothing_evaluable():
    frame = pd.DataFrame({"component_id": ["A"], "parameter": ["vth"], "score": [float("nan")],
                          "flagged": [False], "worst_checkpoint": [float("nan")], "evaluable": [False]})
    row = part_level(frame).iloc[0]
    assert not row.evaluable and not row.flagged and row.worst_parameter is None


# --- defaults and end-to-end on generated data ---------------------------------------

def test_default_limits_cover_every_trained_parameter():
    assert set(default_datasheet_limits()) == set(PARAMETERS)
    assert set(default_delta_limits()) == set(PARAMETERS)
    for name, limit in default_datasheet_limits().items():
        assert limit.upper > np.exp(PARAMETERS[name].lot_center_mu)  # well above a typical lot center


def test_all_baselines_run_on_a_generated_lot():
    lot = generate_lot("L1", "PN-1", 11, account_id="harness").dataset
    reference = fit_static_pat([generate_lot(f"R{k}", "PN-1", 11, account_id="harness").dataset
                                for k in range(3)])
    n_parts = len({r.component_id for r in lot.readings})
    frames = [static_limit_scores(lot, default_datasheet_limits()),
              fixed_delta_scores(lot, default_delta_limits()),
              static_pat_scores(lot, reference),
              dynamic_pat_scores(lot)]
    for frame in frames:
        assert len(frame) == n_parts * len(PARAMETERS)
        assert frame.evaluable.all()
        assert frame.score.notna().all()


def test_baselines_are_deterministic():
    lot = generate_lot("L1", "PN-1", 3, account_id="harness").dataset
    pd.testing.assert_frame_equal(dynamic_pat_scores(lot), dynamic_pat_scores(lot))
    pd.testing.assert_frame_equal(fixed_delta_scores(lot, default_delta_limits()),
                                  fixed_delta_scores(lot, default_delta_limits()))


def test_default_static_limits_almost_never_flag_a_healthy_generated_part():
    # Datasheet limits are set wide of the healthy population - which is why they miss in-spec anomalies.
    flagged_healthy = total_healthy = 0
    for k in range(10):
        generated = generate_lot(f"L{k}", "PN-1", 5, account_id="harness")
        healthy = {p.component_id for p in generated.ground_truth.baselines.parts if not p.is_defective}
        parts = part_level(static_limit_scores(generated.dataset, default_datasheet_limits()))
        parts = parts[parts.component_id.isin(healthy)]
        flagged_healthy += int(parts.flagged.sum())
        total_healthy += len(parts)
    assert flagged_healthy / total_healthy < 0.01
