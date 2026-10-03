"""S6X: the variant engine (harness/variants.py) - fast path vs detect(), thresholds, bootstrap, data sides."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from features.compute import compute
from harness import scoring as hs
from harness import variants as hv
from module_a.detect import detect
from module_a.scoring import ScoringReference, compute_lot_raw

SIDE = hv.Side("unit", 6999, "SC-UNIT", 6)


@pytest.fixture(scope="module")
def prepared():
    return hv.prepare(SIDE, "baseline", hv.setting_family("baseline"))


def _detect_scores(lots_raws, variant, anchor, thresholds=(3.0, 4.0)):
    """The same part scores through detect(scoring=...) with a hand-built reference."""
    import dataclasses
    out = []
    for i, lot in enumerate(lots_raws.lots):
        frames = compute(lot.dataset)
        ref = None
        if variant.calibration == "reference" and i > 0:
            ref = ScoringReference.from_raw([compute_lot_raw(compute(l.dataset)) for l in lots_raws.lots[max(0, i - variant.history_lots):i]])
        cfg = dataclasses.replace(variant.config(reference=ref, anchor=anchor), review_threshold=thresholds[0],
                                  reject_threshold=thresholds[1])
        out.append(hs.variant_part_scores(detect(frames, scoring=cfg)))
    return pd.concat(out, ignore_index=True)


def test_v0_fast_path_equals_detects_live_rank_scores_exactly(prepared):
    lots = hv.generate_lots(SIDE, "baseline", hv.setting_family("baseline"))
    for lot, raw in zip(lots[:2], prepared.raws[:2]):
        frames = compute(lot.dataset)
        np.testing.assert_array_equal(hv.rank_frame_scores(raw), [r.combined_severity for r in detect(frames)])


@pytest.mark.parametrize("variant", [hv.Variant("V1", "absolute"), hv.Variant("V1-C2", "absolute", "hybrid"),
                                     hv.Variant("V2k5-C1", "reference", "mean", history_lots=5)])
def test_fast_path_equals_detect_scoring_path(prepared, variant):
    lots = SimpleNamespace(lots=hv.generate_lots(SIDE, "baseline", hv.setting_family("baseline")))
    anchor = ScoringReference.from_raw(prepared.raws[:5])
    fast = hv.score_sequence(prepared.raws, variant, anchor)
    slow = _detect_scores(lots, variant, anchor)
    merged = fast.merge(slow, on=["lot_id", "component_id"], suffixes=("_fast", "_slow"), validate="one_to_one")
    assert len(merged) == len(fast) == len(slow)
    np.testing.assert_allclose(merged["score_fast"], merged["score_slow"], rtol=1e-12, atol=1e-12)


def test_harness_run_module_a_passes_scoring_through(prepared):
    lots = SimpleNamespace(lots=hv.generate_lots(SIDE, "baseline", hv.setting_family("baseline"))[:3])
    anchor = ScoringReference.from_raw(prepared.raws[:5])
    v = hv.Variant("V1", "absolute")
    results = hs.run_module_a(lots, scoring=v.config(reference=None, anchor=None, review=3.0, reject=4.0),
                              ecod_anchor=anchor)
    got = hs.variant_part_scores(results)
    want = hv.score_sequence(prepared.raws[:3], v, anchor)
    merged = got.merge(want, on=["lot_id", "component_id"], suffixes=("_a", "_b"))
    np.testing.assert_allclose(merged["score_a"], merged["score_b"], rtol=1e-12)


def test_run_module_a_default_is_unchanged_by_the_new_options(prepared):
    lots = SimpleNamespace(lots=hv.generate_lots(SIDE, "baseline", hv.setting_family("baseline"))[:2])
    default = [r.model_dump() for r in hs.run_module_a(lots)]
    explicit = [r.model_dump() for r in hs.run_module_a(lots, scoring=None, reference_lots=None, ecod_anchor=None)]
    assert default == explicit


def test_tuning_ignores_parts_the_override_already_flags():
    rng = np.random.default_rng(1)
    s = rng.normal(size=400)
    y = rng.random(400) < 0.05
    s[y] += 2.5
    plain = pd.DataFrame({"score": s, "is_defective": y, "override": False})
    forced = plain.copy()
    forced.loc[:20, "override"] = True
    t_plain, t_forced = hv.tune_thresholds(plain), hv.tune_thresholds(forced)
    free = forced[~forced["override"]]
    assert t_forced["review"] == hs.tune_threshold(free["score"], free["is_defective"], hs.REVIEW_FN_FP_COST_RATIO)
    assert t_plain["review"] == hs.tune_threshold(plain["score"], plain["is_defective"], hs.REVIEW_FN_FP_COST_RATIO)


def test_apply_thresholds_override_flags_review_only():
    table = pd.DataFrame({"score": [0.1, 0.1, 5.0], "override": [False, True, False]})
    out = hv.apply_thresholds(table, {"review": 3.0, "reject": 6.0})
    assert out["review_flagged"].tolist() == [False, True, True]
    assert out["reject_flagged"].tolist() == [False, False, False]


def test_bootstrap_metrics_match_the_repos_cost_function():
    rng = np.random.default_rng(2)
    table = pd.DataFrame({"lot_id": np.repeat([f"L{i}" for i in range(20)], 30),
                          "is_defective": rng.random(600) < 0.08, "flag": rng.random(600) < 0.2})
    m = hv.lot_bootstrap_metrics(table, "flag", reps=200)
    assert m["cost_per_part"] == pytest.approx(hs.expected_cost(table["is_defective"], table["flag"], 10.0))
    assert m["cost_per_part_ci_lo"] <= m["cost_per_part"] <= m["cost_per_part_ci_hi"]
    assert m["false_alarms"] + int((table["is_defective"] & table["flag"]).sum()) == m["n_flagged"]


def test_sides_are_disjoint_and_avoid_forbidden_seeds():
    hv.assert_sides_disjoint()
    seeds = {s.seed for s in hv.SIDES.values()}
    assert not seeds & hv.FORBIDDEN_SEEDS
    assert len({s.prefix for s in hv.SIDES.values()}) == len(hv.SIDES)


def test_clean_family_has_no_defective_parts():
    lots = hv.generate_lots(hv.Side("c", 6999, "SC-UNIT", 2), "baseline", hv.clean_family("baseline"))
    assert sum(p.is_defective for lot in lots for p in lot.ground_truth.trajectories.parts) == 0


def test_setting_families_differ_from_baseline():
    assert hv.setting_family("prev_1").config.defect_prevalence_range == (0.01, 0.01)
    assert hv.setting_family("noise_x2").measurement_params != hv.setting_family("baseline").measurement_params


def test_leave_one_family_out_never_sees_the_left_out_family():
    rng = np.random.default_rng(3)
    rows = []
    for fam, shift in (("a", 0.0), ("b", 0.0), ("c", 50.0)):  # family c is on a wildly different scale
        s = rng.normal(size=300) + shift
        y = rng.random(300) < 0.1
        s[y] += 3
        rows.append(pd.DataFrame({"family": fam, "score": s, "is_defective": y, "override": False}))
    table = pd.concat(rows)
    lofo = hv.leave_one_family_out_thresholds(table)
    for fam in "abc":
        assert lofo[fam] == hv.tune_thresholds(table[table["family"] != fam])
    assert lofo["a"] != hv.tune_thresholds(table)  # the left-out family really changes the result
