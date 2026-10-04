"""Session I2b Part 1: system-level benchmark (docs/SYSTEM_LEVEL_BENCHMARK.md, pre-registered).

    python -m scripts.system_benchmark run --mode absolute   # fused pipeline per lot, one scoring mode (resumable per family)
    python -m scripts.system_benchmark run --mode rank
    python -m scripts.system_benchmark report                # headline table, per-family table, gates

Each `run` writes docs/evidence_data/adoption/system_level/parts_<mode>.csv.gz (lot_id, component_id, family, is_defective,
verdict, module_a_ran). The part keys are those of the published-protocol lots (seed 2026).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

OUT = Path("docs/evidence_data/adoption/system_level")
LIVE = Path("docs/evidence_data/live_benchmark/parts_live.csv.gz")
ABS = Path("docs/evidence_data/adoption/parts_absolute_live.csv.gz")
TAUS = Path("docs/evidence_data/adoption/v1f/baseline_tuned_thresholds.json")
MARGIN_COST, MARGIN_RECALL, T_GAP = 0.01, 0.03, 0.03


def evaluate_gates(s_new: dict, s_old: dict, d_tuned: dict) -> dict:
    """Pre-registered G-flip, T1, T2 on the S-new / S-old / D-tuned metric rows (flag = not PASS)."""
    g_flip = (s_new["cost_per_part"] <= s_old["cost_per_part"] + MARGIN_COST
              and s_new["recall"] >= s_old["recall"] - MARGIN_RECALL)
    recall_gap = d_tuned["recall"] - s_new["recall"]
    cost_gap = s_new["cost_per_part"] - d_tuned["cost_per_part"]
    separated = (s_new["cost_per_part_ci_lo"] > d_tuned["cost_per_part_ci_hi"]
                 and s_new["recall_ci_hi"] < d_tuned["recall_ci_lo"])
    t1 = recall_gap > T_GAP and cost_gap > T_GAP and separated
    t2 = cost_gap <= T_GAP
    return {"G_flip": {"holds": bool(g_flip), "cost_new": s_new["cost_per_part"], "cost_old": s_old["cost_per_part"],
                       "recall_new": s_new["recall"], "recall_old": s_old["recall"]},
            "T1": {"fired": bool(t1), "recall_gap_vs_D_tuned": recall_gap, "cost_gap_vs_D_tuned": cost_gap,
                   "CIs_separated": bool(separated)},
            "T2": {"fired": bool(t2), "cost_gap_vs_D_tuned": cost_gap}}


def run(mode: str) -> int:
    os.environ["MODULE_A_SCORING"] = mode
    from contracts import ScreeningConfig
    from fusion.pipeline import run_full_pipeline
    from harness import bakeoff
    from harness.held_out import generate_held_out_sets, ground_truth_labels

    OUT.mkdir(parents=True, exist_ok=True)
    done = OUT / f"parts_{mode}.csv.gz"
    if done.exists():
        print(f"{mode}: already done", flush=True)
        return 0
    sets = generate_held_out_sets(seed=bakeoff.HARNESS_SEED)
    frames = []
    for family, hset in sets.items():
        fam_path = OUT / f"parts_{mode}__{family}.csv.gz"
        if fam_path.exists():
            frames.append(pd.read_csv(fam_path))
            print(f"{mode}/{family}: cached", flush=True)
            continue
        started, rows = time.time(), []
        for i, lot in enumerate(hset.lots):
            labels = ground_truth_labels(lot).set_index("component_id")
            results = run_full_pipeline(lot.dataset, ScreeningConfig())
            for a in results.assessments:
                rows.append({"lot_id": a.lot_id, "component_id": a.component_id, "family": family,
                             "is_defective": bool(labels.loc[a.component_id, "is_defective"]),
                             "verdict": a.verdict, "module_a_ran": bool(a.module_a_ran)})
            if i % 10 == 0:
                print(f"{mode}/{family}: lot {i + 1}/{len(hset.lots)} {time.time() - started:.0f}s", flush=True)
        fam = pd.DataFrame(rows)
        fam.to_csv(fam_path, index=False, compression="gzip")
        frames.append(fam)
        print(f"{mode}/{family}: {len(fam)} parts, {time.time() - started:.0f}s", flush=True)
    pd.concat(frames, ignore_index=True).to_csv(done, index=False, compression="gzip")
    return 0


def _table() -> pd.DataFrame:
    keys = ["lot_id", "component_id"]
    new = pd.read_csv(OUT / "parts_absolute.csv.gz")
    old = pd.read_csv(OUT / "parts_rank.csv.gz")
    live = pd.read_csv(LIVE)
    ab = pd.read_csv(ABS)
    t = new.rename(columns={"verdict": "verdict_new", "module_a_ran": "ran_new"}).merge(
        old[keys + ["verdict", "is_defective"]].rename(columns={"verdict": "verdict_old", "is_defective": "y_old"}),
        on=keys, how="outer", validate="one_to_one", indicator=True)
    assert (t["_merge"] == "both").all(), "S-new and S-old scored different parts"
    assert (t["is_defective"] == t["y_old"]).all(), "labels differ between runs"
    t = t.drop(columns="_merge")
    t = t.merge(live[keys + ["is_defective", "dynamic_pat_score", "dynamic_pat_evaluable", "fixed_delta_score",
                             "fixed_delta_evaluable"]].rename(columns={"is_defective": "y_live"}),
                on=keys, how="left", validate="one_to_one")
    assert t["y_live"].notna().all() and (t["y_live"].astype(bool) == t["is_defective"].astype(bool)).all(), \
        "part keys / labels differ from the published-protocol part file"
    t = t.merge(ab[keys + ["absolute_score", "absolute_review_flagged"]], on=keys, how="left", validate="one_to_one")
    taus = {b: v["tau"] for b, v in json.loads(TAUS.read_text()).items()}
    for b in ("fixed_delta", "dynamic_pat"):
        ev = t[f"{b}_evaluable"].astype(bool)
        t[f"{b}_evaluable"] = ev
        t[f"{b}_tuned"] = ev & (t[f"{b}_score"].fillna(float("-inf")) >= taus[b])
    t["S_new"] = t.verdict_new != "PASS"
    t["S_old"] = t.verdict_old != "PASS"
    t["S_new_rej"] = t.verdict_new == "REJECT"
    t["S_old_rej"] = t.verdict_old == "REJECT"
    t["A_new"] = t["absolute_review_flagged"].astype(bool)
    t["is_defective"] = t["is_defective"].astype(bool)
    return t


def report() -> int:
    from harness import variants as hv

    t = _table()
    methods = [("S-new (WATCH+REJECT)", "S_new", None), ("S-new (REJECT only)", "S_new_rej", None),
               ("S-old (WATCH+REJECT)", "S_old", None), ("S-old (REJECT only)", "S_old_rej", None),
               ("A-new (Module A alone, V1F REVIEW)", "A_new", None),
               ("D-tuned (fixed delta)", "fixed_delta_tuned", "fixed_delta_evaluable"),
               ("P-tuned (dynamic PAT)", "dynamic_pat_tuned", "dynamic_pat_evaluable")]
    rows = [{"method": m, **hv.lot_bootstrap_metrics(t, col, judged_col=j)} for m, col, j in methods]
    head = pd.DataFrame(rows)
    head.to_csv(OUT / "system_headline.csv", index=False)
    fam_rows = []
    for fam, g in t.groupby("family", sort=True):
        for m, col in (("S-new", "S_new"), ("S-old", "S_old"), ("A-new", "A_new")):
            r = hv.lot_bootstrap_metrics(g, col)
            fam_rows.append({"family": fam, "method": m, "flag_rate": r["flag_rate"], "recall": r["recall"],
                             "cost_per_part": r["cost_per_part"]})
    fam = pd.DataFrame(fam_rows)
    fam.to_csv(OUT / "system_per_family.csv", index=False)
    by = head.set_index("method")
    gates = evaluate_gates(by.loc["S-new (WATCH+REJECT)"].to_dict(), by.loc["S-old (WATCH+REJECT)"].to_dict(),
                           by.loc["D-tuned (fixed delta)"].to_dict())
    gates["module_B_effect_cost_Snew_minus_Anew"] = float(by.loc["S-new (WATCH+REJECT)", "cost_per_part"]
                                                           - by.loc["A-new (Module A alone, V1F REVIEW)", "cost_per_part"])
    (OUT / "system_gates.json").write_text(json.dumps(gates, indent=2), encoding="utf-8")
    pd.set_option("display.width", 250, "display.max_columns", 40)
    cols = ["method", "n_parts", "n_flagged", "flag_rate", "recall", "recall_ci_lo", "recall_ci_hi", "precision",
            "false_alarms", "missed", "cost_per_part", "cost_per_part_ci_lo", "cost_per_part_ci_hi"]
    print(head[cols].round(3).to_string(index=False))
    print(fam.pivot(index="family", columns="method", values="cost_per_part").round(3).to_string())
    print(json.dumps(gates, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=("rank", "absolute"), required=True)
    sub.add_parser("report")
    a = ap.parse_args(argv)
    return run(a.mode) if a.cmd == "run" else report()


if __name__ == "__main__":
    sys.exit(main())
