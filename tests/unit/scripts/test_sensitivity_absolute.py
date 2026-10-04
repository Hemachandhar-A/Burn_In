"""Session I2c: scripts/sensitivity.py scoring=absolute (V1F) - the sweep columns and the registered claims C1, C2, C5, C6, C7
(docs/ADOPTION_PLAN.md) on toy input; the default (rank) entry points keep their behaviour."""
import inspect

import numpy as np
import pandas as pd
import pytest

from scripts import sensitivity as sens


def _summary(overrides=None) -> pd.DataFrame:
    rows = []
    for setting in ("baseline", "prev_1", "noise_x2"):
        base = {"static_limits": (0.05, 1.0, 0.002, 0.5), "static_pat": (0.4, 0.4, 0.07, 0.35),
                "dynamic_pat": (0.6, 0.97, 0.03, 0.22), "fixed_delta": (1.0, 0.2, 0.24, 0.19),
                "module_a_review": (0.8, 0.2, 0.19, 0.24), "module_a_reject": (0.75, 0.2, 0.15, 0.24),
                "absolute_review": (0.92, 0.5, 0.05, 0.08), "absolute_reject": (0.9, 0.6, 0.04, 0.08)}
        for method, (recall, precision, flag, cost) in base.items():
            rows.append({"setting": setting, "method": method, "recall": recall, "precision": precision,
                         "flag_rate": flag, "cost_per_part": cost, **(overrides or {}).get((setting, method), {})})
    return pd.DataFrame(rows)


def test_claims_hold_on_a_favourable_toy():
    c = sens.evaluate_claims_absolute(_summary(), clean_flag_rate_noise_x2=0.05)
    for tier in ("absolute_review", "absolute_reject"):
        for key, v in c[tier].items():
            assert v["holds"], (tier, key)


def test_claims_report_where_each_breaks():
    s = _summary({("prev_1", "dynamic_pat"): {"recall": 0.95},
                  ("noise_x2", "absolute_review"): {"cost_per_part": 0.6, "flag_rate": 0.2}})
    s.loc[(s.setting == "prev_1") & (s.method == "absolute_review"), "flag_rate"] = 0.07
    c = sens.evaluate_claims_absolute(s, clean_flag_rate_noise_x2=0.09)["absolute_review"]
    assert c["C1_recall_exceeds_static_limits_static_pat_dynamic_pat"]["breaks"] == ["prev_1"]
    assert c["C2_cost_beats_static_limits"]["breaks"] == ["noise_x2"]
    assert c["C5_flag_rate_le_6pct_at_1pct_prevalence"]["holds"] is False
    assert c["C6_flag_rate_le_8pct_on_clean_lots_at_noise_x2"]["holds"] is False
    assert c["C7_cost_no_worse_than_current_by_more_than_0.03"]["breaks"] == ["noise_x2"]


def _toy_parts() -> pd.DataFrame:
    rows = []
    for lot in range(4):
        for k in range(10):
            rows.append({"lot_id": f"L{lot}", "component_id": f"C{k}", "is_defective": k < 2,
                         "static_pat_score": 2.0 if k < 2 else 0.5, "static_pat_evaluable": True})
    return pd.DataFrame(rows)


def test_tuned_baseline_columns_use_the_cut_and_evaluable():
    parts = _toy_parts()
    parts.loc[0, "static_pat_evaluable"] = False
    out = sens.add_tuned_baseline_columns(parts, {"static_pat": 1.5})
    assert out["static_pat_tuned_flagged"].sum() == 7  # 8 defective parts, one unevaluable -> not flagged
    assert out["static_pat_tuned_evaluable"].equals(out["static_pat_evaluable"])


def test_method_metrics_accepts_a_methods_argument_and_default_is_unchanged():
    assert sens.METHODS == ("static_limits", "fixed_delta", "static_pat", "dynamic_pat", "module_a_review", "module_a_reject")
    assert "methods" in inspect.signature(sens.method_metrics).parameters
    parts = _toy_parts()
    parts["x_flagged"], parts["x_evaluable"] = parts["is_defective"], True
    r = sens.method_metrics(parts, reps=20, methods=("x",))
    assert len(r) == 1 and r[0]["recall"] == 1.0 and r[0]["cost_per_part"] == 0.0


def test_run_setting_absolute_skips_a_finished_setting(tmp_path):
    path = sens.result_path("noise_x2", "live_absolute", tmp_path)
    path.write_text("sentinel")
    assert sens.run_setting_absolute("noise_x2", out_dir=tmp_path) == path
    assert path.read_text() == "sentinel"
