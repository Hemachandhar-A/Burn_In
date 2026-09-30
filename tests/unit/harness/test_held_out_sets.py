"""E5 step 2: held-out test sets across all five generator families, each guaranteeing a minimum count of
every defect archetype - decoupled from lot size and from however many lots the live demo contains
(context.md 7.12: threshold tuning and per-archetype claims are only as stable as the smallest archetype).
"""
from dataclasses import replace

import pytest

from contracts import LotDataset, ScreeningConfig
from generator.families import FAMILIES, HELD_OUT_FAMILY_NAMES
from generator.lot import GeneratedLot
from generator.trajectories import DEFECT_ARCHETYPES
from harness.held_out import (
    DEFAULT_MIN_PER_ARCHETYPE,
    HeldOutTestSet,
    archetype_counts,
    generate_held_out_set,
    generate_held_out_sets,
    ground_truth_labels,
)

ARCHETYPES = tuple(DEFECT_ARCHETYPES)


@pytest.fixture(scope="module")
def default_sets():
    return generate_held_out_sets(seed=2026)


# --- the guarantee -------------------------------------------------------------------

def test_default_minimum_is_stated_and_meaningful():
    assert isinstance(DEFAULT_MIN_PER_ARCHETYPE, int)
    assert DEFAULT_MIN_PER_ARCHETYPE >= 20  # enough that one miss moves recall by <= 5 points


def test_every_family_has_its_own_held_out_set(default_sets):
    assert tuple(default_sets) == HELD_OUT_FAMILY_NAMES
    for name, test_set in default_sets.items():
        assert isinstance(test_set, HeldOutTestSet)
        assert test_set.family == name
        assert all(lot.ground_truth.family == name for lot in test_set.lots)


def test_every_family_meets_the_minimum_for_every_archetype(default_sets):
    for name, test_set in default_sets.items():
        counts = test_set.archetype_counts
        assert set(counts) == set(ARCHETYPES), name
        for archetype in ARCHETYPES:
            assert counts[archetype] >= DEFAULT_MIN_PER_ARCHETYPE, (name, archetype, counts)


@pytest.mark.parametrize("n_parts", [30, 77, 200])
def test_minimum_holds_regardless_of_lot_size(n_parts):
    # Volume per lot changes how many lots it takes, never whether the minimum is met.
    test_set = generate_held_out_set("baseline", seed=1, min_per_archetype=15, n_parts=n_parts)
    assert min(test_set.archetype_counts.values()) >= 15
    assert all(len(lot.ground_truth.baselines.parts) == n_parts for lot in test_set.lots)


def test_smaller_lots_need_more_of_them():
    small = generate_held_out_set("baseline", seed=1, min_per_archetype=15, n_parts=30)
    large = generate_held_out_set("baseline", seed=1, min_per_archetype=15, n_parts=200)
    assert len(small.lots) > len(large.lots)


@pytest.mark.parametrize("minimum", [1, 10, 40])
def test_the_minimum_is_what_drives_the_count(minimum):
    test_set = generate_held_out_set("higher_defect_prevalence", seed=4, min_per_archetype=minimum)
    counts = test_set.archetype_counts
    assert min(counts.values()) >= minimum
    # Stops as soon as the minimum (and min_lots) is met: one lot fewer would leave an archetype short.
    if len(test_set.lots) > test_set.min_lots:
        shorter = archetype_counts(test_set.lots[:-1])
        assert min(shorter.values()) < minimum


def test_min_lots_is_respected_even_when_the_archetype_minimum_is_met_early():
    test_set = generate_held_out_set("higher_defect_prevalence", seed=4, min_per_archetype=1, min_lots=8)
    assert len(test_set.lots) == 8


# --- counts are ground truth, and stay out of the datasets --------------------------

def test_archetype_counts_match_the_ground_truth_labels(default_sets):
    test_set = default_sets["baseline"]
    labels = test_set.labels()
    defective = labels[labels.is_defective]
    assert dict(defective.defect_type.value_counts()) == {k: v for k, v in test_set.archetype_counts.items() if v}
    assert labels.defect_type[~labels.is_defective].isna().all()
    assert test_set.n_defective == len(defective)
    assert test_set.n_parts == len(labels)


def test_labels_frame_shape():
    lot = generate_held_out_set("baseline", seed=3, min_per_archetype=1).lots[0]
    labels = ground_truth_labels(lot)
    assert list(labels.columns) == ["lot_id", "component_id", "family", "is_defective", "defect_type"]
    assert len(labels) == len(lot.ground_truth.baselines.parts)
    assert labels.component_id.is_unique


def test_datasets_carry_no_ground_truth():
    lot = generate_held_out_set("baseline", seed=3, min_per_archetype=1).lots[0]
    assert isinstance(lot, GeneratedLot)
    assert isinstance(lot.dataset, LotDataset)
    dumped = lot.dataset.model_dump_json()
    for secret in ("is_defective", "defect_type", *ARCHETYPES):
        assert secret not in dumped


def test_archetype_counts_zero_fills_missing_archetypes():
    counts = archetype_counts([])
    assert counts == {name: 0 for name in ARCHETYPES}


# --- lot identity, determinism, split discipline -------------------------------------

def test_held_out_sets_are_deterministic():
    a = generate_held_out_set("different_noise_regime", seed=5, min_per_archetype=5)
    b = generate_held_out_set("different_noise_regime", seed=5, min_per_archetype=5)
    assert a.lot_ids == b.lot_ids
    assert [lot.dataset for lot in a.lots] == [lot.dataset for lot in b.lots]


def test_seed_changes_the_data():
    a = generate_held_out_set("baseline", seed=5, min_per_archetype=5)
    b = generate_held_out_set("baseline", seed=6, min_per_archetype=5)
    assert a.lots[0].dataset != b.lots[0].dataset


def test_lot_ids_are_unique_within_and_across_families(default_sets):
    all_ids = [lot_id for test_set in default_sets.values() for lot_id in test_set.lot_ids]
    assert len(all_ids) == len(set(all_ids))
    for test_set in default_sets.values():
        assert all(lot_id.startswith("HO-") for lot_id in test_set.lot_ids)


def test_families_do_not_share_underlying_draws(default_sets):
    # Distinct lot ids per family -> independent draws (the generator mixes lot_id into the seed), so a
    # model tuned on one family's held-out lots never meets a common-random-numbers twin in another's.
    baseline = default_sets["baseline"].lots[0].ground_truth.baselines.parts[0].baseline
    other = default_sets["wider_drift_exponent"].lots[0].ground_truth.baselines.parts[0].baseline
    assert baseline != other


def test_custom_prefix_and_part_number():
    test_set = generate_held_out_set("baseline", seed=1, min_per_archetype=2, lot_id_prefix="EVAL",
                                     part_number="PN-X")
    assert all(lot_id.startswith("EVAL-baseline-") for lot_id in test_set.lot_ids)
    assert {lot.dataset.part_number for lot in test_set.lots} == {"PN-X"}


def test_all_lots_are_complete_campaigns():
    test_set = generate_held_out_set("baseline", seed=1, min_per_archetype=2)
    assert {lot.dataset.status for lot in test_set.lots} == {"COMPLETE"}


def test_family_subset():
    sets = generate_held_out_sets(seed=1, families=("baseline", "altered_correlation"), min_per_archetype=2)
    assert tuple(sets) == ("baseline", "altered_correlation")


# --- failure modes -------------------------------------------------------------------

def test_family_that_cannot_produce_defects_fails_fast():
    no_defects = replace(FAMILIES["baseline"], name="no_defects",
                         config=ScreeningConfig(defect_prevalence_range=(0.0, 0.0)))
    with pytest.raises(ValueError, match="prevalence"):
        generate_held_out_set(no_defects, seed=1)


def test_unreachable_minimum_within_max_lots_raises():
    with pytest.raises(RuntimeError, match="max_lots"):
        generate_held_out_set("baseline", seed=1, min_per_archetype=50, min_lots=1, max_lots=3)


@pytest.mark.parametrize("kwargs, error", [
    ({"min_per_archetype": 0}, ValueError),
    ({"min_per_archetype": 2.5}, TypeError),
    ({"min_per_archetype": True}, TypeError),
    ({"min_lots": 0}, ValueError),
    ({"max_lots": 2, "min_lots": 3}, ValueError),
    ({"seed": -1}, ValueError),
    ({"seed": "1"}, TypeError),
])
def test_argument_validation(kwargs, error):
    args = {"seed": 1, **kwargs}
    with pytest.raises(error):
        generate_held_out_set("baseline", **args)


def test_unknown_family_rejected():
    with pytest.raises(ValueError):
        generate_held_out_set("not_a_family", seed=1)


def test_duplicate_family_request_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        generate_held_out_sets(seed=1, families=("baseline", "baseline"), min_per_archetype=1)


def test_held_out_set_is_immutable(default_sets):
    test_set = default_sets["baseline"]
    with pytest.raises(TypeError):
        test_set.archetype_counts["progressive"] = 0
    with pytest.raises(AttributeError):
        test_set.lots = ()


def test_every_baseline_scores_every_family_held_out_lot():
    # The two E5 step 1-2 pieces meet here: each baseline must judge every part of every family's lots,
    # including the coarse-quantization noise family, without an unevaluable part or a crash.
    from harness.industry_baselines import (
        default_datasheet_limits,
        default_delta_limits,
        dynamic_pat_scores,
        fit_static_pat,
        fixed_delta_scores,
        static_limit_scores,
        static_pat_scores,
    )
    for name, test_set in generate_held_out_sets(seed=7, min_per_archetype=1, min_lots=4).items():
        reference = fit_static_pat([lot.dataset for lot in test_set.lots[:3]])
        target = test_set.lots[3].dataset
        for frame in (static_limit_scores(target, default_datasheet_limits()),
                      fixed_delta_scores(target, default_delta_limits()),
                      static_pat_scores(target, reference),
                      dynamic_pat_scores(target)):
            assert frame.evaluable.all(), name
