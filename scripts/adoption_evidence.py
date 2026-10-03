"""Session I2a Part 3 / 4b: the published-protocol evidence for Module A absolute scoring (V1).

    python -m scripts.adoption_evidence absolute     # score the 5 held-out sets (seed 2026) with V1, save the parts table
    python -m scripts.adoption_evidence report       # headline + per-family tables, bootstrap CIs, R1-R3 verdict
    python -m scripts.adoption_evidence heavytail    # 4b: clean-lot flag rate, different_noise_regime, absolute vs current

Protocol (docs/ADOPTION_PLAN.md, committed before this ran): the same five held-out families, seed 2026 and lot counts as
harness/results/p18; live configuration (no pooled reference, Isolation Forest inactive); V1 thresholds fixed at REVIEW
2.956 / REJECT 3.419 (module_a/settings.py, tuning seed 6101), no re-tuning here. The "current" rows and the four baselines are
read from docs/evidence_data/live_benchmark/ (parts_live = current scoring, live configuration; parts_published = current
scoring, Isolation Forest active), produced earlier by scripts.live_benchmark on the same lots; the headline of
parts_published is checked against harness/results/p18/comparison.md before use. Bootstrap: 1000 resamples of whole lots
(harness.variants.lot_bootstrap_metrics). Cost per part is FN:FP 10:1.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("docs/evidence_data/adoption")
LIVE = Path("docs/evidence_data/live_benchmark")
REVIEW_T, REJECT_T = 2.956, 3.419
BASELINES = ("static_limits", "fixed_delta", "static_pat", "dynamic_pat")
SEED = 2026
CLEAN_SEED = 7101


def absolute_path() -> Path:
    return OUT / "parts_absolute_live.csv.gz"


def run_absolute() -> Path:
    from harness import scoring as hs
    from harness import variants as hv
    from harness.held_out import generate_held_out_sets
    from module_a.scoring import ScoringConfig

    path = absolute_path()
    if path.exists():
        print("absolute: already done", flush=True)
        return path
    cfg = ScoringConfig(calibration="absolute", combination="max", review_threshold=REVIEW_T, reject_threshold=REJECT_T)
    tables = []
    for name, test_set in generate_held_out_sets(seed=SEED).items():
        results = hs.run_module_a(test_set, scoring=cfg)
        scores = hv.variant_part_scores(results)
        t = test_set.labels().merge(scores, on=["lot_id", "component_id"], how="left", validate="one_to_one")
        if t["score"].isna().any():
            raise ValueError(f"{name}: unscored parts")
        t = t.rename(columns={"score": "absolute_score"})
        tables.append(t)
        print(f"{name}: {len(t)} parts", flush=True)
    parts = pd.concat(tables, ignore_index=True)
    parts["absolute_review_flagged"] = parts["absolute_score"] >= REVIEW_T
    parts["absolute_reject_flagged"] = parts["absolute_score"] >= REJECT_T
    OUT.mkdir(parents=True, exist_ok=True)
    parts.to_csv(path, index=False, compression="gzip")
    return path


def _verify_published(published: pd.DataFrame) -> None:
    from harness import comparison as cmp

    head = cmp.headline_table(published).set_index("method")
    text = Path("harness/results/p18/comparison.md").read_text(encoding="utf-8")
    block = text.split("## headline")[1].split("##")[0]
    for method, row in head.iterrows():
        line = next(ln for ln in block.splitlines() if ln.startswith(f"| {method} |"))
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert int(cells[3]) == int(row["n_flagged"]), (method, cells)
        assert abs(float(cells[6]) - row["precision"]) < 5e-4 or np.isnan(row["precision"]), (method, cells)
    print("parts_published headline == harness/results/p18/comparison.md headline", flush=True)


def report() -> int:
    from harness import variants as hv

    live = pd.read_csv(LIVE / "parts_live.csv.gz")
    published = pd.read_csv(LIVE / "parts_published.csv.gz")
    _verify_published(published)
    absolute = pd.read_csv(absolute_path())
    keys = ["lot_id", "component_id"]
    t = live.merge(absolute[keys + ["absolute_score", "absolute_review_flagged", "absolute_reject_flagged"]],
                   on=keys, how="left", validate="one_to_one")
    assert t["absolute_score"].notna().all() and len(t) == len(live) == len(absolute)
    pub = published[keys + ["module_a_review_flagged", "module_a_reject_flagged"]].rename(
        columns={"module_a_review_flagged": "published_review_flagged", "module_a_reject_flagged": "published_reject_flagged"})
    t = t.merge(pub, on=keys, how="left", validate="one_to_one")
    for b in BASELINES:
        t[f"{b}_flagged"] = t[f"{b}_flagged"].astype(bool)
    methods = [
        ("static_limits", "static_limits_flagged"), ("fixed_delta", "fixed_delta_flagged"),
        ("static_pat", "static_pat_flagged"), ("dynamic_pat", "dynamic_pat_flagged"),
        ("current_published_review (IF active)", "published_review_flagged"),
        ("current_live_review", "module_a_review_flagged"), ("current_live_reject", "module_a_reject_flagged"),
        ("absolute_review", "absolute_review_flagged"), ("absolute_reject", "absolute_reject_flagged"),
    ]
    rows = []
    for label, col in methods:
        judged = f"{label}_evaluable" if label in BASELINES else None
        m = hv.lot_bootstrap_metrics(t, col, judged_col=judged)
        rows.append({"method": label, **m})
    head = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    head.to_csv(OUT / "published_protocol_headline.csv", index=False)

    fam_rows = []
    for fam, g in t.groupby("family", sort=True):
        for label, col in methods[4:]:
            m = hv.lot_bootstrap_metrics(g, col)
            fam_rows.append({"family": fam, "method": label, "n_parts": m["n_parts"], "n_defective": m["n_defective"],
                             "cost_per_part": m["cost_per_part"], "cost_ci_lo": m["cost_per_part_ci_lo"],
                             "cost_ci_hi": m["cost_per_part_ci_hi"], "recall": m["recall"], "flag_rate": m["flag_rate"]})
    fam = pd.DataFrame(fam_rows)
    fam.to_csv(OUT / "published_protocol_per_family.csv", index=False)

    a = head.set_index("method").loc["absolute_review"]
    diffs = {}
    for f_, g in fam.groupby("family"):
        gi = g.set_index("method")
        diffs[f_] = float(gi.loc["absolute_review", "cost_per_part"] - gi.loc["current_live_review", "cost_per_part"])
    verdict = {
        "R1_cost_review_le_0.22": {"value": float(a["cost_per_part"]), "holds": bool(a["cost_per_part"] <= 0.22)},
        "R2_recall_review_ge_0.75": {"value": float(a["recall"]), "holds": bool(a["recall"] >= 0.75)},
        "R3_no_family_cost_up_by_more_than_0.03": {"cost_difference_absolute_minus_current_live": diffs,
                                                     "holds": bool(max(diffs.values()) <= 0.03)},
        "R4": "measured by tests/integration/test_adoption_absolute.py; see ADOPTION_RESULT.md",
    }
    (OUT / "published_protocol_verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    pd.set_option("display.width", 250, "display.max_columns", 30)
    cols = ["method", "n_parts", "n_flagged", "flag_rate", "recall", "recall_ci_lo", "recall_ci_hi", "precision",
            "false_alarms", "missed", "cost_per_part", "cost_per_part_ci_lo", "cost_per_part_ci_hi"]
    print(head[cols].round(3).to_string(index=False))
    print(fam.round(3).to_string(index=False))
    print(json.dumps(verdict, indent=2))
    return 0


def heavytail() -> int:
    """4b: clean-lot (defect prevalence 0) flag rate on the heavy-tailed-noise family, absolute vs current (rank, live)."""
    from features.compute import compute
    from generator.lot import generate_lot
    from harness.variants import clean_family
    from module_a.detect import detect
    from module_a.scoring import ScoringConfig

    cfg = ScoringConfig(calibration="absolute", combination="max", review_threshold=REVIEW_T, reject_threshold=REJECT_T)
    out = {}
    for fam_name in ("different_noise_regime", "baseline"):
        fam = clean_family(fam_name)
        cur = ab = tot = 0
        for i in range(150):
            ds = generate_lot(f"I2A-HT-{fam_name}-{i:03d}", "PN-I2A", CLEAN_SEED, account_id="i2a", family=fam).dataset
            frames = compute(ds)
            for res, which in ((detect(frames), "cur"), (detect(frames, scoring=cfg), "abs")):
                flagged = {}
                for r in res:
                    flagged[r.component_id] = flagged.get(r.component_id, False) or r.severity_tier != "PASS"
                if which == "cur":
                    cur += sum(flagged.values())
                    tot += len(flagged)
                else:
                    ab += sum(flagged.values())
        out[fam_name] = {"lots": 150, "parts": tot, "current_rank_live_flag_rate": cur / tot,
                         "absolute_flag_rate": ab / tot, "seed": CLEAN_SEED}
        print(fam_name, out[fam_name], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "heavytail_clean_lot_flag_rate.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("absolute", "report", "heavytail"))
    args = ap.parse_args(argv)
    if args.what == "absolute":
        run_absolute()
        return 0
    return report() if args.what == "report" else heavytail()


if __name__ == "__main__":
    sys.exit(main())
