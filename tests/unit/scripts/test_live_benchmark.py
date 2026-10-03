"""scripts/live_benchmark.py: resumable runs, paired cost difference and the M3 decision rule on toy tables."""
import numpy as np
import pandas as pd
import pytest

from harness import comparison as cmp
from scripts import live_benchmark as lb


def _parts(flag_review: list[bool], n_lots: int = 4, per_lot: int = 5) -> pd.DataFrame:
    """n_lots x per_lot parts; part 0 of every lot is defective. Module A REVIEW flags per `flag_review`
    (one flag per part, cycling); every other method flags the defective part only."""
    rows = []
    for lot in range(n_lots):
        for k in range(per_lot):
            idx = lot * per_lot + k
            row = {"lot_id": f"L{lot}", "component_id": f"C{k}", "family": "baseline" if lot < 2 else "other",
                   "is_defective": k == 0}
            for m in cmp.METHODS:
                row[f"{m}_evaluable"] = True
                row[f"{m}_flagged"] = k == 0
            row["module_a_review_flagged"] = flag_review[idx % len(flag_review)]
            rows.append(row)
    return pd.DataFrame(rows)


def test_cost_vector_hand_computed():
    parts = _parts([True, True, False, False, False])  # per lot: defective flagged; one false alarm; rest pass
    assert lb.cost_vector(parts, "module_a_review").tolist() == [0, 1, 0, 0, 0] * 4
    missed = _parts([False, False, False, False, False])
    assert lb.cost_vector(missed, "module_a_review").tolist() == [10, 0, 0, 0, 0] * 4


def test_cost_vector_matches_the_headline_cost_per_part():
    parts = _parts([True, False, True, False, False])
    head = cmp.headline_table(parts).set_index("method")
    assert lb.cost_vector(parts, "module_a_review").mean() == pytest.approx(head.loc["module_a_review", "cost_per_part"])


def test_paired_cost_difference_is_exact_and_ci_brackets_it():
    published = _parts([True, True, True, False, False])  # per lot: 2 false alarms
    live = _parts([True, False, False, False, False])  # per lot: 0 false alarms
    mean, lo, hi = lb.paired_cost_difference(published, live, "module_a_review", reps=200)
    assert mean == pytest.approx(2 / 5)
    assert lo <= mean <= hi
    assert lb.paired_cost_difference(published, live, "module_a_review", reps=200) == (mean, lo, hi)


def test_paired_cost_difference_rejects_different_parts():
    a = _parts([True])
    b = a.iloc[:-1]
    with pytest.raises(ValueError):
        lb.paired_cost_difference(a, b, "module_a_review")


def test_per_family_table_and_decision_rule():
    published = _parts([True, True, False, False, False])
    live = _parts([True, True, False, False, False])
    pf = lb.per_family_cost_difference(published, live)
    assert set(pf["family"]) == {"baseline", "other", "ALL"}
    assert (pf["cost_published_minus_live"] == 0).all()
    assert lb.decision(pf)["verdict"] == "no material difference"
    worse = _parts([True, True, True, True, False])
    pf2 = lb.per_family_cost_difference(worse, live)
    assert lb.decision(pf2)["verdict"] == "the Isolation Forest matters"


def test_decision_needs_both_thresholds():
    rows = [{"family": "ALL", "method": "module_a_review", "cost_published_minus_live": 0.005},
            {"family": "ALL", "method": "module_a_reject", "cost_published_minus_live": -0.02}]
    assert lb.decision(pd.DataFrame(rows))["verdict"] == "the Isolation Forest matters"
    rows[1]["cost_published_minus_live"] = -0.009
    assert lb.decision(pd.DataFrame(rows))["verdict"] == "no material difference"


def test_run_config_skips_a_finished_run(tmp_path):
    marker = lb.parts_path("live", tmp_path)
    marker.write_text("sentinel")
    assert lb.run_config("live", tmp_path) == marker
    assert marker.read_text() == "sentinel"  # nothing was recomputed or overwritten


def test_configs_published_is_the_default_behaviour():
    assert lb.CONFIGS["published"] == {"pooled_reference": True, "max_history": None}
    assert lb.CONFIGS["live"]["pooled_reference"] is False
