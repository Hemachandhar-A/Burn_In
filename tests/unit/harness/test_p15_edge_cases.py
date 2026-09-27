"""P1.5 edge-case review: industry baselines (E5 step 1) and held-out test sets (E5 step 2).

Each test names a failure mode found on review - floating-point limit boundaries, non-finite readings,
malformed schedules and datasets, unit mismatches, partial populations, the information horizon (AGENTS.md
rule 6), input-order independence, and held-out-set integrity.
"""
import math
import random
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from contracts import LotDataset, Reading, ScreeningConfig
from generator.families import FAMILIES
from generator.lot import generate_lot
from harness.held_out import (
    HeldOutTestSet,
    archetype_counts,
    generate_held_out_set,
    generate_held_out_sets,
)
from harness.industry_baselines import (
    DeltaLimit,
    Limit,
    PatLimits,
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

NAN, INF = float("nan"), float("inf")


def _reading(**fields) -> Reading:
    """Reading rejects NaN/inf at construction since 5363f4a (CONTRACT_CHANGES.md, 2026-09-27 Lead). A
    non-finite value can then only arrive by bypassing validation (model_construct), which is what these
    tests simulate: the baselines' own non-finite handling stays a second line of defence."""
    if all(math.isfinite(fields[k]) for k in ("value", "checkpoint_hour")):
        return Reading(**fields)
    return Reading.model_construct(**fields)


def _lot(rows, lot_id="L1", part_number="PN-1", unit="uA", status="COMPLETE"):
    """rows: (component_id, parameter, checkpoint_hour, value[, unit])."""
    readings = []
    for row in rows:
        c, p, h, v = row[:4]
        readings.append(_reading(component_id=c, lot_id=lot_id, part_number=part_number, manufacturer="M",
                                 date_code="2601", parameter=p, checkpoint_hour=h, value=v,
                                 unit=row[4] if len(row) > 4 else unit))
    return LotDataset(lot_id=lot_id, part_number=part_number, status=status, account_id="acct", readings=readings)


def _flat(values, hour=0.0, parameter="iddq", **kwargs):
    return _lot([(f"C{i:03d}", parameter, hour, v) for i, v in enumerate(values)], **kwargs)


def _row(frame, component_id, parameter="iddq"):
    match = frame[(frame.component_id == component_id) & (frame.parameter == parameter)]
    assert len(match) == 1
    return match.iloc[0]


BASE_40 = [9.0] * 10 + [10.0] * 20 + [11.0] * 10


def _all_scorers(dataset, reference=None, **kwargs):
    out = {
        "static": static_limit_scores(dataset, default_datasheet_limits(), **kwargs),
        "delta": fixed_delta_scores(dataset, default_delta_limits(), **kwargs),
        "dpat": dynamic_pat_scores(dataset, **kwargs),
    }
    if reference is not None:
        out["static_pat"] = static_pat_scores(dataset, reference, **kwargs)
    return out


# =====================================================================================
# 1. Floating-point limit boundaries: "on the limit passes" must hold for the limit a reviewer computes
#    by hand (center + 6 sigma, initial + allowance), not only when the division happens to round kindly.
# =====================================================================================

def test_delta_value_exactly_on_the_hand_computed_limit_passes():
    # 0.1 + 0.2 = 0.30000000000000004 and (0.30000000000000004 - 0.1) / 0.2 = 1.0000000000000002.
    rows = [("A", "iddq", 0.0, 0.1), ("A", "iddq", 24.0, 0.1 + 0.2), ("A", "iddq", 96.0, 0.1 - 0.2)]
    row = _row(fixed_delta_scores(_lot(rows), {"iddq": DeltaLimit(absolute=0.2)}), "A")
    assert not row.flagged
    assert row.score <= 1.0


def test_delta_value_one_ulp_past_the_limit_is_flagged():
    over = math.nextafter(0.1 + 0.2, INF)
    row = _row(fixed_delta_scores(_lot([("A", "iddq", 0.0, 0.1), ("A", "iddq", 24.0, over)]),
                                  {"iddq": DeltaLimit(absolute=0.2)}), "A")
    assert row.flagged and row.score > 1.0


@pytest.mark.parametrize("upper", [0.3, 1 / 3, 50.0, 7.1, 1e-9])
def test_static_value_one_ulp_past_the_limit_is_flagged(upper):
    over = math.nextafter(upper, INF)
    frame = static_limit_scores(_flat([upper, over]), {"iddq": Limit(upper=upper)})
    assert not _row(frame, "C000").flagged and _row(frame, "C000").score <= 1.0
    assert _row(frame, "C001").flagged and _row(frame, "C001").score > 1.0


@pytest.mark.parametrize("center, sigma", [(0.1, 0.2 / 6), (10.0, 0.5 / 1.35), (1 / 3, 1 / 7), (0.7, 0.01)])
def test_static_pat_value_on_published_limit_passes_and_one_ulp_past_fails(center, sigma):
    limits = PatLimits(part_number="PN-1", reference_lot_ids=frozenset({"R"}), center={("iddq", 0.0): center},
                       sigma={("iddq", 0.0): sigma}, units={"iddq": "uA"}, nominal_hours=(0.0, 24.0, 96.0, 168.0))
    lower, upper = limits.limits("iddq", 0.0)
    assert (lower, upper) == (center - 6 * sigma, center + 6 * sigma)
    values = [upper, lower, math.nextafter(upper, INF), math.nextafter(lower, -INF)]
    frame = static_pat_scores(_flat(values), limits)
    assert list(frame.flagged) == [False, False, True, True]
    assert (frame.score > 1.0).tolist() == frame.flagged.tolist()


def test_dpat_value_on_its_lots_published_limit_passes():
    base = [0.1 * k for k in range(1, 40)]  # float-unfriendly values; the 40th part sits above q75
    center, sigma = robust_center_sigma(base + [1e6])
    upper = center + 6 * sigma
    assert robust_center_sigma(base + [upper]) == (center, sigma)  # placing it doesn't move the limits
    for value, expected in ((upper, False), (math.nextafter(upper, INF), True)):
        row = _row(dynamic_pat_scores(_flat(base + [value])), "C039")
        assert row.flagged == expected
        assert (row.score > 1.0) == expected


@pytest.mark.parametrize("family", list(FAMILIES))
def test_score_above_one_iff_flagged_on_generated_lots(family):
    lots = [generate_lot(f"L{k}", "PN-1", 3, account_id="h", family=family).dataset for k in range(4)]
    reference = fit_static_pat(lots[:3])
    for name, frame in _all_scorers(lots[3], reference).items():
        evaluable = frame[frame.evaluable]
        assert ((evaluable.score > 1.0) == evaluable.flagged).all(), name
        assert not frame[~frame.evaluable].flagged.any(), name


# =====================================================================================
# 2. Non-finite readings are "no measurement", never an automatic flag
# =====================================================================================

@pytest.mark.parametrize("bad", [INF, -INF, NAN])
def test_non_finite_reading_is_unevaluable_in_every_baseline(bad):
    rows = [(f"C{i:03d}", "iddq", h, v) for i, v in enumerate(BASE_40) for h in (0.0, 24.0)]
    rows.append(("X", "iddq", 0.0, 10.0))
    rows.append(("X", "iddq", 24.0, bad))
    lot = _lot(rows)
    reference = fit_static_pat([_lot(rows[:-2], lot_id="R")])
    for name, frame in _all_scorers(lot, reference).items():
        row = _row(frame, "X")
        assert not row.flagged, name
        if name != "delta":  # the 0h read is still judgeable by the snapshot baselines
            assert row.evaluable and row.worst_checkpoint == 0.0, name
        else:
            assert not row.evaluable, name


def test_non_finite_pre_burn_in_read_makes_delta_unevaluable():
    rows = [("A", "iddq", 0.0, INF), ("A", "iddq", 24.0, 10.0)]
    row = _row(fixed_delta_scores(_lot(rows), {"iddq": DeltaLimit(relative=0.2)}), "A")
    assert not row.evaluable and not row.flagged


def test_infinite_reading_does_not_enter_dpat_limits():
    with_inf = dynamic_pat_scores(_flat(BASE_40 + [INF]))
    assert _row(with_inf, "C039").score == pytest.approx(1.0 / (6 * 0.5 / 1.35))


# =====================================================================================
# 3. Malformed schedules and datasets
# =====================================================================================

def test_negative_readout_hour_is_rejected():
    with pytest.raises(ValueError, match="negative"):
        checkpoint_frame(_lot([("A", "iddq", -5.0, 1.0)]))


def test_nan_readout_hour_is_rejected():
    with pytest.raises(ValueError):
        checkpoint_frame(_lot([("A", "iddq", NAN, 1.0)]))


@pytest.mark.parametrize("nominal, error", [
    ((), ValueError),
    ((0.0, 24.0, 24.0, 168.0), ValueError),
    ((0.0, NAN, 168.0), ValueError),
    ((0.0, INF), ValueError),
    ((-24.0, 0.0), ValueError),
    ("0,24", TypeError),
    ((0.0, "24"), TypeError),
    ((0.0, True), TypeError),
])
def test_nominal_schedule_validation(nominal, error):
    with pytest.raises(error):
        checkpoint_frame(_lot([("A", "iddq", 0.0, 1.0)]), nominal_hours=nominal)


def test_unsorted_nominal_schedule_is_accepted():
    frame = checkpoint_frame(_lot([("A", "iddq", 23.0, 1.0)]), nominal_hours=(168.0, 0.0, 24.0))
    assert frame.checkpoint.tolist() == [24.0]


def test_reading_from_another_lot_is_rejected():
    dataset = _lot([("A", "iddq", 0.0, 1.0)])
    stray = dataset.readings[0].model_copy(update={"lot_id": "OTHER"})
    with pytest.raises(ValueError, match="lot"):
        checkpoint_frame(dataset.model_copy(update={"readings": [*dataset.readings, stray]}))


def test_reading_from_another_part_number_is_rejected():
    dataset = _lot([("A", "iddq", 0.0, 1.0)])
    stray = dataset.readings[0].model_copy(update={"part_number": "PN-OTHER", "component_id": "B"})
    with pytest.raises(ValueError, match="part number"):
        dynamic_pat_scores(dataset.model_copy(update={"readings": [*dataset.readings, stray]}))


def test_ragged_parameters_give_rows_only_for_measured_pairs():
    rows = [("A", "iddq", 0.0, 1.0), ("A", "leakage", 0.0, 1.0), ("B", "iddq", 0.0, 1.0)]
    frame = static_limit_scores(_lot(rows), {"iddq": Limit(upper=5.0)})
    assert sorted(zip(frame.component_id, frame.parameter)) == [("A", "iddq"), ("A", "leakage"), ("B", "iddq")]


# =====================================================================================
# 4. Units: a limit or a pooled population in one unit must never judge readings in another
# =====================================================================================

def test_mixed_units_for_one_parameter_within_a_lot_are_rejected():
    rows = [("A", "iddq", 0.0, 1.0, "uA"), ("B", "iddq", 0.0, 1000.0, "nA")]
    with pytest.raises(ValueError, match="unit"):
        checkpoint_frame(_lot(rows))


def test_limit_unit_mismatch_is_rejected():
    with pytest.raises(ValueError, match="unit"):
        static_limit_scores(_flat([10.0], unit="nA"), {"iddq": Limit(upper=50.0, unit="uA")})
    with pytest.raises(ValueError, match="unit"):
        fixed_delta_scores(_lot([("A", "iddq", 0.0, 1.0, "nA")]), {"iddq": DeltaLimit(absolute=1.0, unit="uA")})


def test_limit_without_a_unit_is_not_unit_checked():
    frame = static_limit_scores(_flat([10.0], unit="nA"), {"iddq": Limit(upper=50.0)})
    assert frame.evaluable.all()


def test_default_datasheet_limits_carry_the_generator_units():
    generated_units = {r.parameter: r.unit for r in generate_lot("L", "PN", 1, account_id="h").dataset.readings}
    assert {name: limit.unit for name, limit in default_datasheet_limits().items()} == generated_units


def test_default_delta_limits_are_unit_free():
    # Relative allowances don't depend on the unit, so they must not reject a lot recorded in another one.
    assert all(limit.unit is None and limit.absolute is None for limit in default_delta_limits().values())


def test_static_pat_rejects_reference_lots_in_different_units():
    a = _flat(BASE_40, lot_id="R1", unit="uA")
    b = _flat([v * 1000 for v in BASE_40], lot_id="R2", unit="nA")
    with pytest.raises(ValueError, match="unit"):
        fit_static_pat([a, b])


def test_static_pat_rejects_a_target_in_a_different_unit():
    limits = fit_static_pat([_flat(BASE_40, lot_id="R1")])
    with pytest.raises(ValueError, match="unit"):
        static_pat_scores(_flat(BASE_40, lot_id="T", unit="nA"), limits)


# =====================================================================================
# 5. Partial populations: one unmeasurable group must not take the whole lot down
# =====================================================================================

def test_dpat_all_nan_group_is_unevaluable_and_the_rest_is_scored():
    rows = [(f"C{i:03d}", "iddq", 0.0, v) for i, v in enumerate(BASE_40)]
    rows += [(f"C{i:03d}", "leakage", 0.0, NAN) for i in range(40)]
    frame = dynamic_pat_scores(_lot(rows))
    assert frame[frame.parameter == "iddq"].evaluable.all()
    leakage = frame[frame.parameter == "leakage"]
    assert not leakage.evaluable.any() and not leakage.flagged.any()
    assert set(leakage.limit_source) == {"none"}


def test_dpat_unrecognized_parameter_on_a_few_parts_does_not_block_the_lot():
    rows = [(f"C{i:03d}", "iddq", 0.0, v) for i, v in enumerate(BASE_40)]
    rows += [("C000", "vth", 0.0, 0.4), ("C001", "vth", 0.0, 0.41)]
    frame = dynamic_pat_scores(_lot(rows))
    assert frame[frame.parameter == "iddq"].evaluable.all()
    assert not frame[frame.parameter == "vth"].evaluable.any()


def test_dpat_mixed_sources_within_one_row():
    # 40 parts at 0h (lot limits), only 20 of them read at 24h (pooled fallback).
    rows = [(f"C{i:03d}", "iddq", 0.0, v) for i, v in enumerate(BASE_40)]
    rows += [(f"C{i:03d}", "iddq", 24.0, v) for i, v in enumerate(BASE_40[:20])]
    reference = fit_static_pat([_lot([(f"C{i:03d}", "iddq", h, v) for i, v in enumerate(BASE_40)
                                      for h in (0.0, 24.0)], lot_id="R")])
    frame = dynamic_pat_scores(_lot(rows), fallback=reference)
    assert _row(frame, "C000").limit_source == "pooled"
    assert _row(frame, "C030").limit_source == "lot"


def test_dpat_rejects_a_fallback_fitted_on_this_lot():
    lot = _flat(BASE_40)
    with pytest.raises(ValueError, match="reference"):
        dynamic_pat_scores(lot, fallback=fit_static_pat([lot]))


@pytest.mark.parametrize("threshold", [0, -5])
def test_non_positive_minimum_population_is_rejected(threshold):
    config = ScreeningConfig(small_lot_fallback_threshold=threshold)
    with pytest.raises(ValueError, match="small_lot_fallback_threshold"):
        dynamic_pat_scores(_flat(BASE_40), config=config)
    with pytest.raises(ValueError, match="small_lot_fallback_threshold"):
        fit_static_pat([_flat(BASE_40)], config=config)


def test_wrong_config_type_is_rejected():
    with pytest.raises(TypeError):
        dynamic_pat_scores(_flat(BASE_40), config={"small_lot_fallback_threshold": 30})


def test_static_pat_skips_and_records_an_undersized_group():
    rows = [(f"C{i:03d}", "iddq", 0.0, v) for i, v in enumerate(BASE_40)]
    rows += [("C000", "vth", 0.0, 0.4)]
    limits = fit_static_pat([_lot(rows, lot_id="R")])
    assert ("iddq", 0.0) in limits.center
    assert ("vth", 0.0) not in limits.center
    assert limits.insufficient == frozenset({("vth", 0.0)})


def test_static_pat_with_no_adequate_group_raises():
    with pytest.raises(ValueError, match="30"):
        fit_static_pat([_flat([10.0] * 29, lot_id="R")])


def test_static_pat_rejects_a_single_dataset_instead_of_a_collection():
    with pytest.raises(TypeError, match="collection"):
        fit_static_pat(_flat(BASE_40, lot_id="R"))


def test_static_pat_accepts_a_generator_of_lots():
    limits = fit_static_pat(_flat(BASE_40, lot_id=f"R{k}") for k in range(2))
    assert limits.reference_lot_ids == frozenset({"R0", "R1"})


def test_static_pat_scores_on_the_schedule_it_was_fitted_on():
    schedule = (0.0, 48.0, 168.0)
    reference = _lot([(f"C{i:03d}", "iddq", 48.0, v) for i, v in enumerate(BASE_40)], lot_id="R")
    limits = fit_static_pat([reference], nominal_hours=schedule)
    assert limits.nominal_hours == schedule
    target = _lot([("A", "iddq", 50.5, 10.0)], lot_id="T")  # 50.5h only aligns under the fitted schedule
    assert _row(static_pat_scores(target, limits), "A").evaluable
    with pytest.raises(ValueError, match="schedule"):
        static_pat_scores(target, limits, nominal_hours=(0.0, 24.0, 96.0, 168.0))


@pytest.mark.parametrize("change, error", [
    ({"sigma": {("iddq", 24.0): 0.1}}, ValueError),  # keys differ from center's
    ({"sigma": {("iddq", 0.0): -0.1}}, ValueError),
    ({"sigma": {("iddq", 0.0): NAN}}, ValueError),
    ({"center": {("iddq", 0.0): INF}}, ValueError),
    ({"multiplier": 0.0}, ValueError),
    ({"multiplier": NAN}, ValueError),
    ({"part_number": ""}, ValueError),
    ({"units": {}}, ValueError),  # a fitted parameter with no unit
])
def test_pat_limits_validation(change, error):
    args = {"part_number": "PN-1", "reference_lot_ids": frozenset({"R"}), "center": {("iddq", 0.0): 10.0},
                "sigma": {("iddq", 0.0): 0.5}, "units": {"iddq": "uA"}, "nominal_hours": (0.0, 24.0)}
    args.update(change)
    with pytest.raises(error):
        PatLimits(**args)


def test_pat_limits_normalizes_reference_ids_to_frozenset():
    limits = PatLimits(part_number="PN-1", reference_lot_ids={"R"}, center={("iddq", 0.0): 10.0},
                       sigma={("iddq", 0.0): 0.5}, units={"iddq": "uA"}, nominal_hours=(0.0, 24.0))
    assert isinstance(limits.reference_lot_ids, frozenset)


# =====================================================================================
# 6. Information horizon (AGENTS.md rule 6): a baseline compared against an early (0h/24h) decision must
#    not see - or pool statistics from - later checkpoints.
# =====================================================================================

def test_horizon_hides_later_checkpoints_from_every_baseline():
    rows = [(f"C{i:03d}", "iddq", h, v) for i, v in enumerate(BASE_40) for h in (0.0, 24.0, 168.0)]
    rows = [r if not (r[0] == "C039" and r[2] == 168.0) else ("C039", "iddq", 168.0, 1000.0) for r in rows]
    lot = _lot(rows)
    reference = fit_static_pat([_lot(rows, lot_id="R")])
    for name, frame in _all_scorers(lot, reference).items():
        assert _row(frame, "C039").flagged, name
    for name, frame in _all_scorers(lot, reference, horizon_hours=24.0).items():
        row = _row(frame, "C039")
        assert not row.flagged and row.worst_checkpoint != 168.0, name


def test_horizon_applies_to_the_nominal_checkpoint_not_the_jittered_hour():
    # A jittered 24.4h read is the 24h checkpoint, inside a 24h horizon.
    rows = [(f"C{i:03d}", "iddq", h, v) for i, v in enumerate(BASE_40) for h in (0.0, 24.4)]
    frame = checkpoint_frame(_lot(rows), horizon_hours=24.0)
    assert set(frame.checkpoint) == {0.0, 24.0}


def test_horizon_before_any_post_burn_in_read_leaves_delta_unevaluable():
    rows = [("A", "iddq", 0.0, 10.0), ("A", "iddq", 24.0, 99.0)]
    frame = fixed_delta_scores(_lot(rows), {"iddq": DeltaLimit(relative=0.2)}, horizon_hours=0.0)
    assert not _row(frame, "A").evaluable


@pytest.mark.parametrize("horizon, error", [(-1.0, ValueError), (NAN, ValueError), ("24", TypeError)])
def test_horizon_validation(horizon, error):
    with pytest.raises(error):
        checkpoint_frame(_flat([1.0]), horizon_hours=horizon)


# =====================================================================================
# 7. Input-order independence, empty inputs, argument hygiene
# =====================================================================================

def test_reading_order_does_not_change_any_result():
    lot = generate_lot("L1", "PN-1", 21, account_id="h").dataset
    shuffled = list(lot.readings)
    random.Random(0).shuffle(shuffled)
    shuffled_lot = lot.model_copy(update={"readings": shuffled})
    reference = fit_static_pat([generate_lot(f"R{k}", "PN-1", 21, account_id="h").dataset for k in range(2)])
    original, reordered = _all_scorers(lot, reference), _all_scorers(shuffled_lot, reference)
    for name in original:
        pd.testing.assert_frame_equal(original[name], reordered[name])


def test_empty_dataset_through_every_scorer():
    reference = fit_static_pat([_flat(BASE_40, lot_id="R")])
    for name, frame in _all_scorers(_lot([]), reference).items():
        assert frame.empty, name
    assert part_level(static_limit_scores(_lot([]), {})).empty


def test_limits_argument_must_be_a_mapping():
    with pytest.raises(TypeError):
        static_limit_scores(_flat([1.0]), [Limit(upper=5.0)])
    with pytest.raises(TypeError):
        fixed_delta_scores(_flat([1.0]), [("iddq", DeltaLimit(relative=0.1))])


@pytest.mark.parametrize("factory", [Limit, DeltaLimit])
def test_huge_integer_limit_is_a_value_error(factory):
    field = "upper" if factory is Limit else "absolute"
    with pytest.raises(ValueError):
        factory(**{field: 10 ** 400})


def test_numpy_scalars_are_accepted_and_normalized():
    limit = Limit(upper=np.float64(50.0), lower=np.int64(1))
    assert type(limit.upper) is float and type(limit.lower) is float


@pytest.mark.parametrize("bad", ["123", b"123"])
def test_robust_stats_reject_text(bad):
    with pytest.raises(TypeError):
        robust_center_sigma(bad)


def test_default_limit_dicts_are_fresh_copies():
    first = default_datasheet_limits()
    first["iddq"] = Limit(upper=1.0)
    assert default_datasheet_limits()["iddq"].upper != 1.0
    delta = default_delta_limits()
    delta.clear()
    assert default_delta_limits()


def test_part_level_tie_between_parameters_is_deterministic():
    frame = pd.DataFrame({"component_id": ["A", "A"], "parameter": ["leakage", "iddq"], "score": [2.0, 2.0],
                          "flagged": [True, True], "worst_checkpoint": [24.0, 24.0], "evaluable": [True, True]})
    assert part_level(frame).iloc[0].worst_parameter == part_level(frame.iloc[::-1]).iloc[0].worst_parameter


def test_part_level_handles_infinite_scores():
    frame = pd.DataFrame({"component_id": ["A", "A"], "parameter": ["iddq", "leakage"], "score": [INF, 3.0],
                          "flagged": [True, True], "worst_checkpoint": [0.0, 24.0], "evaluable": [True, True]})
    row = part_level(frame).iloc[0]
    assert math.isinf(row.score) and row.worst_parameter == "iddq"


# =====================================================================================
# 8. Held-out sets: argument hygiene and a self-certifying result type
# =====================================================================================

def test_families_given_as_one_string_is_rejected():
    with pytest.raises(TypeError, match="families"):
        generate_held_out_sets(seed=1, families="baseline")


def test_families_given_as_one_family_object_is_rejected():
    with pytest.raises(TypeError, match="families"):
        generate_held_out_sets(seed=1, families=FAMILIES["baseline"])


def test_empty_family_list_is_rejected():
    with pytest.raises(ValueError, match="famil"):
        generate_held_out_sets(seed=1, families=())


@pytest.mark.parametrize("prefix, error", [("", ValueError), ("  ", ValueError), (5, TypeError), (None, TypeError)])
def test_lot_prefix_validation(prefix, error):
    with pytest.raises(error):
        generate_held_out_set("baseline", seed=1, min_per_archetype=1, lot_id_prefix=prefix)


def test_numpy_integer_seed_matches_plain_int():
    a = generate_held_out_set("baseline", seed=np.int64(3), min_per_archetype=2)
    b = generate_held_out_set("baseline", seed=3, min_per_archetype=2)
    assert type(a.seed) is int and a.lot_ids == b.lot_ids
    assert [lot.dataset for lot in a.lots] == [lot.dataset for lot in b.lots]


def test_jittered_held_out_set_meets_the_minimum_and_is_scoreable():
    test_set = generate_held_out_set("baseline", seed=2, min_per_archetype=5, checkpoint_jitter_hours=2.0)
    assert min(test_set.archetype_counts.values()) >= 5
    hours = {r.checkpoint_hour for r in test_set.lots[0].dataset.readings}
    assert any(h not in (0.0, 24.0, 96.0, 168.0) for h in hours)
    frame = dynamic_pat_scores(test_set.lots[0].dataset)
    assert frame.evaluable.all()


def test_invalid_jitter_surfaces_the_generator_error():
    with pytest.raises(ValueError):
        generate_held_out_set("baseline", seed=2, min_per_archetype=1, checkpoint_jitter_hours=-1.0)


def test_every_counted_defect_is_active_before_the_last_read():
    # A defect counted toward the minimum must be one the data can show - never a latent defect whose onset
    # falls after the final checkpoint.
    test_set = generate_held_out_set("baseline", seed=8, min_per_archetype=10, checkpoint_jitter_hours=3.0)
    for lot in test_set.lots:
        last_read = max(lot.ground_truth.trajectories.checkpoint_hours)
        for part in lot.ground_truth.trajectories.parts:
            if part.is_defective:
                assert part.defect_onset_hours < last_read


def _valid_set(**overrides):
    base = generate_held_out_set("higher_defect_prevalence", seed=4, min_per_archetype=2, min_lots=2)
    args = {"family": base.family, "seed": base.seed, "min_per_archetype": base.min_per_archetype,
                "min_lots": base.min_lots, "lots": base.lots}
    args.update(overrides)
    return HeldOutTestSet(**args)


def test_held_out_set_rejects_lots_from_another_family():
    stray = generate_lot("X-1", "PN-HELDOUT", 4, account_id="h", family="baseline")
    with pytest.raises(ValueError, match="family"):
        _valid_set(lots=(*_valid_set().lots, stray))


def test_held_out_set_rejects_a_shortfall():
    with pytest.raises(ValueError, match="minimum"):
        _valid_set(min_per_archetype=10_000)
    with pytest.raises(ValueError, match="min_lots"):
        _valid_set(min_lots=500)


def test_held_out_set_rejects_duplicate_lots():
    lots = _valid_set().lots
    with pytest.raises(ValueError, match="duplicate"):
        _valid_set(lots=(*lots, lots[0]))


def test_held_out_set_rejects_non_lots():
    with pytest.raises(TypeError):
        _valid_set(lots=({"lot_id": "x"},))


def test_archetype_counts_rejects_non_lots():
    with pytest.raises(TypeError):
        archetype_counts([{"lot_id": "x"}])


def test_custom_family_name_flows_into_lot_ids_and_provenance():
    custom = replace(FAMILIES["baseline"], name="stress_2x", description="custom stress family")
    test_set = generate_held_out_set(custom, seed=1, min_per_archetype=1)
    assert test_set.family == "stress_2x"
    assert all(lot_id.startswith("HO-stress_2x-") for lot_id in test_set.lot_ids)
