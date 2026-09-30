"""E5 step 7 (session P1.8): comparison tables for the PPT's differentiation-versus-industry-baseline slide,
handed to the Lead.

Every held-out part (the same five families and seed as the P1.7 bake-off) is judged by:
    static_limits    a datasheet max per parameter at every checkpoint        (harness.industry_baselines)
    fixed_delta      space-spec |reading - 0h| allowance after burn-in
    static_pat       AEC-Q001 PAT, limits fit once on a pooled reference population of earlier lots
    dynamic_pat      AEC-Q001 DPAT, limits recomputed per lot
    module_a_review  Module A's max-combined severity >= the committed REVIEW threshold
    module_a_reject  ... >= the committed REJECT threshold
The baselines run at their own published operating points (flag = outside the limit), not re-tuned; Module A
runs at the thresholds in config/harness_thresholds.yaml. Everything sees the full Complete-lot series,
0h-168h - Module A is the post-hoc screen, so this is a like-for-like comparison of the same information.

module_a_reject is the *pre-cap* REJECT tier: module_a's direction cap (E2 step 6) and fusion's
Isolation-Forest-only cap (E12) can move a part from REJECT down to WATCH but never unflag it, so
module_a_review is the honest "reaches a reviewer" figure and module_a_reject an upper bound on REJECTs.

A method that cannot judge a part (no limit for it, below the PAT minimum population) is reported through
`evaluable_share` and its metrics are computed over the parts it could judge - never counted as a pass.
Precision is undefined (NaN) for a method that flags nothing.

Tables are written as CSV (PowerPoint's own charts are built from exactly this kind of table) and one
Markdown summary. No chart images: the locked stack has no Python plotting library, and adding one is a Lead
decision (AGENTS.md "Locked stack") - the long-form CSVs (archetype_recall.csv) are shaped for direct charting.

Run `python -m harness.comparison` (several minutes: it re-runs Module A over every held-out lot) to
regenerate harness/results/p18/.
"""
import argparse
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from contracts import HarnessThresholds, LotDataset
from generator.lot import generate_lot
from harness import bakeoff, golden, scoring
from harness import industry_baselines as ib
from harness.held_out import HELD_OUT_ACCOUNT_ID, HELD_OUT_PART_NUMBER, HeldOutTestSet, generate_held_out_sets

BASELINES = ("static_limits", "fixed_delta", "static_pat", "dynamic_pat")
METHODS = (*BASELINES, "module_a_review", "module_a_reject")
PAT_REFERENCE_LOTS = 10  # the pooled "historical" population static PAT is fit on
PAT_REFERENCE_PREFIX = "PATREF"  # disjoint from held-out ids ("HO-<family>-<n>")
PAT_REFERENCE_FAMILY = "baseline"  # the nominal process the static limits were set against
RESULTS_DIR = Path(__file__).resolve().parent / "results" / "p18"
_KEY = ["lot_id", "component_id"]


# --- building the per-part table ----------------------------------------------------------------------------

def reference_lots(seed: int, n_lots: int = PAT_REFERENCE_LOTS,
                   part_number: str = HELD_OUT_PART_NUMBER) -> list[LotDataset]:
    return [generate_lot(f"{PAT_REFERENCE_PREFIX}-{i:04d}", part_number, seed, account_id=HELD_OUT_ACCOUNT_ID,
                         family=PAT_REFERENCE_FAMILY).dataset for i in range(n_lots)]


def _baseline_parts(dataset: LotDataset, pat_limits: ib.PatLimits) -> pd.DataFrame:
    scorers = {
        "static_limits": lambda: ib.static_limit_scores(dataset, ib.default_datasheet_limits()),
        "fixed_delta": lambda: ib.fixed_delta_scores(dataset, ib.default_delta_limits()),
        "static_pat": lambda: ib.static_pat_scores(dataset, pat_limits),
        "dynamic_pat": lambda: ib.dynamic_pat_scores(dataset),
    }
    out = None
    for name, score in scorers.items():
        part = ib.part_level(score())[["component_id", "score", "flagged", "evaluable"]]
        part = part.rename(columns={c: f"{name}_{c}" for c in ("score", "flagged", "evaluable")})
        out = part if out is None else out.merge(part, on="component_id", how="outer", validate="one_to_one")
    out.insert(0, "lot_id", dataset.lot_id)
    return out


def add_module_a_flags(parts: pd.DataFrame, thresholds: HarnessThresholds) -> pd.DataFrame:
    if thresholds.combination_strategy != "max":
        raise ValueError(f"comparison assumes the shipped max combination, got {thresholds.combination_strategy!r}")
    parts = parts.copy()
    parts["module_a_review_flagged"] = parts["module_a_score"] >= thresholds.module_a_review_threshold
    parts["module_a_reject_flagged"] = parts["module_a_score"] >= thresholds.module_a_reject_threshold
    for tier in ("review", "reject"):
        parts[f"module_a_{tier}_score"] = parts["module_a_score"]
        parts[f"module_a_{tier}_evaluable"] = True
    return parts


def part_table(sets: Mapping[str, HeldOutTestSet], thresholds: HarnessThresholds, *, seed: int,
               n_reference_lots: int = PAT_REFERENCE_LOTS) -> pd.DataFrame:
    """One row per held-out part: ground truth, Module A's severity, and every method's score/flag/evaluable."""
    tables = []
    for test_set in sets.values():
        part_number = test_set.lots[0].dataset.part_number
        pat_limits = ib.fit_static_pat(reference_lots(seed, n_reference_lots, part_number))
        module_a = scoring.module_a_table(test_set)
        module_a["module_a_score"] = module_a[list(scoring.DETECTORS)].max(axis=1)
        module_a = module_a.drop(columns=list(scoring.DETECTORS))
        base = pd.concat([_baseline_parts(lot.dataset, pat_limits) for lot in test_set.lots], ignore_index=True)
        tables.append(module_a.merge(base, on=_KEY, how="left", validate="one_to_one"))
    parts = pd.concat(tables, ignore_index=True)
    for name in BASELINES:
        parts[f"{name}_flagged"] = parts[f"{name}_flagged"].fillna(False).astype(bool)
        parts[f"{name}_evaluable"] = parts[f"{name}_evaluable"].fillna(False).astype(bool)
    return add_module_a_flags(parts, thresholds)


# --- tables -------------------------------------------------------------------------------------------------

def headline_table(parts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for method in METHODS:
        judged = parts[parts[f"{method}_evaluable"].astype(bool)]
        row = {"method": method, "n_parts": len(parts), "evaluable_share": len(judged) / len(parts)}
        if len(judged):
            y, flagged = judged["is_defective"].to_numpy(bool), judged[f"{method}_flagged"].to_numpy(bool)
            m = scoring.classification_metrics(y, flagged)
            row.update(n_flagged=m["n_flagged"], flag_rate=m["flag_rate"], recall=m["recall"],
                       precision=m["precision"] if m["n_flagged"] else math.nan,
                       false_alarms=int((flagged & ~y).sum()), missed=int((~flagged & y).sum()),
                       cost_per_part=m["cost"])
        else:
            row.update(n_flagged=0, flag_rate=math.nan, recall=math.nan, precision=math.nan,
                       false_alarms=0, missed=0, cost_per_part=math.nan)
        rows.append(row)
    return pd.DataFrame(rows)


def archetype_recall(parts: pd.DataFrame) -> pd.DataFrame:
    """Long form - one row per (method, defect archetype) - ready to chart as grouped bars."""
    rows = []
    defective = parts[parts["is_defective"].astype(bool)]
    for method in METHODS:
        judged = defective[defective[f"{method}_evaluable"].astype(bool)]
        for defect_type, group in judged.groupby("defect_type", sort=True):
            rows.append({"method": method, "defect_type": defect_type, "n": len(group),
                         "recall": float(group[f"{method}_flagged"].mean())})
    return pd.DataFrame(rows, columns=["method", "defect_type", "n", "recall"])


def matched_flag_budget(parts: pd.DataFrame) -> pd.DataFrame:
    """For each baseline, Module A given exactly the same number of flags (its top-k by severity) on the same
    parts - the fairest single comparison, independent of either side's threshold choice. A baseline that
    judged nothing, or flagged nothing, has no budget to match and is left out."""
    rows = []
    for name in BASELINES:
        judged = parts[parts[f"{name}_evaluable"].astype(bool)]
        k = int(judged[f"{name}_flagged"].sum()) if len(judged) else 0
        if k == 0:
            continue
        y = judged["is_defective"].to_numpy(bool)
        order = np.argsort(-judged["module_a_score"].to_numpy(float), kind="stable")
        top = np.zeros(len(judged), dtype=bool)
        top[order[:k]] = True
        base = judged[f"{name}_flagged"].to_numpy(bool)
        rows.append({"baseline": name, "n_parts": len(judged), "n_flagged": k, "flag_rate": k / len(judged),
                     "baseline_recall": float(base[y].mean()), "module_a_recall": float(top[y].mean()),
                     "baseline_precision": float(y[base].mean()), "module_a_precision": float(y[top].mean())})
    return pd.DataFrame(rows)


def golden_example_table(thresholds: HarnessThresholds | None = None) -> pd.DataFrame:
    """What each method does with the problem statement's own worked example (harness.golden): lot median
    10 uA, a part at 45 uA, a 50 uA datasheet limit."""
    from module_a.detect import detect

    thresholds = thresholds or bakeoff.load_harness_thresholds()
    lot = golden.golden_lot()
    gid = golden.GOLDEN_COMPONENT_ID

    def part(scores: pd.DataFrame) -> dict:
        row = ib.part_level(scores).set_index("component_id").loc[gid]
        return {"evaluable": bool(row["evaluable"]), "flagged": bool(row["flagged"]), "score": float(row["score"])}

    rows = [
        {"method": "static_limits", **part(ib.static_limit_scores(lot, golden.golden_datasheet_limits())),
         "note": "45 uA against the 50 uA datasheet max - inside the limit"},
        {"method": "fixed_delta", **part(ib.fixed_delta_scores(lot, ib.default_delta_limits())),
         "note": "the part reads 45 uA at every checkpoint - it never drifts"},
        {"method": "static_pat", "evaluable": False, "flagged": False, "score": math.nan,
         "note": "no pooled reference population exists for this part number"},
        {"method": "dynamic_pat", **part(ib.dynamic_pat_scores(lot)),
         "note": "lot-relative limits - catches a static level outlier"},
    ]
    parts = scoring.part_detector_scores(detect(golden.golden_feature_frames()))
    score = float(parts.set_index("component_id").loc[gid, list(scoring.DETECTORS)].max())
    tier = ("REJECT" if score >= thresholds.module_a_reject_threshold
            else "REVIEW" if score >= thresholds.module_a_review_threshold else "PASS")
    rows.append({"method": "module_a", "evaluable": True, "flagged": tier != "PASS", "score": score, "tier": tier,
                 "note": "max-combined within-lot severity; tier from config/harness_thresholds.yaml"})
    table = pd.DataFrame(rows, columns=["method", "evaluable", "flagged", "score", "tier", "note"])
    table.attrs["lot_id"] = lot.lot_id
    return table


def module_b_tables(module_b_summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(detail, summary): Module B's MAE and interval coverage against the three physics baselines, from the
    P1.7 evaluation report, and per horizon how many (family, parameter) cells the model beats every baseline."""
    cols = ["family", "parameter", "horizon", "mae_model", "mae_persistence", "mae_linear", "mae_power_law",
            "best_baseline", "model_beats_best_baseline", "coverage", "target_coverage"]
    detail = module_b_summary[cols].copy()
    summary = (detail.groupby("horizon")
               .agg(cells=("model_beats_best_baseline", "size"), model_beats_best=("model_beats_best_baseline", "sum"),
                    median_coverage=("coverage", "median"), min_coverage=("coverage", "min"))
               .reset_index())
    return detail, summary


# --- output -------------------------------------------------------------------------------------------------

def _md(table: pd.DataFrame) -> str:
    def cell(v):
        if isinstance(v, float):
            return "n/a" if math.isnan(v) else f"{v:.3f}"
        return "" if v is None else str(v)
    head = "| " + " | ".join(map(str, table.columns)) + " |"
    rule = "|" + "---|" * len(table.columns)
    body = ["| " + " | ".join(cell(v) for v in row) + " |" for row in table.itertuples(index=False)]
    return "\n".join([head, rule, *body])


def write_outputs(parts: pd.DataFrame, out_dir: Path, *, module_b: pd.DataFrame | None,
                  bakeoff_costs: Mapping[str, float] | None = None,
                  thresholds: HarnessThresholds | None = None) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "headline": headline_table(parts),
        "archetype_recall": archetype_recall(parts),
        "matched_flag_budget": matched_flag_budget(parts),
        "golden_example": golden_example_table(thresholds),
    }
    if module_b is not None:
        tables["module_b_vs_physics"], tables["module_b_summary"] = module_b_tables(module_b)
    if bakeoff_costs:
        tables["combination_bakeoff"] = pd.DataFrame(
            [{"strategy": k, "mean_held_out_cost": v, "shipped": k == bakeoff.SHIPPED_STRATEGY}
             for k, v in bakeoff_costs.items()])
    for name, table in tables.items():
        table.to_csv(out_dir / f"{name}.csv", index=False)
    sections = [
        "# P1.8 - Differentiation versus industry baselines (E5 step 7)",
        ("Generated by `python -m harness.comparison`; do not hand-edit. Held-out parts: "
         f"{len(parts)} ({int(parts['is_defective'].sum())} defective) across families "
         f"{', '.join(sorted(parts['family'].unique()))}. Cost is per part at FN:FP "
         f"{scoring.FN_FP_COST_RATIO:g}:1. module_a_reject is pre-cap (see harness/comparison.py)."),
    ]
    for name, table in tables.items():
        sections += [f"## {name}", _md(table)]
    (out_dir / "comparison.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=bakeoff.HARNESS_SEED)
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)
    thresholds = bakeoff.load_harness_thresholds()
    sets = generate_held_out_sets(seed=args.seed)
    parts = part_table(sets, thresholds, seed=args.seed)
    report = json.loads(bakeoff.RESULTS_PATH.read_text(encoding="utf-8"))
    if report["seed"] != args.seed:
        raise ValueError(f"p17_evaluation.json is from seed {report['seed']}, not {args.seed} - rerun harness.bakeoff")
    write_outputs(parts, args.out, module_b=pd.DataFrame(report["module_b"]),
                  bakeoff_costs=report["mean_held_out_cost"], thresholds=thresholds)
    print(headline_table(parts).to_string(index=False))


if __name__ == "__main__":
    main()
