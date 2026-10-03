"""S6X: scripts/scoring_experiment.py end to end on a tiny configuration (not the experiment's numbers)."""
import json

import pytest

from scripts import scoring_experiment as se


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    root = tmp_path_factory.mktemp("s6x")
    exp = se.Experiment(out_dir=root / "out", cache_dir=root / "cache",
                        lots={"tune": 10, "eval": 4, "clean": 12, "rob": 4})
    units = {f"V{c}-C{k}": {p: "pass" for p in ("p3", "p4", "p5")} for c in (1, 2) for k in (0, 1, 2)}
    se.run_units = lambda out_dir: units  # the pytest sub-run is covered by its own test file
    return exp


def test_stage_a_runs_resumes_and_reports(ran):
    exp = ran
    exp.baselines()
    decision = se.stage_a(exp)
    assert decision["label"] in {"passing", "best_not_passing_S1_only", "best_not_passing_no_S1", "none"}
    files = sorted(p.name for p in exp.out_dir.glob("variant_*.json"))
    assert files == ["variant_V0.json", "variant_V1.json", "variant_V2k10.json", "variant_V2k2.json", "variant_V2k5.json"]
    first = json.loads((exp.out_dir / "variant_V1.json").read_text())
    again = se.stage_a(exp)  # resumable: a second call reads the saved decision
    assert again["winner"] == decision["winner"]
    # thresholds were tuned on tuning data and stored; the evaluation block exists with CIs
    assert set(first["thresholds"]) == {"review", "reject"}
    assert {"recall_ci_lo", "cost_per_part_ci_hi"} <= set(first["eval"]["review"])
    v0 = json.loads((exp.out_dir / "variant_V0.json").read_text())
    assert "eval_shipped_thresholds" in v0 and v0["p1"]["share_flagged_at_shipped_thresholds"] is not None


def test_k2_is_v1_by_the_cold_start_rule(ran):
    exp = ran
    se.stage_a(exp)
    v1 = json.loads((exp.out_dir / "variant_V1.json").read_text())
    k2 = json.loads((exp.out_dir / "variant_V2k2.json").read_text())
    assert v1["thresholds"] == k2["thresholds"]
    assert v1["eval"]["review"]["cost_per_part"] == k2["eval"]["review"]["cost_per_part"]


def test_report_has_the_p1_table_first_and_all_criteria(ran):
    exp = ran
    se.stage_a(exp)
    text = se.report(exp)
    assert text.index("## P1") < text.index("## Held-out headline")
    for key in ("S1", "S2", "S3", "S4", "S5", "S6"):
        assert key in text
    assert (exp.out_dir / "SUMMARY.md").exists() and (exp.out_dir / "criteria.json").exists()


def test_selection_rule_prefers_the_simpler_variant_inside_the_tie_band():
    def res(name, cost, passing=True):
        return {"variant": name, "cost": cost, "passing": passing}
    real_criteria = se.criteria
    se.criteria = lambda r, v0, sp, units: {"all": r["passing"], "S1": r["passing"], "values": {"cost": r["cost"]}}
    try:
        out = se.select([res("V1", 0.200), res("V2k5", 0.198)], {}, 0.1, {}, ["V0", "V1", "V2k5"])
        assert out["winner"] == "V1"  # 0.002 apart: a tie, the simpler wins
        out = se.select([res("V1", 0.210), res("V2k5", 0.198)], {}, 0.1, {}, ["V0", "V1", "V2k5"])
        assert out["winner"] == "V2k5"
        out = se.select([res("V1", 0.2, False), res("V2k5", 0.3, False)], {}, 0.1, {}, ["V0", "V1", "V2k5"])
        assert out["label"].startswith("best_not_passing") and out["winner"] == "V1"
    finally:
        se.criteria = real_criteria
