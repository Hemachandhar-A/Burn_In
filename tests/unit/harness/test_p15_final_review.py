"""P1.5 final review: the remaining gaps found on a second full read of harness/, plus a randomized invariant
sweep across every baseline scorer.

Gaps: a part whose only reads fall after the horizon vanished from the output (and crashed DPAT); a delta
baseline on a schedule with no pre-burn-in checkpoint silently judged nothing; numeric strings slipped into
robust statistics; PatLimits accepted keys off its own schedule; HeldOutTestSet did not check its lots'
seed or part number; small input-type gaps.
"""
import math
import random
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from contracts import LotDataset, Reading
from generator.lot import generate_lot
from harness.held_out import HeldOutTestSet, generate_held_out_set, ground_truth_labels
from harness.industry_baselines import (
    SCORE_COLUMNS,
    DeltaLimit,
    Limit,
    PatLimits,
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

NOMINAL = (0.0, 24.0, 96.0, 168.0)
BASE_40 = [9.0] * 10 + [10.0] * 20 + [11.0] * 10


def _lot(rows, lot_id="L1", part_number="PN-1", unit="uA"):
    return LotDataset(
        lot_id=lot_id, part_number=part_number, status="COMPLETE", account_id="acct",
        readings=[Reading(component_id=c, lot_id=lot_id, part_number=part_number, manufacturer="M",
                          date_code="2601", parameter=p, checkpoint_hour=h, value=v, unit=unit)
                  for c, p, h, v in rows],
    )


def _scorers(dataset, reference, **kwargs):
    return {
        "static": static_limit_scores(dataset, default_datasheet_limits(), **kwargs),
        "delta": fixed_delta_scores(dataset, default_delta_limits(), **kwargs),
        "static_pat": static_pat_scores(dataset, reference, **kwargs),
        "dpat": dynamic_pat_scores(dataset, fallback=reference, **kwargs),
    }


# --- horizon keeps every measured pair ------------------------------------------------

def test_part_read_only_after_the_horizon_is_kept_as_unevaluable():
    rows = [(f"C{i:03d}", "iddq", h, v) for i, v in enumerate(BASE_40) for h in (0.0, 24.0, 168.0)]
    rows.append(("LATE", "iddq", 168.0, 10.0))  # only read at 168h
    lot = _lot(rows)
    reference = fit_static_pat([_lot(rows[:-1], lot_id="R")])
    for name, frame in _scorers(lot, reference, horizon_hours=24.0).items():
        late = frame[frame.component_id == "LATE"]
        assert len(late) == 1, name
        assert not late.evaluable.iloc[0] and not late.flagged.iloc[0], name
        if name == "dpat":
            assert late.limit_source.iloc[0] == "none"


def test_horizon_never_changes_the_row_set():
    lot = generate_lot("L1", "PN-1", 4, account_id="h").dataset
    reference = fit_static_pat([generate_lot(f"R{k}", "PN-1", 4, account_id="h").dataset for k in range(2)])
    full = _scorers(lot, reference)
    for horizon in (0.0, 24.0, 96.0):
        for name, frame in _scorers(lot, reference, horizon_hours=horizon).items():
            pd.testing.assert_frame_equal(frame[["component_id", "parameter"]],
                                          full[name][["component_id", "parameter"]])


# --- delta needs a pre-burn-in checkpoint in the schedule ------------------------------

def test_delta_on_a_schedule_without_a_pre_burn_in_checkpoint_raises():
    with pytest.raises(ValueError, match="pre-burn-in"):
        fixed_delta_scores(_lot([("A", "iddq", 24.0, 1.0)]), {"iddq": DeltaLimit(relative=0.2)},
                           nominal_hours=(24.0, 96.0, 168.0))


# --- robust statistics accept numbers only ---------------------------------------------

@pytest.mark.parametrize("bad", [["1", "2", "3"], [1.0, "2"], [True, False, True], [None, 1.0]])
def test_robust_stats_reject_non_numeric_elements(bad):
    with pytest.raises(TypeError):
        robust_center_sigma(bad)


def test_robust_stats_accept_numpy_and_pandas():
    expected = robust_center_sigma([1.0, 2.0, 3.0, 4.0])
    assert robust_center_sigma(np.array([1, 2, 3, 4])) == expected
    assert robust_center_sigma(pd.Series([1.0, 2.0, 3.0, 4.0])) == expected


# --- PatLimits keys must be coherent with its own schedule ------------------------------

def _pat(**changes):
    args = {"part_number": "PN-1", "reference_lot_ids": frozenset({"R"}), "center": {("iddq", 0.0): 10.0},
            "sigma": {("iddq", 0.0): 0.5}, "units": {"iddq": "uA"}, "nominal_hours": NOMINAL}
    args.update(changes)
    return PatLimits(**args)


def test_pat_limits_reject_a_checkpoint_off_their_schedule():
    with pytest.raises(ValueError, match="schedule"):
        _pat(center={("iddq", 50.0): 10.0}, sigma={("iddq", 50.0): 0.5})


def test_pat_limits_reject_a_non_string_parameter():
    with pytest.raises(TypeError):
        _pat(center={(5, 0.0): 10.0}, sigma={(5, 0.0): 0.5}, units={5: "uA"})


def test_pat_limits_reject_malformed_insufficient_entries():
    with pytest.raises(ValueError):
        _pat(insufficient=frozenset({("vth", 50.0)}))
    with pytest.raises(TypeError):
        _pat(insufficient=frozenset({"vth"}))


def test_pat_limits_reject_a_non_string_reference_id_set():
    with pytest.raises(TypeError):
        _pat(reference_lot_ids="R1")  # a bare string would become {"R", "1"}


def test_fitted_insufficient_groups_are_on_the_schedule():
    rows = [(f"C{i:03d}", "iddq", 0.0, v) for i, v in enumerate(BASE_40)] + [("C000", "vth", 24.0, 0.4)]
    limits = fit_static_pat([_lot(rows, lot_id="R")])
    assert limits.insufficient == frozenset({("vth", 24.0)})


# --- part_level input hygiene ----------------------------------------------------------

def test_part_level_missing_columns_is_a_clear_error():
    with pytest.raises(ValueError, match="evaluable"):
        part_level(pd.DataFrame({"component_id": ["A"], "parameter": ["iddq"], "score": [1.0], "flagged": [False]}))


def test_part_level_rejects_non_frames():
    with pytest.raises(TypeError):
        part_level([{"component_id": "A"}])


# --- held-out set provenance -----------------------------------------------------------

def _set():
    return generate_held_out_set("higher_defect_prevalence", seed=4, min_per_archetype=2, min_lots=2)


def test_held_out_set_rejects_a_seed_its_lots_were_not_generated_with():
    base = _set()
    with pytest.raises(ValueError, match="seed"):
        HeldOutTestSet(family=base.family, seed=base.seed + 1, min_per_archetype=2, min_lots=2, lots=base.lots)


def test_held_out_set_rejects_mixed_part_numbers():
    base = _set()
    other = generate_lot("HO-x-9999", "PN-OTHER", base.seed, account_id="h", family=base.family)
    with pytest.raises(ValueError, match="part number"):
        HeldOutTestSet(family=base.family, seed=base.seed, min_per_archetype=2, min_lots=2,
                       lots=(*base.lots, other))


@pytest.mark.parametrize("family", ["", 5])
def test_held_out_set_rejects_a_bad_family_name(family):
    base = _set()
    with pytest.raises((TypeError, ValueError)):
        HeldOutTestSet(family=family, seed=base.seed, min_per_archetype=2, min_lots=2, lots=base.lots)


def test_held_out_set_supports_dataclass_replace():
    base = _set()
    assert replace(base, min_lots=1).archetype_counts == base.archetype_counts


def test_ground_truth_labels_rejects_non_lots():
    with pytest.raises(TypeError):
        ground_truth_labels({"lot_id": "x"})


# --- randomized invariant sweep --------------------------------------------------------

def _corrupt(dataset: LotDataset, rng: random.Random) -> LotDataset:
    """Drop, blank or blow up a random subset of readings, and jitter the lot's readout times - every kind of
    damage a real lot file can carry that the baselines must survive without guessing."""
    shifts = {h: (rng.uniform(-3, 3) if h else 0.0) for h in NOMINAL}
    readings = []
    for r in dataset.readings:
        roll = rng.random()
        if roll < 0.05:
            continue
        value = math.nan if roll < 0.08 else math.inf if roll < 0.09 else -math.inf if roll < 0.10 else r.value
        readings.append(r.model_copy(update={"value": value, "checkpoint_hour": r.checkpoint_hour + shifts[r.checkpoint_hour]}))
    rng.shuffle(readings)
    return dataset.model_copy(update={"readings": readings})


@pytest.mark.parametrize("seed", range(12))
def test_invariants_hold_on_randomly_corrupted_lots(seed):
    rng = random.Random(seed)
    family = ["baseline", "different_noise_regime", "higher_defect_prevalence", "altered_correlation"][seed % 4]
    n_parts = rng.choice([12, 31, 77])
    lot = _corrupt(generate_lot("T", "PN-1", seed, account_id="h", family=family, n_parts=n_parts).dataset, rng)
    reference = fit_static_pat([generate_lot(f"R{k}", "PN-1", seed, account_id="h", family=family).dataset
                                for k in range(2)])
    measured = sorted({(r.component_id, r.parameter) for r in lot.readings})
    horizon = rng.choice([None, 24.0, 96.0])
    for name, frame in _scorers(lot, reference, horizon_hours=horizon).items():
        assert list(frame.columns[:6]) == SCORE_COLUMNS, name
        assert sorted(zip(frame.component_id, frame.parameter)) == measured, name  # nothing dropped
        assert (frame.evaluable == frame.score.notna()).all(), name
        assert not frame[~frame.evaluable].flagged.any(), name
        assert (frame[frame.evaluable].flagged == (frame[frame.evaluable].score > 1.0)).all(), name
        assert (frame[frame.evaluable].score >= 0).all(), name
        worst = frame.worst_checkpoint.dropna()
        assert worst.isin(NOMINAL).all(), name
        if horizon is not None:
            assert (worst <= horizon).all(), name
        if name == "delta":
            assert (worst != 0.0).all()
        reordered = _scorers(lot.model_copy(update={"readings": list(reversed(lot.readings))}), reference,
                             horizon_hours=horizon)[name]
        pd.testing.assert_frame_equal(frame, reordered)
        parts = part_level(frame)
        assert sorted(parts.component_id) == sorted({c for c, _ in measured})
        assert (parts.flagged == parts.component_id.map(frame.groupby("component_id").flagged.any())).all()


def test_limit_objects_compare_by_value():
    assert Limit(upper=50) == Limit(upper=50.0)
    assert DeltaLimit(relative=np.float64(0.2)) == DeltaLimit(relative=0.2)
