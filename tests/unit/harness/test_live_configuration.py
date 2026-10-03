"""run_module_a's optional pooled_reference / max_history switches (session M1): defaults reproduce the
published benchmark behaviour, the live configuration changes only the Isolation Forest."""
import pytest

from features.compute import compute
from harness import scoring
from harness.held_out import generate_held_out_set
from module_a import detect as module_a_detect


@pytest.fixture(scope="module")
def small_set():
    return generate_held_out_set("baseline", seed=2026, min_per_archetype=1, min_lots=4, n_parts=40)


def _legacy_run(test_set):
    """The pre-M1 implementation, verbatim: each lot's history is every earlier lot, flattened."""
    results, history = [], []
    for lot in test_set.lots:
        frames = compute(lot.dataset)
        results += module_a_detect.detect(frames, prior_frames=list(history))
        history += frames
    return results


def _key(r):
    return (r.lot_id, r.component_id, r.parameter)


def test_default_output_unchanged(small_set):
    new = scoring.run_module_a(small_set)
    old = _legacy_run(small_set)
    assert [r.model_dump() for r in new] == [r.model_dump() for r in old]


def test_live_configuration_changes_only_the_isolation_forest(small_set):
    pooled = {_key(r): r for r in scoring.run_module_a(small_set)}
    live = {_key(r): r for r in scoring.run_module_a(small_set, pooled_reference=False)}
    assert pooled.keys() == live.keys()
    assert all(r.isolation_forest_score is None for r in live.values())
    assert any(r.isolation_forest_score is not None for r in pooled.values())  # later lots have a forest
    for k, p in pooled.items():
        lv = live[k]
        assert (lv.robust_z, lv.mcd_distance, lv.ecod_score) == (p.robust_z, p.mcd_distance, p.ecod_score)


def test_first_lot_is_identical_in_both_configurations(small_set):
    first = small_set.lots[0].dataset.lot_id
    pooled = [r for r in scoring.run_module_a(small_set) if r.lot_id == first]
    live = [r for r in scoring.run_module_a(small_set, pooled_reference=False) if r.lot_id == first]
    assert [r.model_dump() for r in pooled] == [r.model_dump() for r in live]  # cold start: no history either way


def test_max_history_one_matches_full_history_on_the_second_lot_only(small_set):
    full = scoring.run_module_a(small_set)
    one = scoring.run_module_a(small_set, max_history=1)
    lots = [lot.dataset.lot_id for lot in small_set.lots]
    for idx, lot_id in enumerate(lots):
        a = [r.model_dump() for r in full if r.lot_id == lot_id]
        b = [r.model_dump() for r in one if r.lot_id == lot_id]
        if idx <= 1:
            assert a == b  # history is at most one lot either way
    last = lots[-1]
    assert [r.isolation_forest_score for r in full if r.lot_id == last] != \
           [r.isolation_forest_score for r in one if r.lot_id == last]


def test_max_history_larger_than_available_equals_default(small_set):
    big = scoring.run_module_a(small_set, max_history=99)
    assert [r.model_dump() for r in big] == [r.model_dump() for r in scoring.run_module_a(small_set)]


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "3"])
def test_max_history_rejects_invalid_values(small_set, bad):
    with pytest.raises(ValueError):
        scoring.run_module_a(small_set, max_history=bad)


def test_module_a_table_forwards_the_switches(small_set):
    pooled = scoring.module_a_table(small_set)
    live = scoring.module_a_table(small_set, pooled_reference=False)
    assert (pooled["isolation_forest"] != live["isolation_forest"]).any()
    for col in ("robust_z", "mcd", "ecod"):
        assert pooled[col].tolist() == live[col].tolist()
