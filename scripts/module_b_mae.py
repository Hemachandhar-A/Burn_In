"""M1 evidence: Module B's drift-prediction error (MAE of predicted 168h against the true 168h) against
naive baselines, on complete synthetic lots Module B never trained on. Measurement only - it calls
module_b.predict exactly as fusion does and changes nothing.

    PYTHONPATH=. uv run python -m scripts.module_b_mae [--lots 40] [--seed 7001] [--out docs/evidence_data]

Plan and pass criterion: docs/EVIDENCE_PLAN.md (pre-registered). Method and verdict: docs/EVIDENCE_MEASUREMENTS.md.

Leakage control (the thing to check first): module_b.predictor.synthetic_models(part_number) trains on
SYNTHETIC_LOTS complete baseline-family lots with lot ids `SYNTHETIC-<pn>-<seed:03d>` and seeds 0..13. Each
lot's draws come from SeedSequence([seed, hash(lot_id), hash(part_number)]) (generator.lot._lot_seed). The
evaluation lots here use seed 7001, lot ids `M1-<family>-<index>` and the part number PN-M1, so both the
(seed, lot id) pair and the derived lot seed are different from every training lot; `assert_disjoint_from_
training` checks that explicitly and the run aborts if it ever fails.
"""
import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

PART_NUMBER = "PN-M1"
ACCOUNT_ID = "m1.evidence"
LOT_PREFIX = "M1"
DEFAULT_LOTS = 40
DEFAULT_SEED = 7001
BOOTSTRAP_SEED = 20261003
BOOTSTRAP_REPS = 1000
FIXED_EXPONENT = 0.22  # literature median NBTI-type drift exponent; inside the 0.15-0.30 spread cited in context.md 1.4
PARAMETERS = ("iddq", "leakage", "prop_delay")
UNITS = {"iddq": "uA", "leakage": "nA", "prop_delay": "ns"}
MODES = ("24h", "96h")
BASELINES = ("persistence", "linear", "fixed_power_law", "lot_median_drift", "lot_fitted_power_law")
NAIVE_BRIEF = BASELINES[:4]  # the four baselines of the session brief; the fifth is the app's own comparator
METHODS = ("model", *BASELINES)
DEFAULT_OUT = Path("docs/evidence_data")


# --- baselines ----------------------------------------------------------------------------------------------

def _latest(frame) -> tuple[float, float]:
    """(elapsed hours, value) of the latest reading the mode allows: 96h when present, else 24h."""
    if frame.value_96h is not None:
        return frame.elapsed_hours["96h"], frame.value_96h
    return frame.elapsed_hours["24h"], frame.value_24h


def horizon_ratio(frame) -> float:
    """(168 - t0) / (t_last - t0)."""
    t0 = frame.elapsed_hours["0h"]
    return (168.0 - t0) / (_latest(frame)[0] - t0)


def persistence_168h(frame) -> float:
    """(a) 168h = the latest reading (the 24h value in the 0h+24h mode)."""
    return _latest(frame)[1]


def linear_168h(frame) -> float:
    """(b) straight line through the 0h and latest readings, extended to 168h."""
    v0 = frame.value_0h
    return v0 + (_latest(frame)[1] - v0) * horizon_ratio(frame)


def fixed_power_law_168h(frame, exponent: float = FIXED_EXPONENT) -> float:
    """(c) v0 + (v_last - v0) * ratio ** n with the fixed literature exponent n = 0.22."""
    v0 = frame.value_0h
    return v0 + (_latest(frame)[1] - v0) * horizon_ratio(frame) ** exponent


def lot_median_drift_168h(frames: Sequence, exponent: float = FIXED_EXPONENT) -> dict[tuple[str, str, str], float]:
    """(d) Lot-median relative drift: per (lot, parameter) m = median over the lot's parts of
    (v_last - v0) / v0; each part is then predicted as v0 * (1 + m * ratio ** n), n fixed at 0.22. It pools
    the whole lot's drift so one part's measurement noise does not enter its own prediction, and ignores the
    part's own drift - a healthy-lot assumption, which is why a defect is its weak case."""
    by_group: dict[tuple[str, str], list[float]] = {}
    for f in frames:
        by_group.setdefault((f.lot_id, f.parameter), []).append((_latest(f)[1] - f.value_0h) / f.value_0h)
    medians = {k: float(np.median(v)) for k, v in by_group.items()}
    return {(f.lot_id, f.component_id, f.parameter):
            f.value_0h * (1.0 + medians[(f.lot_id, f.parameter)] * horizon_ratio(f) ** exponent) for f in frames}


# --- metrics --------------------------------------------------------------------------------------------------

def abs_error(pred, actual) -> np.ndarray:
    return np.abs(np.asarray(pred, dtype=float) - np.asarray(actual, dtype=float))


def rel_error(pred, actual) -> np.ndarray:
    """|pred - actual| / |actual|."""
    actual = np.asarray(actual, dtype=float)
    return abs_error(pred, actual) / np.abs(actual)


def cluster_bootstrap_mean(values, lot_ids, *, reps: int = BOOTSTRAP_REPS, seed: int = BOOTSTRAP_SEED
                           ) -> tuple[float, float, float]:
    """(mean, lo, hi): the mean of `values` and its 95% percentile CI from resampling whole LOTS with
    replacement (parts within a lot are not independent draws)."""
    values = np.asarray(values, dtype=float)
    codes, uniques = pd.factorize(np.asarray(lot_ids))
    n_lots = len(uniques)
    sums = np.bincount(codes, weights=values, minlength=n_lots)
    counts = np.bincount(codes, minlength=n_lots).astype(float)
    mean = float(values.mean())
    if n_lots < 2:
        return mean, mean, mean
    idx = np.random.default_rng(seed).integers(0, n_lots, size=(reps, n_lots))
    boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return mean, float(lo), float(hi)


def _summarize_group(g: pd.DataFrame, *, reps: int) -> list[dict]:
    rows = []
    actual = g["measured_168h"].to_numpy(float)
    truth = g["true_168h"].to_numpy(float)
    lots = g["lot_id"].to_numpy()
    for method in METHODS:
        pred = g[f"pred_{method}"].to_numpy(float)
        ae, re = abs_error(pred, actual), rel_error(pred, actual)
        mae, mae_lo, mae_hi = cluster_bootstrap_mean(ae, lots, reps=reps)
        rel, rel_lo, rel_hi = cluster_bootstrap_mean(100.0 * re, lots, reps=reps)
        defective = g["is_defective"].to_numpy(bool)
        row = {"method": method, "n": len(g),
               "mae": mae, "mae_ci_lo": mae_lo, "mae_ci_hi": mae_hi,
               "rel_mae_pct": rel, "rel_ci_lo": rel_lo, "rel_ci_hi": rel_hi,
               "mae_vs_true_168h": float(abs_error(pred, truth).mean()),
               "mae_healthy": float(ae[~defective].mean()) if (~defective).any() else np.nan,
               "mae_defective": float(ae[defective].mean()) if defective.any() else np.nan,
               "rel_mae_healthy_pct": float(100 * re[~defective].mean()) if (~defective).any() else np.nan,
               "rel_mae_defective_pct": float(100 * re[defective].mean()) if defective.any() else np.nan}
        if method == "model":
            inside = (actual >= g["interval_lower"].to_numpy(float)) & (actual <= g["interval_upper"].to_numpy(float))
            row["coverage"] = float(inside.mean())
            row["mean_interval_width"] = float((g["interval_upper"] - g["interval_lower"]).mean())
        rows.append(row)
    return rows


def summarize(raw: pd.DataFrame, *, reps: int = BOOTSTRAP_REPS) -> pd.DataFrame:
    """Summary rows per (family, parameter, mode, method) plus pooled rows: parameter == 'ALL' pools the
    three parameters (relative metrics only are meaningful there), family == 'ALL' pools families, and
    family == 'ALL_HELD_OUT' pools the four non-baseline families. Only rows the model forecast are scored,
    for every method alike, so each comparison is on identical parts."""
    raw = raw[~raw["forecast_unavailable"].astype(bool)]
    held_out = raw[raw["family"] != "baseline"]
    family_views: list[tuple[str, pd.DataFrame]] = [(fam, g) for fam, g in raw.groupby("family", sort=True)]
    family_views += [("ALL_HELD_OUT", held_out), ("ALL", raw)]
    rows = []
    for family, fam_df in family_views:
        for mode, mode_df in fam_df.groupby("mode", sort=True):
            views = [(p, g) for p, g in mode_df.groupby("parameter", sort=True)] + [("ALL", mode_df)]
            for parameter, g in views:
                for row in _summarize_group(g, reps=reps):
                    rows.append({"family": family, "parameter": parameter,
                                 "unit": UNITS.get(parameter, "relative only"), "mode": mode, **row})
    return pd.DataFrame(rows)


def verdict(summary: pd.DataFrame) -> dict:
    """The pre-registered M1 verdict (docs/EVIDENCE_PLAN.md, operationalisation 3-5), judged on the 0h+24h
    mode with parameter == 'ALL' pooled relative MAE. Reported for both the strict comparator set (a)-(e)
    and the brief's (a)-(d)."""
    s = summary[(summary["parameter"] == "ALL") & (summary["mode"] == "24h")]
    out: dict = {}
    for label, candidates in (("strict_a_to_e", BASELINES), ("brief_a_to_d", NAIVE_BRIEF)):
        def rel(family: str, method: str) -> float:
            return float(s[(s["family"] == family) & (s["method"] == method)]["rel_mae_pct"].iloc[0])
        pooled_family = "ALL"
        best = min(candidates, key=lambda b: rel(pooled_family, b))
        model_rel, best_rel = rel(pooled_family, "model"), rel(pooled_family, best)
        held_out = {}
        for fam in sorted(set(s["family"]) - {"ALL", "ALL_HELD_OUT", "baseline"}):
            fam_best = min(candidates, key=lambda b, fam=fam: rel(fam, b))
            m, b = rel(fam, "model"), rel(fam, fam_best)
            held_out[fam] = {"best_baseline": fam_best, "model_rel_mae_pct": m, "best_rel_mae_pct": b,
                             "ratio": m / b, "loses_by_more_than_10pct": bool(m > 1.10 * b)}
        beats = bool(model_rel <= 0.90 * best_rel)
        no_big_loss = not any(v["loses_by_more_than_10pct"] for v in held_out.values())
        out[label] = {"best_baseline_pooled": best, "model_rel_mae_pct": model_rel, "best_rel_mae_pct": best_rel,
                      "improvement_pct": 100.0 * (1.0 - model_rel / best_rel), "beats_by_10pct": beats,
                      "held_out": held_out, "no_held_out_loss_over_10pct": no_big_loss,
                      "M1_PASS": bool(beats and no_big_loss)}
    return out


# --- data -----------------------------------------------------------------------------------------------------

def assert_disjoint_from_training(family_names: Sequence[str], n_lots: int, seed: int, part_number: str = PART_NUMBER
                                  ) -> dict:
    """Abort unless no evaluation lot can coincide with a Module B training lot: different (seed, lot id,
    part number) triples AND different derived lot seeds. Returns what was compared, for the report."""
    from generator.lot import _lot_seed
    from module_b.predictor import SYNTHETIC_LOTS

    train = {(s, f"SYNTHETIC-{part_number}-{s:03d}") for s in range(SYNTHETIC_LOTS)}
    train_seeds = {_lot_seed(s, lot_id, part_number) for s, lot_id in train}
    evaluation = {(seed, f"{LOT_PREFIX}-{fam}-{i:04d}") for fam in family_names for i in range(n_lots)}
    eval_seeds = {_lot_seed(s, lot_id, part_number) for s, lot_id in evaluation}
    if train & evaluation or train_seeds & eval_seeds or seed in range(SYNTHETIC_LOTS):
        raise RuntimeError("Module B training lots and evaluation lots overlap - aborting (leakage)")
    return {"training_lots": len(train), "evaluation_lots": len(evaluation), "training_seeds": f"0..{SYNTHETIC_LOTS - 1}",
            "evaluation_seed": seed, "derived_lot_seed_overlap": len(train_seeds & eval_seeds)}


def score_lot(lot, family: str) -> pd.DataFrame:
    """One wide row per (part, parameter, mode): the measured and true 168h, Module B's forecast and
    interval (module_b.predict, the same call fusion makes) and every baseline's prediction."""
    import module_b
    from contracts import to_module_b_input
    from features.compute import compute
    from module_b.baselines import physics_baselines
    from module_b.model import view_at_24h

    frames = compute(lot.dataset)
    inputs = [to_module_b_input(f) for f in frames]
    measured = {(f.lot_id, f.component_id, f.parameter): f.value_168h for f in frames}
    traj = lot.ground_truth.trajectories
    idx168 = list(traj.checkpoint_hours).index(168.0)
    parts = {p.component_id: p for p in traj.parts}
    rows = []
    for mode, view in (("24h", [view_at_24h(i) for i in inputs]), ("96h", inputs)):
        results = module_b.predict(view)
        phys = physics_baselines(view)
        lot_med = lot_median_drift_168h(view)
        for inp, res in zip(view, results):
            key = (inp.lot_id, inp.component_id, inp.parameter)
            part = parts[inp.component_id]
            rows.append({
                "family": family, "lot_id": inp.lot_id, "component_id": inp.component_id, "parameter": inp.parameter,
                "mode": mode, "is_defective": bool(part.is_defective), "defect_type": part.defect_type,
                "measured_168h": measured[key], "true_168h": part.values[inp.parameter][idx168],
                "forecast_unavailable": bool(res.forecast_unavailable),
                "pred_model": res.predicted_168h if not res.forecast_unavailable else np.nan,
                "interval_lower": res.interval_lower, "interval_upper": res.interval_upper,
                "pred_persistence": persistence_168h(inp), "pred_linear": linear_168h(inp),
                "pred_fixed_power_law": fixed_power_law_168h(inp), "pred_lot_median_drift": lot_med[key],
                "pred_lot_fitted_power_law": phys[key].power_law,
            })
    return pd.DataFrame(rows)


def run_family(family: str, n_lots: int, seed: int) -> pd.DataFrame:
    from generator.lot import generate_lot
    frames = []
    for i in range(n_lots):
        lot = generate_lot(f"{LOT_PREFIX}-{family}-{i:04d}", PART_NUMBER, seed, account_id=ACCOUNT_ID, family=family)
        frames.append(score_lot(lot, family))
    return pd.concat(frames, ignore_index=True)


def main(argv: Sequence[str] | None = None) -> int:
    from generator.families import HELD_OUT_FAMILY_NAMES

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lots", type=int, default=DEFAULT_LOTS, help="lots per family")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--families", nargs="+", default=list(HELD_OUT_FAMILY_NAMES))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache", type=Path, default=Path(".evidence_logs/mae_cache"),
                        help="per-family raw results, so a crashed run resumes")
    args = parser.parse_args(argv)

    started = time.time()
    check = assert_disjoint_from_training(args.families, args.lots, args.seed)
    print("disjointness check:", check, flush=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    parts = []
    for fam in args.families:
        cached = args.cache / f"{fam}_{args.lots}_{args.seed}.csv.gz"
        if cached.exists():
            parts.append(pd.read_csv(cached))
            print(f"{fam}: reused {cached}", flush=True)
            continue
        t = time.time()
        df = run_family(fam, args.lots, args.seed)
        df.to_csv(cached, index=False)
        parts.append(df)
        print(f"{fam}: {len(df)} rows in {time.time() - t:.0f}s", flush=True)
    raw = pd.concat(parts, ignore_index=True)
    raw.to_csv(args.out / "module_b_mae_raw.csv.gz", index=False)
    summary = summarize(raw)
    summary.to_csv(args.out / "module_b_mae_summary.csv", index=False)
    import json
    (args.out / "module_b_mae_verdict.json").write_text(json.dumps(
        {"disjointness": check, "lots_per_family": args.lots, "seed": args.seed, "verdict": verdict(summary)},
        indent=2), encoding="utf-8")
    print(f"done in {time.time() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
