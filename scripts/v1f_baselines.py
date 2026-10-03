"""Session I2c Part 2: baseline fairness. Each industry baseline's single threshold is cost-tuned on tuning seed 6101 and
evaluated on the published protocol (seed 2026), next to V1F.

    python -m scripts.v1f_baselines tune     # score the tuning side (seed 6101, 5 families x 100 lots), tune the cut per baseline
    python -m scripts.v1f_baselines report   # published-protocol table + matched-flag-budget recall

Every baseline's part score is a RATIO to its own limit (harness/industry_baselines.py: static_limit_scores,
fixed_delta_scores, static_pat_scores, dynamic_pat_scores; `_summarize` flags `score > 1.0`). The one tunable parameter is
therefore that cut tau (default 1.0): flagging at `score >= tau` is the same as scaling the limit (the datasheet max/min, the
delta allowance, the PAT multiplier of 6 sigma). tau is found with the repo's own cost-sensitive optimiser
(harness.scoring.tune_threshold, FN:FP 10:1, flag at score >= tau) on parts the baseline could evaluate. No harness code
changes. V1F rows are read from the I2a published-protocol parts file: at lot size 77 (all benchmark lots) V1F == V1.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("docs/evidence_data/adoption/v1f")
LIVE = Path("docs/evidence_data/live_benchmark")
ADOPT = Path("docs/evidence_data/adoption")
BASELINES = ("static_limits", "fixed_delta", "static_pat", "dynamic_pat")


def tune() -> int:
    from harness import comparison as cmp
    from harness import scoring as hs
    from harness import variants as hv
    from harness.held_out import ground_truth_labels

    path = OUT / "baseline_tuning_parts.csv.gz"
    side = hv.SIDES["tune"]
    if not path.exists():
        pat_ref_lots = cmp.reference_lots(side.seed, cmp.PAT_REFERENCE_LOTS, hv.PART_NUMBER)
        from harness import industry_baselines as ib
        pat = ib.fit_static_pat(pat_ref_lots)
        tables = []
        for key in hv.FAMILY_NAMES:
            fam = hv.setting_family(key)
            for lot in hv.generate_lots(side, key, fam):
                labels = ground_truth_labels(lot)
                base = cmp._baseline_parts(lot.dataset, pat)
                t = labels.merge(base, on=["lot_id", "component_id"], how="left", validate="one_to_one")
                t["family_key"] = key
                tables.append(t)
            print(key, "done", flush=True)
        parts = pd.concat(tables, ignore_index=True)
        OUT.mkdir(parents=True, exist_ok=True)
        parts.to_csv(path, index=False, compression="gzip")
    parts = pd.read_csv(path)
    taus = {}
    for b in BASELINES:
        ev = parts[parts[f"{b}_evaluable"].fillna(False).astype(bool)]
        tau = hs.tune_threshold(ev[f"{b}_score"].to_numpy(float), ev["is_defective"].to_numpy(bool), hs.FN_FP_COST_RATIO)
        taus[b] = {"tau": float(tau), "default_tau": 1.0, "tuning_parts": int(len(ev)), "tuning_defective": int(ev.is_defective.sum())}
        print(b, taus[b], flush=True)
    (OUT / "baseline_tuned_thresholds.json").write_text(json.dumps(taus, indent=2), encoding="utf-8")
    return 0


def _top_k_recall(score: np.ndarray, y: np.ndarray, k: int) -> float:
    order = np.argsort(-score, kind="stable")[:k]
    return float(y[order].sum() / y.sum())


def report() -> int:
    from harness import variants as hv

    taus = json.loads((OUT / "baseline_tuned_thresholds.json").read_text())
    live = pd.read_csv(LIVE / "parts_live.csv.gz")
    ab = pd.read_csv(ADOPT / "parts_absolute_live.csv.gz")
    keys = ["lot_id", "component_id"]
    t = live.merge(ab[keys + ["absolute_score", "absolute_review_flagged", "absolute_reject_flagged"]], on=keys,
                   how="left", validate="one_to_one")
    assert t["absolute_score"].notna().all() and len(t) == len(live)
    assert t.groupby("lot_id").size().eq(77).all(), "all benchmark lots must have 77 parts for V1F == V1"
    rows = []

    def add(label, col, judged=None):
        m = hv.lot_bootstrap_metrics(t, col, judged_col=judged)
        rows.append({"method": label, "tau": None, **m})

    for b in BASELINES:
        t[f"{b}_flagged"] = t[f"{b}_flagged"].astype(bool)
        t[f"{b}_evaluable"] = t[f"{b}_evaluable"].astype(bool)
        t[f"{b}_tuned_flagged"] = t[f"{b}_evaluable"] & (t[f"{b}_score"].fillna(-np.inf) >= taus[b]["tau"])
        add(f"{b} default", f"{b}_flagged", f"{b}_evaluable")
        add(f"{b} cost-tuned (tau={taus[b]['tau']:.3f})", f"{b}_tuned_flagged", f"{b}_evaluable")
    add("V1F REVIEW", "absolute_review_flagged")
    add("V1F REJECT", "absolute_reject_flagged")
    add("current (rank, live) REVIEW", "module_a_review_flagged")
    head = pd.DataFrame(rows)
    head.to_csv(OUT / "fairness_table.csv", index=False)

    # F-R6 verdict
    v = head.set_index("method").loc["V1F REVIEW"]
    verdict = {}
    for b in BASELINES:
        r = head[head.method.str.startswith(f"{b} cost-tuned")].iloc[0]
        d = head[head.method == f"{b} default"].iloc[0]
        verdict[b] = {
            "V1F_cost": [v.cost_per_part, v.cost_per_part_ci_lo, v.cost_per_part_ci_hi],
            "tuned_cost": r.cost_per_part, "default_cost": d.cost_per_part,
            "cheaper_than_tuned_F_R6 (V1F cost CI hi < tuned cost)": bool(v.cost_per_part_ci_hi < r.cost_per_part),
            "cheaper_than_default (V1F CI hi < default cost)": bool(v.cost_per_part_ci_hi < d.cost_per_part)}

    # matched flag budget (evaluable parts only for a baseline's own budget; ranks by score)
    y_all = t["is_defective"].to_numpy(bool)
    mb = []
    for b in BASELINES:
        ev = t[t[f"{b}_evaluable"]]
        y = ev["is_defective"].to_numpy(bool)
        k_b = int(ev[f"{b}_tuned_flagged"].sum())
        k_v = int(t["absolute_review_flagged"].sum())
        mb.append({"baseline": b, "baseline_tuned_flags": k_b, "V1F_flags": k_v,
                   "V1F_recall_at_baseline_budget": _top_k_recall(t["absolute_score"].to_numpy(float), y_all, k_b),
                   "baseline_recall_at_baseline_budget": float(y[ev[f"{b}_tuned_flagged"].to_numpy()].sum() / y.sum()),
                   "V1F_recall_at_V1F_budget": _top_k_recall(t["absolute_score"].to_numpy(float), y_all, k_v),
                   "baseline_recall_at_V1F_budget": _top_k_recall(ev[f"{b}_score"].to_numpy(float), y, min(k_v, len(ev)))})
    mbt = pd.DataFrame(mb)
    mbt.to_csv(OUT / "fairness_matched_budget.csv", index=False)
    (OUT / "fairness_verdict.json").write_text(json.dumps(verdict, indent=2, default=float), encoding="utf-8")
    pd.set_option("display.width", 250, "display.max_columns", 40)
    cols = ["method", "n_flagged", "flag_rate", "recall", "recall_ci_lo", "recall_ci_hi", "precision", "cost_per_part",
            "cost_per_part_ci_lo", "cost_per_part_ci_hi"]
    print(head[cols].round(3).to_string(index=False))
    print(mbt.round(3).to_string(index=False))
    print(json.dumps(verdict, indent=2, default=float))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("tune", "report"))
    a = ap.parse_args(argv)
    return tune() if a.what == "tune" else report()


if __name__ == "__main__":
    sys.exit(main())
