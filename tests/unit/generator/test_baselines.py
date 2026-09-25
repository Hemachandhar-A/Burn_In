"""E1 steps 1-3: lot/die baseline sampling + defect assignment.

7.3 checklist (Generator row): determinism (same seed -> identical output).
Trajectory generation (power-law drift, Arrhenius defects) lands in session P1.2 -
this session only covers baseline sampling and defect status assignment.
"""
import pytest

from contracts import ScreeningConfig
from generator.baselines import generate_lot_baselines
from generator.parameters import PARAMETERS


def test_determinism_same_seed_identical_output():
    lot_a = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=77, seed=42)
    lot_b = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=77, seed=42)

    assert lot_a.lot_center == lot_b.lot_center
    assert lot_a.lot_die_sigma == lot_b.lot_die_sigma
    assert lot_a.defect_prevalence == lot_b.defect_prevalence
    assert [p.is_defective for p in lot_a.parts] == [p.is_defective for p in lot_b.parts]
    assert [p.baseline for p in lot_a.parts] == [p.baseline for p in lot_b.parts]


def test_different_seed_produces_different_output():
    lot_a = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=30, seed=1)
    lot_b = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=30, seed=2)

    assert lot_a.lot_center != lot_b.lot_center


def test_defect_prevalence_within_config_range():
    config = ScreeningConfig()
    lo, hi = config.defect_prevalence_range
    for seed in range(10):
        lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=77, seed=seed, config=config)
        assert lo <= lot.defect_prevalence <= hi


def test_defect_status_is_healthy_majority():
    # A wide lot with the config's default (low) prevalence range should be overwhelmingly healthy.
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=500, seed=7)
    defective_count = sum(p.is_defective for p in lot.parts)
    assert 0 < defective_count < len(lot.parts) * 0.5


def test_every_part_has_a_baseline_for_every_parameter():
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=77, seed=3)
    for part in lot.parts:
        assert set(part.baseline.keys()) == set(PARAMETERS.keys())
        for value in part.baseline.values():
            assert value > 0  # lognormal is strictly positive - physically required for these parameters


def test_component_ids_are_unique_within_a_lot():
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=77, seed=9)
    component_ids = [p.component_id for p in lot.parts]
    assert len(component_ids) == len(set(component_ids))


def test_lot_die_sigma_varies_across_lots():
    # E1 step 1: both center AND spread are sampled per lot, not just the center.
    lot_a = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=30, seed=1)
    lot_b = generate_lot_baselines(lot_id="L2", part_number="PN-1", n_parts=30, seed=2)
    assert lot_a.lot_die_sigma != lot_b.lot_die_sigma


def test_die_baselines_are_centered_near_lot_center_not_identical():
    # Die-to-die variation (context.md 3.3): parts shouldn't all collapse to one value.
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=77, seed=11)
    for name in PARAMETERS:
        values = [p.baseline[name] for p in lot.parts]
        assert len(set(values)) > 1


def test_ground_truth_defect_status_is_not_a_reading_or_lot_dataset_field():
    # Ground truth (is_defective) must stay out of the production-facing schema (E1's "What it
    # is"); Reading/LotDataset are defined in contracts.py without any defect field.
    from contracts import LotDataset, Reading

    assert "is_defective" not in Reading.model_fields
    assert "is_defective" not in LotDataset.model_fields


def test_rejects_out_of_range_n_parts():
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=0, seed=1)
