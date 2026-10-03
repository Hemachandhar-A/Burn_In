"""scripts/sensitivity.py: settings map to the generator's own config objects, runs are resumable, and the
metric / ranking / claim builders are right on toy input."""
import json

import numpy as np
import pandas as pd
import pytest

from generator.families import FAMILIES
from harness import comparison as cmp
from scripts import sensitivity as sens


def test_baseline_setting_is_the_registered_baseline_family():
    assert sens.make_family(sens.SETTINGS["baseline"]) is FAMILIES["baseline"]


def test_there_are_nine_non_baseline_settings_one_dimension_each():
    assert len(sens.SETTINGS) == 10  # baseline + noise x2, prevalence x3, exponent x2, lot size x2
    base = FAMILIES["baseline"]
    for name, setting in sens.SETTINGS.items():
        if name == "baseline":
            continue
        fam = sens.make_family(setting)
        changed = [
            fam.config.defect_prevalence_range != base.config.defect_prevalence_range,
            fam.config.power_law_exponent_range != base.config.power_law_exponent_range,
            dict(fam.measurement_params.noise_frac) != dict(base.measurement_params.noise_frac),
            setting.n_parts is not None,
        ]
        assert sum(changed) == 1, name  # exactly one knob moves per setting


def test_noise_prevalence_and_exponent_values():
    base = FAMILIES["baseline"]
    x2 = sens.make_family(sens.SETTINGS["noise_x2"]).measurement_params
    assert x2.noise_frac["iddq"] == pytest.approx(2 * base.measurement_params.noise_frac["iddq"])
    assert x2.tester_offset_sigma["leakage"] == pytest.approx(2 * base.measurement_params.tester_offset_sigma["leakage"])
    assert sens.make_family(sens.SETTINGS["prev_3"]).config.defect_prevalence_range == (0.03, 0.03)
    assert sens.make_family(sens.SETTINGS["exp_high"]).config.power_law_exponent_range == (0.25, 0.40)
    assert (sens.SETTINGS["lot_30"].n_parts, sens.SETTINGS["lot_150"].n_parts) == (30, 150)


def test_generate_lots_honours_lot_size_and_prevalence():
    lots = sens.generate_lots(sens.SETTINGS["lot_30"], 2)
    assert [len(lot.ground_truth.trajectories.parts) for lot in lots.lots] == [30, 30]
    prev = sens.generate_lots(sens.SETTINGS["prev_8"], 3)
    rates = [np.mean([p.is_defective for p in lot.ground_truth.trajectories.parts]) for lot in prev.lots]
    assert all(0.0 <= r <= 0.25 for r in rates)
    assert list(prev.labels().columns) == ["lot_id", "component_id", "family", "is_defective", "defect_type"]


def test_run_setting_skips_a_finished_setting(tmp_path):
    path = sens.result_path("noise_x2", "live", tmp_path)
    path.write_text("sentinel")
    assert sens.run_setting("noise_x2", "live", tmp_path) == path
    assert path.read_text() == "sentinel"  # a second run redoes nothing


def _toy_parts(n_lots=6, per_lot=10) -> pd.DataFrame:
    rows = []
    for lot in range(n_lots):
        for k in range(per_lot):
            row = {"lot_id": f"L{lot}", "component_id": f"C{k}", "is_defective": k < 2}
            for m in cmp.METHODS:
                row[f"{m}_evaluable"] = True
                row[f"{m}_flagged"] = k < 2
            rows.append(row)
    return pd.DataFrame(rows)


def test_method_metrics_hand_computed():
    parts = _toy_parts()
    # module_a_review: flags parts 1,2,3 of every lot -> TP=1, FP=2, FN=1 per lot of 10
    parts["module_a_review_flagged"] = parts["component_id"].isin(["C1", "C2", "C3"])
    rows = {r["method"]: r for r in sens.method_metrics(parts, reps=100)}
    r = rows["module_a_review"]
    assert r["recall"] == pytest.approx(0.5) and r["precision"] == pytest.approx(1 / 3)
    assert r["flag_rate"] == pytest.approx(0.3) and r["cost_per_part"] == pytest.approx((10 * 1 + 2) / 10)
    assert r["recall_ci_lo"] <= r["recall"] <= r["recall_ci_hi"]
    assert rows["static_limits"]["recall"] == 1.0 and rows["static_limits"]["cost_per_part"] == 0.0


def test_precision_is_nan_when_nothing_is_flagged():
    parts = _toy_parts()
    parts["dynamic_pat_flagged"] = False
    r = {x["method"]: x for x in sens.method_metrics(parts, reps=50)}["dynamic_pat"]
    assert np.isnan(r["precision"]) and r["recall"] == 0.0


def _summary(overrides=None) -> pd.DataFrame:
    """Two settings; Module A beats everything unless an override says otherwise."""
    rows = []
    for setting in ("baseline", "prev_1"):
        base = {"static_limits": (0.05, 1.0, 0.002, 0.5), "static_pat": (0.4, 0.4, 0.07, 0.35),
                "dynamic_pat": (0.6, 0.97, 0.03, 0.22), "fixed_delta": (1.0, 0.2, 0.24, 0.19),
                "module_a_review": (0.85, 0.2, 0.24, 0.28), "module_a_reject": (0.8, 0.2, 0.2, 0.27)}
        for method, (recall, precision, flag, cost) in base.items():
            rows.append({"setting": setting, "method": method, "recall": recall, "precision": precision,
                         "flag_rate": flag, "cost_per_part": cost,
                         **(overrides or {}).get((setting, method), {})})
    return pd.DataFrame(rows)


def test_claims_all_hold_on_a_favourable_toy():
    c = sens.evaluate_claims(_summary())
    assert c["module_a_review"]["C1_recall_exceeds_static_limits_static_pat_dynamic_pat"]["holds"]
    assert c["module_a_review"]["C2_cost_beats_static_limits"]["holds"]
    assert c["module_a_review"]["C3_flag_rate_at_least_10pct_at_1pct_prevalence"]["holds"]
    assert c["C4_dynamic_pat_precision_above_0.9"]["holds"]


def test_claims_report_where_each_one_breaks():
    s = _summary({("prev_1", "dynamic_pat"): {"recall": 0.9, "precision": 0.85},
                    ("prev_1", "module_a_review"): {"flag_rate": 0.05, "cost_per_part": 0.6}})
    c = sens.evaluate_claims(s)
    assert c["module_a_review"]["C1_recall_exceeds_static_limits_static_pat_dynamic_pat"]["breaks"] == ["prev_1"]
    assert c["module_a_review"]["C2_cost_beats_static_limits"]["breaks"] == ["prev_1"]
    assert c["module_a_review"]["C3_flag_rate_at_least_10pct_at_1pct_prevalence"]["holds"] is False
    assert c["C4_dynamic_pat_precision_above_0.9"]["breaks"] == ["prev_1"]
    assert c["module_a_reject"]["C2_cost_beats_static_limits"]["holds"] is True  # reject was not touched


def test_cost_ranking_orders_by_cost_per_part():
    r = sens.cost_ranking(_summary()).set_index("setting")["rank_by_cost"]
    assert r["baseline"].split(" < ")[0] == "fixed_delta"
    assert r["baseline"].split(" < ")[-1] == "static_limits"


def test_report_and_load_summary_round_trip(tmp_path):
    parts = _toy_parts()
    payload = {"setting": "baseline", "config": "live", "label": "baseline (all defaults)", "lots": 6, "parts": 60,
               "defective": 12, "seconds": 1, "methods": sens.method_metrics(parts, reps=50)}
    sens.result_path("baseline", "live", tmp_path).write_text(json.dumps(payload))
    summary = sens.load_summary("live", tmp_path)
    assert set(summary["setting"]) == {"baseline"} and len(summary) == len(sens.METHODS)
    text = sens.report("live", tmp_path)
    assert "module_a_review" in text and (tmp_path / "claims__live.json").exists()
