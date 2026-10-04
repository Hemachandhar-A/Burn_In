"""M1 evidence: do the benchmark conclusions survive different generator assumptions? One setting at a time
around the baseline family, everything else at its default; thresholds stay at their shipped values; nothing
is re-tuned. Module A runs in the LIVE configuration (no pooled reference) by default, optionally also the
published one.

    PYTHONPATH=. uv run python -m scripts.sensitivity run --setting noise_x2 [--config live]   # one setting, resumable
    PYTHONPATH=. uv run python -m scripts.sensitivity report [--config live]                    # tables + claims C1-C4

Every setting uses the SAME number of lots (LOTS_PER_SETTING) with the SAME lot ids and seed, so settings are
common-random-number twins where the generator allows it and the contrasts are less noisy. Held-out sets
here are fixed-size (not the archetype-minimum sets of harness.held_out), because the archetype minimum would
give each setting a different number of lots. Static PAT's reference population stays the nominal baseline
process, as in the published benchmark (harness.comparison.PAT_REFERENCE_FAMILY).
Plan and claims: docs/EVIDENCE_PLAN.md (M5).
"""
import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path("docs/evidence_data/sensitivity")
LOTS_PER_SETTING = 150
LOT_SEED = 5101
PART_NUMBER = "PN-SENS"
ACCOUNT_ID = "m1.sensitivity"
BOOTSTRAP_REPS = 1000
BOOTSTRAP_SEED = 20261003
METHODS = ("static_limits", "fixed_delta", "static_pat", "dynamic_pat", "module_a_review", "module_a_reject")
MODULE_A = ("module_a_review", "module_a_reject")
CONFIGS = {"live": {"pooled_reference": False, "max_history": None},
           "published": {"pooled_reference": True, "max_history": None}}
FN_COST = 10.0
BASELINE_NAME = "baseline"


@dataclass(frozen=True)
class Setting:
    name: str
    dimension: str
    label: str
    noise_scale: float = 1.0
    prevalence: tuple[float, float] | None = None
    exponent_range: tuple[float, float] | None = None
    n_parts: int | None = None


SETTINGS: dict[str, Setting] = {s.name: s for s in (
    Setting("baseline", "baseline", "baseline (all defaults)"),
    Setting("noise_x0.5", "noise", "measurement + tester noise x0.5", noise_scale=0.5),
    Setting("noise_x2", "noise", "measurement + tester noise x2", noise_scale=2.0),
    Setting("prev_1", "prevalence", "defect prevalence 1%", prevalence=(0.01, 0.01)),
    Setting("prev_3", "prevalence", "defect prevalence 3%", prevalence=(0.03, 0.03)),
    Setting("prev_8", "prevalence", "defect prevalence 8%", prevalence=(0.08, 0.08)),
    Setting("exp_low", "drift exponent", "healthy drift exponent in [0.10, 0.20]", exponent_range=(0.10, 0.20)),
    Setting("exp_high", "drift exponent", "healthy drift exponent in [0.25, 0.40]", exponent_range=(0.25, 0.40)),
    Setting("lot_30", "lot size", "30 parts per lot", n_parts=30),
    Setting("lot_150", "lot size", "150 parts per lot", n_parts=150),
)}


def make_family(setting: Setting):
    """A GeneratorFamily for `setting`, built only from the generator's own config objects (no generator code
    changed). The baseline setting is the registered baseline family itself."""
    from contracts import ScreeningConfig
    from generator.families import FAMILIES, GeneratorFamily
    from generator.measurement import MeasurementParams
    from generator.trajectories import TrajectoryParams

    if setting.name == BASELINE_NAME:
        return FAMILIES["baseline"]
    base_cfg, base_meas = ScreeningConfig(), MeasurementParams()
    cfg = ScreeningConfig(
        defect_prevalence_range=setting.prevalence or base_cfg.defect_prevalence_range,
        power_law_exponent_range=setting.exponent_range or base_cfg.power_law_exponent_range)
    meas = MeasurementParams(
        noise_frac={k: setting.noise_scale * v for k, v in base_meas.noise_frac.items()},
        tester_offset_sigma={k: setting.noise_scale * v for k, v in base_meas.tester_offset_sigma.items()})
    return GeneratorFamily(name=f"sens_{setting.name}", description=f"Sensitivity setting: {setting.label}.",
                           config=cfg, trajectory_params=TrajectoryParams(), measurement_params=meas)


class LotSet:
    """The three things harness.scoring / harness.comparison read from a held-out set - the lots, their
    labels and a family name - without HeldOutTestSet's archetype-minimum guarantee."""

    def __init__(self, family: str, lots):
        self.family, self.lots = family, tuple(lots)

    def labels(self) -> pd.DataFrame:
        from harness.held_out import ground_truth_labels
        return pd.concat([ground_truth_labels(lot) for lot in self.lots], ignore_index=True)


def generate_lots(setting: Setting, n_lots: int = LOTS_PER_SETTING, seed: int = LOT_SEED) -> LotSet:
    from generator.lot import generate_lot
    family = make_family(setting)
    lots = [generate_lot(f"SENS-{i:04d}", PART_NUMBER, seed, account_id=ACCOUNT_ID, family=family,
                         n_parts=setting.n_parts) for i in range(n_lots)]
    return LotSet(family.name, lots)


def result_path(name: str, config: str, out_dir: Path = OUT_DIR) -> Path:
    return out_dir / f"{name}__{config}.json"


def run_setting(name: str, config: str = "live", out_dir: Path = OUT_DIR, *, n_lots: int = LOTS_PER_SETTING) -> Path:
    """One setting: generate, score every method, save the summary (with CIs) and the part-level table.
    Skips a setting whose result already exists."""
    from harness import bakeoff
    from harness import comparison as cmp

    path = result_path(name, config, out_dir)
    if path.exists():
        print(f"{name}/{config}: already done", flush=True)
        return path
    started = time.time()
    setting = SETTINGS[name]
    lots = generate_lots(setting, n_lots)
    parts = cmp.part_table({lots.family: lots}, bakeoff.load_harness_thresholds(), seed=bakeoff.HARNESS_SEED,
                           **CONFIGS[config])
    out_dir.mkdir(parents=True, exist_ok=True)
    parts.to_csv(out_dir / f"parts_{name}__{config}.csv.gz", index=False, compression="gzip")
    rows = method_metrics(parts)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"setting": name, "config": config, "label": setting.label, "lots": n_lots,
                               "parts": len(parts), "defective": int(parts["is_defective"].sum()),
                               "seconds": round(time.time() - started), "methods": rows}, indent=2), encoding="utf-8")
    tmp.replace(path)
    print(f"{name}/{config}: {len(parts)} parts, {int(parts['is_defective'].sum())} defective, "
          f"{time.time() - started:.0f}s", flush=True)
    return path


# --- metrics with lot-bootstrap CIs ---------------------------------------------------------------------------

def _ratio(num, den):
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den, np.nan)


def method_metrics(parts: pd.DataFrame, *, reps: int = BOOTSTRAP_REPS, seed: int = BOOTSTRAP_SEED,
                   methods: tuple[str, ...] = METHODS) -> list[dict]:
    """recall, precision, flag rate and cost per part for every method, each with a 95% percentile CI from
    resampling whole lots. Metrics are over the parts a method could judge (the benchmark's own convention)."""
    rows = []
    for method in methods:
        judged = parts[parts[f"{method}_evaluable"].astype(bool)]
        y = judged["is_defective"].to_numpy(bool)
        f = judged[f"{method}_flagged"].to_numpy(bool)
        codes, uniques = pd.factorize(judged["lot_id"].to_numpy())
        n_lots = len(uniques)

        def per_lot(mask):
            return np.bincount(codes, weights=mask.astype(float), minlength=n_lots)

        tp, fp, fn, n = per_lot(y & f), per_lot(~y & f), per_lot(y & ~f), per_lot(np.ones_like(y))

        def metrics(tp, fp, fn, n):
            return {"recall": _ratio(tp, tp + fn), "precision": _ratio(tp, tp + fp), "flag_rate": (tp + fp) / n,
                    "cost_per_part": (FN_COST * fn + fp) / n}

        point = {k: float(v) for k, v in metrics(tp.sum(), fp.sum(), fn.sum(), n.sum()).items()}
        idx = np.random.default_rng(seed).integers(0, n_lots, size=(reps, n_lots))
        boot = metrics(tp[idx].sum(1), fp[idx].sum(1), fn[idx].sum(1), n[idx].sum(1))
        row = {"method": method, "n_parts": int(n.sum()), "n_defective": int(y.sum()), "n_flagged": int(f.sum())}
        for k, v in point.items():
            lo, hi = np.nanpercentile(boot[k], [2.5, 97.5]) if np.isfinite(boot[k]).any() else (np.nan, np.nan)
            row.update({k: v, f"{k}_ci_lo": float(lo), f"{k}_ci_hi": float(hi)})
        rows.append(row)
    return rows


# --- session I2c: the same sweep with Module A in absolute mode (V1F) ------------------------------------------------
# Same lots, seed and ids as the rank sweep above (so the baselines and the current-scoring columns are read from the
# existing parts files rather than recomputed - Module A's default path is unchanged), plus: V1F REVIEW / REJECT at the
# fixed thresholds of module_a/settings.py (never re-tuned here) and each baseline with its cut cost-tuned on seed 6101
# (scripts/v1f_baselines.py tune). docs/ADOPTION_PLAN_ADDENDUM.md.
ABS_OUT_DIR = Path("docs/evidence_data/adoption/v1f/sweep")
TUNED_THRESHOLDS_PATH = Path("docs/evidence_data/adoption/v1f/baseline_tuned_thresholds.json")
TUNABLE_BASELINES = ("static_limits", "fixed_delta", "static_pat", "dynamic_pat")
ABSOLUTE_METHODS = ("absolute_review", "absolute_reject")
TUNED_METHODS = tuple(f"{b}_tuned" for b in TUNABLE_BASELINES)


def add_tuned_baseline_columns(parts: pd.DataFrame, taus: dict[str, float]) -> pd.DataFrame:
    """`<b>_tuned_flagged` = evaluable and score >= tau (the cost-tuned cut); `<b>_tuned_evaluable` = `<b>_evaluable`."""
    parts = parts.copy()
    for b, tau in taus.items():
        ev = parts[f"{b}_evaluable"].astype(bool)
        parts[f"{b}_tuned_evaluable"] = ev
        parts[f"{b}_tuned_flagged"] = ev & (parts[f"{b}_score"].fillna(-np.inf) >= tau)
    return parts


def add_absolute_columns(parts: pd.DataFrame, lots: "LotSet") -> pd.DataFrame:
    """V1F part scores s (max over the part's frames) and the REVIEW / REJECT flags, Module A in the live configuration."""
    from harness import scoring as hs
    from module_a.scoring import ScoringConfig
    from module_a.settings import ABSOLUTE_REJECT_THRESHOLD, ABSOLUTE_REVIEW_THRESHOLD, MCD_MIN_PARTS_ABSOLUTE

    cfg = ScoringConfig(calibration="absolute", combination="max", review_threshold=ABSOLUTE_REVIEW_THRESHOLD,
                        reject_threshold=ABSOLUTE_REJECT_THRESHOLD, mcd_min_parts=MCD_MIN_PARTS_ABSOLUTE)
    scores = hs.variant_part_scores(hs.run_module_a(lots, scoring=cfg)).rename(columns={"score": "absolute_score"})
    out = parts.merge(scores, on=["lot_id", "component_id"], how="left", validate="one_to_one")
    if out["absolute_score"].isna().any():
        raise ValueError("unscored parts in the absolute sweep")
    out["absolute_review_flagged"] = out["absolute_score"] >= ABSOLUTE_REVIEW_THRESHOLD
    out["absolute_reject_flagged"] = out["absolute_score"] >= ABSOLUTE_REJECT_THRESHOLD
    for m in ABSOLUTE_METHODS:
        out[f"{m}_evaluable"] = True
    return out


def run_setting_absolute(name: str, config: str = "live", out_dir: Path = ABS_OUT_DIR, *,
                         n_lots: int = LOTS_PER_SETTING, rank_dir: Path = OUT_DIR) -> Path:
    """One setting with V1F added. Resumable (skips a finished setting)."""
    path = result_path(name, f"{config}_absolute", out_dir)
    if path.exists():
        print(f"{name}/{config}/absolute: already done", flush=True)
        return path
    started = time.time()
    setting = SETTINGS[name]
    lots = generate_lots(setting, n_lots)
    rank_parts = rank_dir / f"parts_{name}__{config}.csv.gz"
    if rank_parts.exists():
        parts = pd.read_csv(rank_parts)
        for m in METHODS:
            parts[f"{m}_flagged"] = parts[f"{m}_flagged"].fillna(False).astype(bool)
            parts[f"{m}_evaluable"] = parts[f"{m}_evaluable"].fillna(False).astype(bool)
    else:
        from harness import bakeoff
        from harness import comparison as cmp
        parts = cmp.part_table({lots.family: lots}, bakeoff.load_harness_thresholds(), seed=bakeoff.HARNESS_SEED,
                               **CONFIGS[config])
    parts = add_absolute_columns(parts, lots)
    methods = METHODS + ABSOLUTE_METHODS
    if TUNED_THRESHOLDS_PATH.exists():
        taus = {b: v["tau"] for b, v in json.loads(TUNED_THRESHOLDS_PATH.read_text(encoding="utf-8")).items()}
        parts = add_tuned_baseline_columns(parts, taus)
        methods = methods + TUNED_METHODS
    out_dir.mkdir(parents=True, exist_ok=True)
    parts.to_csv(out_dir / f"parts_{name}__{config}_absolute.csv.gz", index=False, compression="gzip")
    rows = method_metrics(parts, methods=methods)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"setting": name, "config": config, "scoring": "absolute (V1F)", "label": setting.label,
                               "lots": n_lots, "parts": len(parts), "defective": int(parts["is_defective"].sum()),
                               "seconds": round(time.time() - started), "methods": rows}, indent=2), encoding="utf-8")
    tmp.replace(path)
    print(f"{name}/{config}/absolute: {len(parts)} parts, {int(parts['is_defective'].sum())} defective, "
          f"{time.time() - started:.0f}s", flush=True)
    return path


def evaluate_claims_absolute(summary: pd.DataFrame, *, clean_flag_rate_noise_x2: float | None) -> dict:
    """Claims C1, C2, C5, C6, C7 of docs/ADOPTION_PLAN.md at point estimates over every setting present, for V1F at REVIEW
    and at REJECT. C6 takes the flag rate on the clean (zero-defect) lots at noise x2, computed from the parts file."""
    out: dict = {}
    for tier in ABSOLUTE_METHODS:
        recall_a, cost_a = _by(summary, "recall", tier), _by(summary, "cost_per_part", tier)
        c1 = sorted({s for b in ("static_limits", "static_pat", "dynamic_pat") for s in recall_a.index
                     if not recall_a[s] > _by(summary, "recall", b)[s]})
        c2 = [s for s in cost_a.index if not cost_a[s] < _by(summary, "cost_per_part", "static_limits")[s]]
        flag = _by(summary, "flag_rate", tier)
        cost_cur = _by(summary, "cost_per_part", "module_a_review")
        c7 = [s for s in cost_a.index if not (cost_a[s] - cost_cur[s]) <= 0.03]
        out[tier] = {
            "C1_recall_exceeds_static_limits_static_pat_dynamic_pat": {"holds": not c1, "breaks": c1},
            "C2_cost_beats_static_limits": {"holds": not c2, "breaks": c2},
            "C5_flag_rate_le_6pct_at_1pct_prevalence": {
                "holds": bool("prev_1" in flag.index and flag["prev_1"] <= 0.06),
                "value": float(flag["prev_1"]) if "prev_1" in flag.index else None},
            "C6_flag_rate_le_8pct_on_clean_lots_at_noise_x2": {
                "holds": bool(clean_flag_rate_noise_x2 is not None and clean_flag_rate_noise_x2 <= 0.08),
                "value": clean_flag_rate_noise_x2},
            "C7_cost_no_worse_than_current_by_more_than_0.03": {
                "holds": not c7, "breaks": c7,
                "difference_absolute_minus_current": {s: float(cost_a[s] - cost_cur[s]) for s in cost_a.index}},
        }
    return out


def load_summary(config: str, out_dir: Path = OUT_DIR) -> pd.DataFrame:
    rows = []
    for name in SETTINGS:
        path = result_path(name, config, out_dir)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data["methods"]:
            rows.append({"setting": name, "dimension": SETTINGS[name].dimension, "label": data["label"],
                         "lots": data["lots"], "parts": data["parts"], "defective": data["defective"], **r})
    return pd.DataFrame(rows)


def cost_ranking(summary: pd.DataFrame) -> pd.DataFrame:
    """Per setting: methods ordered by cost per part (lowest first), as 'a < b < c'."""
    rows = []
    for setting, g in summary.groupby("setting", sort=False):
        order = g.sort_values(["cost_per_part", "method"])["method"].tolist()
        rows.append({"setting": setting, "rank_by_cost": " < ".join(order)})
    return pd.DataFrame(rows)


def _by(summary: pd.DataFrame, metric: str, method: str) -> pd.Series:
    return summary[summary["method"] == method].set_index("setting")[metric]


def evaluate_claims(summary: pd.DataFrame) -> dict:
    """The pre-registered claims C1-C4 (docs/EVIDENCE_PLAN.md, M5), at point estimates over every setting
    present. Module A is evaluated at its REVIEW and REJECT operating points; a claim 'holds' for one only
    if no setting breaks it."""
    claims: dict = {}
    baselines = ("static_limits", "static_pat", "dynamic_pat")
    for tier in MODULE_A:
        recall_a = _by(summary, "recall", tier)
        c1_breaks = sorted({s for b in baselines for s in recall_a.index
                            if not recall_a[s] > _by(summary, "recall", b)[s]})
        cost_a, cost_static = _by(summary, "cost_per_part", tier), _by(summary, "cost_per_part", "static_limits")
        c2_breaks = [s for s in cost_a.index if not cost_a[s] < cost_static[s]]
        claims[tier] = {
            "C1_recall_exceeds_static_limits_static_pat_dynamic_pat": {"holds": not c1_breaks, "breaks": c1_breaks},
            "C2_cost_beats_static_limits": {"holds": not c2_breaks, "breaks": c2_breaks}}
        flag = _by(summary, "flag_rate", tier)
        claims[tier]["C3_flag_rate_at_least_10pct_at_1pct_prevalence"] = {
            "holds": bool("prev_1" in flag.index and flag["prev_1"] >= 0.10),
            "flag_rate_at_prev_1": float(flag["prev_1"]) if "prev_1" in flag.index else None,
            "flag_rate_all_settings": {s: float(v) for s, v in flag.items()}}
    prec = _by(summary, "precision", "dynamic_pat")
    c4_breaks = [s for s in prec.index if not prec[s] > 0.9]
    claims["C4_dynamic_pat_precision_above_0.9"] = {"holds": not c4_breaks, "breaks": c4_breaks,
                                                    "precision": {s: float(v) for s, v in prec.items()}}
    return claims


def report(config: str = "live", out_dir: Path = OUT_DIR) -> str:
    from harness.comparison import _md
    summary = load_summary(config, out_dir)
    if summary.empty:
        return "no results yet"
    summary.to_csv(out_dir / f"summary__{config}.csv", index=False)
    claims = evaluate_claims(summary)
    (out_dir / f"claims__{config}.json").write_text(json.dumps(claims, indent=2), encoding="utf-8")
    ranking = cost_ranking(summary)
    ranking.to_csv(out_dir / f"cost_ranking__{config}.csv", index=False)
    show = summary.copy()
    for m in ("recall", "precision", "flag_rate", "cost_per_part"):
        show[m] = (show[m].map("{:.3f}".format) + " [" + show[f"{m}_ci_lo"].map("{:.3f}".format) + ", "
                   + show[f"{m}_ci_hi"].map("{:.3f}".format) + "]")
    table = show[["setting", "method", "n_defective", "recall", "precision", "flag_rate", "cost_per_part"]]
    return (f"## sensitivity ({config} configuration)\n\n{_md(table)}\n\n## cost ranking\n\n{_md(ranking)}\n\n"
            f"## claims\n\n{json.dumps(claims, indent=2)}")


def report_absolute(config: str = "live", out_dir: Path = ABS_OUT_DIR) -> str:
    """Tables and the registered claims for the V1F sweep. C6's flag rate is read from the noise x2 parts file: the lots with
    no defective part (the 'clean' lots); the flag rate on all healthy parts of that setting is reported beside it."""
    from harness.comparison import _md

    summary = load_summary(f"{config}_absolute", out_dir)
    if summary.empty:
        return "no results yet"
    summary.to_csv(out_dir / f"summary__{config}_absolute.csv", index=False)
    clean = healthy = None
    parts_file = out_dir / f"parts_noise_x2__{config}_absolute.csv.gz"
    extra = {}
    if parts_file.exists():
        parts = pd.read_csv(parts_file)
        defects = parts.groupby("lot_id")["is_defective"].transform("sum")
        zero = parts[defects == 0]
        clean = float(zero["absolute_review_flagged"].mean()) if len(zero) else None
        healthy = float(parts.loc[~parts["is_defective"].astype(bool), "absolute_review_flagged"].mean())
        extra = {"noise_x2_zero_defect_lots": int(zero["lot_id"].nunique()), "noise_x2_zero_defect_parts": int(len(zero)),
                 "noise_x2_healthy_part_flag_rate_review": healthy}
    claims = evaluate_claims_absolute(summary, clean_flag_rate_noise_x2=clean)
    claims["_context"] = extra
    (out_dir / f"claims__{config}_absolute.json").write_text(json.dumps(claims, indent=2), encoding="utf-8")
    show = summary.copy()
    for m in ("recall", "precision", "flag_rate", "cost_per_part"):
        show[m] = (show[m].map("{:.3f}".format) + " [" + show[f"{m}_ci_lo"].map("{:.3f}".format) + ", "
                   + show[f"{m}_ci_hi"].map("{:.3f}".format) + "]")
    table = show[["setting", "method", "n_defective", "recall", "precision", "flag_rate", "cost_per_part"]]
    return (f"## sensitivity, V1F ({config} configuration)" + chr(10)*2 + _md(table) + chr(10)*2 + "## claims" + chr(10)*2
            + json.dumps(claims, indent=2))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--setting", choices=sorted(SETTINGS), required=True)
    run.add_argument("--config", choices=sorted(CONFIGS), default="live")
    rep = sub.add_parser("report")
    rep.add_argument("--config", choices=sorted(CONFIGS), default="live")
    runa = sub.add_parser("run-absolute", help="session I2c: add V1F and the cost-tuned baselines to a setting")
    runa.add_argument("--setting", choices=sorted(SETTINGS), nargs="+", required=True)
    sub.add_parser("report-absolute")
    args = parser.parse_args(argv)
    if args.cmd == "run-absolute":
        for name in args.setting:
            run_setting_absolute(name)
    elif args.cmd == "report-absolute":
        print(report_absolute())
    elif args.cmd == "run":
        run_setting(args.setting, args.config)
    else:
        print(report(args.config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
