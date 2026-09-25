"""E1 step 8 end-to-end: generate_lot() produces a production-facing LotDataset whose readings carry
elapsed time as an explicit numeric field, plus a separate ground-truth sidecar.

7.3 checklist (Generator row): determinism over the full pipeline, and "ground-truth sidecar never
leaks into the production schema" - both closeable here now that real Readings exist.
"""
import json
import math
from collections import defaultdict

import pytest

from contracts import LotDataset, Reading, ScreeningConfig
from generator.lot import GeneratedLot, LotGroundTruth, generate_lot
from generator.parameters import PARAMETERS


def _lot(**kwargs):
    kwargs.setdefault("lot_id", "L1")
    kwargs.setdefault("part_number", "PN-1")
    kwargs.setdefault("seed", 42)
    kwargs.setdefault("account_id", "acct-test")
    return generate_lot(**kwargs)


def _by_part(dataset):
    out = defaultdict(lambda: defaultdict(list))
    for r in dataset.readings:
        out[r.component_id][r.parameter].append((r.checkpoint_hour, r.value))
    return out


# --- shape -----------------------------------------------------------------------

def test_returns_dataset_and_separate_ground_truth():
    lot = _lot()
    assert isinstance(lot, GeneratedLot)
    assert isinstance(lot.dataset, LotDataset)
    assert isinstance(lot.ground_truth, LotGroundTruth)


def test_dataset_is_a_valid_contract_object():
    lot = _lot()
    # Round-trips through the contract's own validation, as ingestion/the API would see it.
    assert LotDataset.model_validate(lot.dataset.model_dump()) == lot.dataset
    assert all(isinstance(r, Reading) for r in lot.dataset.readings)


def test_default_lot_size_and_full_schedule():
    lot = _lot()
    by_part = _by_part(lot.dataset)
    assert len(by_part) == ScreeningConfig().lot_size_default
    for series_by_param in by_part.values():
        assert set(series_by_param) == set(PARAMETERS)
        assert all([h for h, _ in s] == [0.0, 24.0, 96.0, 168.0] for s in series_by_param.values())


def test_reading_metadata_populated():
    lot = _lot(lot_id="LOT-9", part_number="PN-X", manufacturer="ACME-SIM", date_code="2612",
               account_id="a.sharma")
    assert lot.dataset.lot_id == "LOT-9" and lot.dataset.part_number == "PN-X"
    assert lot.dataset.account_id == "a.sharma"
    for r in lot.dataset.readings:
        assert (r.lot_id, r.part_number, r.manufacturer, r.date_code) == ("LOT-9", "PN-X", "ACME-SIM", "2612")
        assert r.unit == PARAMETERS[r.parameter].unit
        assert math.isfinite(r.value) and r.value > 0


def test_n_parts_override():
    assert len(_by_part(_lot(n_parts=12).dataset)) == 12


def test_status_complete_only_with_168h_checkpoint():
    assert _lot().dataset.status == "COMPLETE"
    assert _lot(checkpoint_hours=(0.0, 24.0)).dataset.status == "IN_PROGRESS"
    assert _lot(checkpoint_hours=(0.0, 24.0, 96.0)).dataset.status == "IN_PROGRESS"


# --- determinism (7.3) --------------------------------------------------------------

def test_determinism_full_pipeline():
    assert _lot(seed=7) == _lot(seed=7)
    assert _lot(seed=7).dataset.model_dump_json() == _lot(seed=7).dataset.model_dump_json()


def test_different_seed_different_lot():
    assert _lot(seed=7).dataset != _lot(seed=8).dataset


# --- step 8: explicit elapsed time, irregular schedules ------------------------------

def test_checkpoint_hour_is_explicit_float_per_reading():
    for r in _lot().dataset.readings:
        assert isinstance(r.checkpoint_hour, float)


def test_irregular_schedule_passes_through_exactly():
    hours = (0.0, 22.5, 101.0, 170.25)
    lot = _lot(checkpoint_hours=hours)
    assert sorted({r.checkpoint_hour for r in lot.dataset.readings}) == list(hours)
    assert lot.ground_truth.trajectories.checkpoint_hours == hours


def test_checkpoint_jitter_makes_actual_hours_irregular():
    lot = _lot(checkpoint_jitter_hours=2.0)
    actual = sorted({r.checkpoint_hour for r in lot.dataset.readings})
    nominal = [0.0, 24.0, 96.0, 168.0]
    assert len(actual) == 4
    assert actual[0] == 0.0  # the pre-burn-in read defines t = 0
    assert all(abs(a - n) <= 2.0 for a, n in zip(actual[1:], nominal[1:]))
    assert actual[1:] != nominal[1:]
    assert lot.ground_truth.nominal_checkpoint_hours == tuple(nominal)
    assert lot.ground_truth.trajectories.checkpoint_hours == tuple(actual)


def test_jitter_is_lot_wide_so_every_part_shares_the_readout_times():
    by_part = _by_part(_lot(checkpoint_jitter_hours=2.0).dataset)
    schedules = {tuple(h for h, _ in s) for series in by_part.values() for s in series.values()}
    assert len(schedules) == 1


def test_jitter_is_deterministic_and_varies_by_seed():
    a = _lot(seed=1, checkpoint_jitter_hours=2.0).ground_truth.trajectories.checkpoint_hours
    assert a == _lot(seed=1, checkpoint_jitter_hours=2.0).ground_truth.trajectories.checkpoint_hours
    assert a != _lot(seed=2, checkpoint_jitter_hours=2.0).ground_truth.trajectories.checkpoint_hours


def test_status_uses_nominal_schedule_even_when_jitter_lands_below_168():
    for seed in range(10):
        assert _lot(seed=seed, checkpoint_jitter_hours=3.0).dataset.status == "COMPLETE"


@pytest.mark.parametrize("jitter", [-1.0, math.nan, math.inf, 12.0, True])
def test_invalid_jitter_rejected(jitter):
    # 12h would let the 24h read reach 12h - within the nominal gap to 0h, so ordering could break.
    with pytest.raises((ValueError, TypeError)):
        _lot(checkpoint_jitter_hours=jitter)


def test_first_checkpoint_not_at_zero_still_jittered_and_nonnegative():
    lot = _lot(checkpoint_hours=(24.0, 96.0), checkpoint_jitter_hours=5.0)
    hours = lot.ground_truth.trajectories.checkpoint_hours
    assert all(h >= 0 for h in hours) and hours[0] < hours[1]


def test_early_readings_independent_of_later_checkpoints():
    # Rule 6: a lot read to 24h so far must carry exactly the 0h/24h values it will have once complete.
    early = _by_part(_lot(checkpoint_hours=(0.0, 24.0), checkpoint_jitter_hours=1.0).dataset)
    full = _by_part(_lot(checkpoint_hours=(0.0, 24.0, 96.0, 168.0), checkpoint_jitter_hours=1.0).dataset)
    for cid, series_by_param in early.items():
        for name, series in series_by_param.items():
            assert series == full[cid][name][:2]


# --- ground-truth sidecar never leaks (7.3) -------------------------------------------

_GROUND_TRUTH_TERMS = ("defect", "defective", "severity", "activation", "onset", "archetype",
                       "drift_exponent", "drift_amplitude", "junction", "family", "offset", "truth")


def test_production_schema_fields_are_exactly_the_contract():
    lot = _lot()
    assert set(lot.dataset.model_dump()) == set(LotDataset.model_fields)
    for r in lot.dataset.readings[:50]:
        assert set(r.model_dump()) == set(Reading.model_fields)


def test_no_ground_truth_term_anywhere_in_serialized_dataset():
    payload = _lot(family="higher_defect_prevalence").dataset.model_dump_json().lower()
    for term in _GROUND_TRUTH_TERMS:
        assert term not in payload, term


def test_contract_models_carry_no_ground_truth_fields():
    for model in (Reading, LotDataset):
        for field in model.model_fields:
            assert not any(term in field.lower() for term in _GROUND_TRUTH_TERMS), (model, field)


def test_component_ids_do_not_encode_defect_status():
    lot = _lot(family="higher_defect_prevalence", n_parts=200)
    truth = {p.component_id: p.is_defective for p in lot.ground_truth.trajectories.parts}
    assert any(truth.values()) and not all(truth.values())
    ids = sorted(truth)
    # Same naming scheme for both populations - nothing about an ID distinguishes a defective part.
    assert {len(c) for c in ids} == {len(ids[0])}
    assert [r.component_id for r in lot.dataset.readings if r.parameter == "iddq" and r.checkpoint_hour == 0.0] == ids


def test_readings_are_measured_not_the_hidden_true_values():
    lot = _lot()
    true = {p.component_id: p.values for p in lot.ground_truth.trajectories.parts}
    by_part = _by_part(lot.dataset)
    diffs = [
        got != t
        for cid, series_by_param in by_part.items()
        for name, series in series_by_param.items()
        for (_, got), t in zip(series, true[cid][name])
    ]
    assert sum(diffs) > 0.9 * len(diffs)


def test_ground_truth_has_labels_for_every_production_part():
    lot = _lot(family="higher_defect_prevalence", n_parts=150)
    gt_ids = {p.component_id for p in lot.ground_truth.trajectories.parts}
    assert gt_ids == {r.component_id for r in lot.dataset.readings}
    for p in lot.ground_truth.trajectories.parts:
        assert (p.defect_type is None) == (not p.is_defective)


def test_ground_truth_records_provenance():
    gt = _lot(seed=5, family="different_noise_regime").ground_truth
    assert gt.family == "different_noise_regime"
    assert gt.seed == 5
    assert len(gt.measurement.tester_offset) == len(gt.trajectories.checkpoint_hours)


def test_dataset_json_is_standalone_serializable_without_sidecar():
    data = json.loads(_lot().dataset.model_dump_json())
    assert LotDataset.model_validate(data).readings


# --- validation ------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    {"account_id": ""},
    {"account_id": "   "},
    {"account_id": None},
    {"manufacturer": ""},
    {"date_code": ""},
    {"family": "no_such_family"},
    {"family": 3},
    {"n_parts": 0},
    {"seed": -1},
    {"checkpoint_hours": ()},
    {"checkpoint_hours": (24.0, 0.0)},
])
def test_invalid_inputs_rejected(kwargs):
    with pytest.raises((ValueError, TypeError)):
        _lot(**kwargs)


def test_account_id_is_required():
    with pytest.raises(TypeError):
        generate_lot(lot_id="L1", part_number="PN-1", seed=1)
