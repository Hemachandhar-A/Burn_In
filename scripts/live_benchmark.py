"""M1 evidence: the P1.8 benchmark re-run in the LIVE configuration (no pooled reference, Isolation Forest
inactive) next to the published configuration, plus a history-length sweep. Measurement only; thresholds
and every default are untouched.

    PYTHONPATH=. uv run python -m scripts.live_benchmark run --config live        # one configuration (resumable)
    PYTHONPATH=. uv run python -m scripts.live_benchmark report                    # tables from the saved runs

Configurations: published (all earlier lots pooled - what harness/results/p18 reports), live (prior_frames
empty - what the app's pipeline does), hist2 / hist5 / hist10 (the 2/5/10 most recent earlier lots). Each run
saves its part-level table under docs/evidence_data/live_benchmark/, so a finished run is never repeated.
Criterion: docs/EVIDENCE_PLAN.md (M3 decision rule).
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path("docs/evidence_data/live_benchmark")
CONFIGS = {
    "published": {"pooled_reference": True, "max_history": None},
    "live": {"pooled_reference": False, "max_history": None},
    "hist2": {"pooled_reference": True, "max_history": 2},
    "hist5": {"pooled_reference": True, "max_history": 5},
    "hist10": {"pooled_reference": True, "max_history": 10},
}
MODULE_A = ("module_a_review", "module_a_reject")
FN_COST = 10.0  # scoring.FN_FP_COST_RATIO: a missed defect costs 10 false alarms
DECISION_THRESHOLD = 0.01
BOOTSTRAP_REPS = 1000
BOOTSTRAP_SEED = 20261003


def parts_path(name: str, out_dir: Path = OUT_DIR) -> Path:
    return out_dir / f"parts_{name}.csv.gz"


def run_config(name: str, out_dir: Path = OUT_DIR, *, seed: int | None = None) -> Path:
    """Run one configuration over the five held-out sets and save the part-level table. Skips a finished one."""
    from harness import bakeoff
    from harness import comparison as cmp
    from harness.held_out import generate_held_out_sets

    path = parts_path(name, out_dir)
    if path.exists():
        print(f"{name}: already done ({path})", flush=True)
        return path
    seed = bakeoff.HARNESS_SEED if seed is None else seed
    started = time.time()
    thresholds = bakeoff.load_harness_thresholds()
    parts = cmp.part_table(generate_held_out_sets(seed=seed), thresholds, seed=seed, **CONFIGS[name])
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    parts.to_csv(tmp, index=False, compression="gzip")
    tmp.replace(path)
    print(f"{name}: {len(parts)} parts in {time.time() - started:.0f}s", flush=True)
    return path


# --- tables ---------------------------------------------------------------------------------------------------

def headline(parts: pd.DataFrame) -> pd.DataFrame:
    from harness import comparison as cmp
    return cmp.headline_table(parts)


def cost_vector(parts: pd.DataFrame, method: str) -> np.ndarray:
    """Per-part cost: FN_COST for a missed defect, 1 for a false alarm, 0 otherwise (over evaluable parts)."""
    judged = parts[parts[f"{method}_evaluable"].astype(bool)]
    y, f = judged["is_defective"].to_numpy(bool), judged[f"{method}_flagged"].to_numpy(bool)
    return np.where(y & ~f, FN_COST, np.where(~y & f, 1.0, 0.0))


def paired_cost_difference(a: pd.DataFrame, b: pd.DataFrame, method: str, *, reps: int = BOOTSTRAP_REPS,
                           seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    """mean(cost_a - cost_b) per part for `method` on the same parts, and a 95% CI from resampling LOTS."""
    key = ["lot_id", "component_id"]
    a = a.sort_values(key).reset_index(drop=True)
    b = b.sort_values(key).reset_index(drop=True)
    if not a[key].equals(b[key]):
        raise ValueError("the two configurations scored different parts")
    diff = cost_vector(a, method) - cost_vector(b, method)
    codes, uniques = pd.factorize(a["lot_id"].to_numpy())
    sums = np.bincount(codes, weights=diff, minlength=len(uniques))
    counts = np.bincount(codes, minlength=len(uniques)).astype(float)
    idx = np.random.default_rng(seed).integers(0, len(uniques), size=(reps, len(uniques)))
    boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return float(diff.mean()), float(lo), float(hi)


def per_family_cost_difference(published: pd.DataFrame, live: pd.DataFrame) -> pd.DataFrame:
    """Cost per part, published minus live, per held-out family and overall, for Module A REVIEW and REJECT."""
    rows = []
    for family, pub_f in [*published.groupby("family", sort=True), ("ALL", published)]:
        live_f = live if family == "ALL" else live[live["family"] == family]
        for method in MODULE_A:
            mean, lo, hi = paired_cost_difference(pub_f, live_f, method)
            h_pub, h_live = headline(pub_f).set_index("method"), headline(live_f).set_index("method")
            rows.append({"family": family, "method": method, "n_parts": len(pub_f),
                         "cost_published": h_pub.loc[method, "cost_per_part"],
                         "cost_live": h_live.loc[method, "cost_per_part"],
                         "cost_published_minus_live": mean, "ci_lo": lo, "ci_hi": hi,
                         "recall_published": h_pub.loc[method, "recall"], "recall_live": h_live.loc[method, "recall"],
                         "flag_rate_published": h_pub.loc[method, "flag_rate"],
                         "flag_rate_live": h_live.loc[method, "flag_rate"]})
    return pd.DataFrame(rows)


def decision(per_family: pd.DataFrame, threshold: float = DECISION_THRESHOLD) -> dict:
    """The pre-registered M3 decision rule: |published - live| cost per part below `threshold` at BOTH REVIEW and
    REJECT (overall) means 'no material difference', otherwise 'the Isolation Forest matters'."""
    overall = per_family[per_family["family"] == "ALL"].set_index("method")
    diffs = {m: float(overall.loc[m, "cost_published_minus_live"]) for m in MODULE_A}
    immaterial = all(abs(d) < threshold for d in diffs.values())
    return {"cost_published_minus_live": diffs, "threshold": threshold,
            "verdict": "no material difference" if immaterial else "the Isolation Forest matters"}


def report(out_dir: Path = OUT_DIR) -> str:
    from harness.comparison import _md

    runs = {n: pd.read_csv(parts_path(n, out_dir)) for n in CONFIGS if parts_path(n, out_dir).exists()}
    lines = []
    for name, parts in runs.items():
        h = headline(parts)
        h.to_csv(out_dir / f"headline_{name}.csv", index=False)
        lines.append(f"### {name}\n\n" + _md(h.round(3)))
    if {"published", "live"} <= runs.keys():
        pf = per_family_cost_difference(runs["published"], runs["live"])
        pf.to_csv(out_dir / "per_family_published_minus_live.csv", index=False)
        lines.append("### cost per part, published minus live\n\n" + _md(pf.round(4)))
        d = decision(pf)
        (out_dir / "decision.json").write_text(__import__("json").dumps(d, indent=2), encoding="utf-8")
        lines.append(f"### M3 decision\n\n{d}")
    return "\n\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--config", choices=sorted(CONFIGS), required=True)
    sub.add_parser("report")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        run_config(args.config)
    else:
        print(report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
