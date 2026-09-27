"""E5 steps 4-5 (session P1.7): score the real Module A and Module B against held-out ground truth.

Module A (step 4). Every held-out lot goes through features.compute() and then module_a's detect(), one call
per lot - the way fusion calls it - with the set's earlier lots as the Isolation Forest's pooled cross-lot
history (E2 step 3), so a set's first lot is a cold start exactly as a part number's first-ever lot is. Scores
are part-level: a part's severity is its worst parameter's (E2 step 8, context.md 6.1). Thresholds are tuned
against one locked cost function, FN:FP = ScreeningConfig.fn_fp_cost_ratio (10:1, context.md 7.12); F2 and
recall at fixed flag rates are reported for monitoring only, never tuned on.

The REJECT threshold uses FN:FP = 1:1 (REJECT_FN_FP_COST_RATIO). context.md 6.2 says both thresholds are cost-
tuned but names only the one ratio; a REJECT routes a part to dual sign-off, so its cut is the one where a
flag must be right at least as often as it is wrong. A disclosed harness judgment call, not evidence-derived.

`TEMP_detector_percentiles` is a TEMP_ stand-in for a contract gap (CONTRACT_CHANGES.md, 2026-09-27 P1):
ModuleAResult carries each detector's raw score but not the percentile-normalised, max-combined severity that
module_a compares against its thresholds (E2 steps 5 and 8). The harness therefore re-derives the percentiles
from the raw scores, mirroring module_a/detect.py step 5 exactly (rank / n within the lot over every frame,
absent MCD/IF scores as 0.0, IF sign negated); test_p17_scoring pins the mirror against module_a's own
combined score through its direction cap. Swap for the contracted field once the Lead adds it.

Module B (step 5). Each lot's frames go through contracts.to_module_b_input and the real module_b.predict(),
once per lot, at two horizons: with the 96h read (a Complete lot's full input) and as the same part looked
like at 24h (module_b.model.view_at_24h - an In-Progress lot). The actual 168h value comes from the frame's
own value_168h, never from anything Module B saw (AGENTS.md rule 6). MAE and CQR interval coverage are
compared against the three physics baselines (module_b.baselines), per family, parameter and horizon -
parameters are never pooled, since their units differ.
"""
from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.metrics import fbeta_score, precision_score, recall_score

import module_a.detect as module_a_detect
import module_b
from contracts import ModuleAResult, ScreeningConfig, to_module_b_input
from features.compute import compute
from harness.held_out import HeldOutTestSet, ground_truth_labels
from module_b.baselines import physics_baselines
from module_b.calibration import DEFAULT_CONFIDENCE_LEVEL, horizon_of
from module_b.model import view_at_24h

DETECTORS = ("robust_z", "mcd", "isolation_forest", "ecod")
REVIEW_FN_FP_COST_RATIO = ScreeningConfig().fn_fp_cost_ratio  # context.md 7.12 - the locked cost function
REJECT_FN_FP_COST_RATIO = 1.0  # disclosed judgment call - see the module docstring
FLAG_RATES = (0.01, 0.02, 0.05, 0.10, 0.20)
BASELINES = ("persistence", "linear", "power_law")
_PART_KEY = ["lot_id", "component_id"]


# --- cost function and threshold search ---------------------------------------------------------------------

def _arrays(scores, y_true) -> tuple[np.ndarray, np.ndarray]:
    scores = np.asarray(scores, dtype=float)
    y = np.asarray(y_true).astype(bool)
    if scores.ndim != 1 or scores.shape != y.shape:
        raise ValueError(f"scores {scores.shape} and labels {y.shape} must be equal-length 1-d arrays")
    if scores.size == 0:
        raise ValueError("no parts to score")
    if not np.isfinite(scores).all():
        raise ValueError("scores must be finite")
    return scores, y


def expected_cost(y_true, flagged, fn_fp_cost_ratio: float) -> float:
    """Mean cost per part: a missed defect costs `fn_fp_cost_ratio`, a false alarm costs 1."""
    y = np.asarray(y_true).astype(bool)
    flagged = np.asarray(flagged).astype(bool)
    fn = np.sum(y & ~flagged)
    fp = np.sum(~y & flagged)
    return float((fn_fp_cost_ratio * fn + fp) / y.size)


def tune_threshold(scores, y_true, fn_fp_cost_ratio: float) -> float:
    """The threshold minimising expected cost when a part is flagged at `score >= threshold`. The cut sits
    midway between the lowest flagged score and the next score below it, so it does not hinge on one exact
    training value. Equal-cost cuts resolve toward the lower threshold (more recall - context.md 6.1's
    recall-preserving stance). With nothing worth flagging, the cut sits above every score."""
    scores, y = _arrays(scores, y_true)
    order = np.argsort(-scores, kind="stable")
    s, yy = scores[order], y[order]
    distinct = np.r_[s[1:] != s[:-1], True]  # a cut can only fall after the last copy of a tied score
    tp = np.cumsum(yy)[distinct]
    fp = np.cumsum(~yy)[distinct]
    cut_scores = s[distinct]
    fn = y.sum() - tp
    costs = np.r_[fn_fp_cost_ratio * y.sum(), fn_fp_cost_ratio * fn + fp]  # index 0: flag nothing
    best = int(np.flatnonzero(costs == costs.min())[-1])  # last minimum = lowest threshold
    if best == 0:
        return float(np.nextafter(s[0], np.inf))
    lowest_flagged = cut_scores[best - 1]
    below = cut_scores[best] if best < cut_scores.size else None
    return float(lowest_flagged if below is None else (lowest_flagged + below) / 2)


def classification_metrics(y_true, flagged, fn_fp_cost_ratio: float = REVIEW_FN_FP_COST_RATIO) -> dict:
    y = np.asarray(y_true).astype(bool)
    flagged = np.asarray(flagged).astype(bool)
    return {
        "n_parts": int(y.size),
        "n_defective": int(y.sum()),
        "n_flagged": int(flagged.sum()),
        "recall": float(recall_score(y, flagged, zero_division=0)),
        "precision": float(precision_score(y, flagged, zero_division=0)),
        "f2": float(fbeta_score(y, flagged, beta=2, zero_division=0)),
        "flag_rate": float(flagged.mean()),
        "cost": expected_cost(y, flagged, fn_fp_cost_ratio),
    }


def recall_at_flag_rates(scores, y_true, rates: Iterable[float] = FLAG_RATES) -> pd.DataFrame:
    """Recall and precision when the top `rate` fraction of parts (by score) is flagged - the monitoring view
    E5 step 4 asks for alongside the cost-tuned operating point. Ties at the cut break by input order."""
    scores, y = _arrays(scores, y_true)
    order = np.argsort(-scores, kind="stable")
    rows = []
    for rate in rates:
        k = round(rate * y.size)
        flagged = np.zeros(y.size, dtype=bool)
        flagged[order[:k]] = True
        m = classification_metrics(y, flagged)
        rows.append({"flag_rate": rate, "n_flagged": k, "recall": m["recall"], "precision": m["precision"]})
    return pd.DataFrame(rows)


# --- Module A -----------------------------------------------------------------------------------------------

def TEMP_detector_percentiles(results: Sequence[ModuleAResult]) -> pd.DataFrame:
    """Frame-level percentile rank (0-1) of each detector within its lot, mirroring module_a/detect.py step 5.
    TEMP_: see the module docstring's contract gap."""
    rows = [{
        "lot_id": r.lot_id, "component_id": r.component_id, "parameter": r.parameter, "direction": r.direction,
        "robust_z": r.robust_z,
        "mcd": 0.0 if r.mcd_distance is None else r.mcd_distance,
        "isolation_forest": 0.0 if r.isolation_forest_score is None else -r.isolation_forest_score,
        "ecod": r.ecod_score,
    } for r in results]
    frame = pd.DataFrame(rows, columns=["lot_id", "component_id", "parameter", "direction", *DETECTORS])
    for idx in frame.groupby("lot_id", sort=False).groups.values():
        n = len(idx)
        for det in DETECTORS:
            raw = frame.loc[idx, det].to_numpy(dtype=float)
            frame.loc[idx, det] = np.full(n, 0.5) if n == 1 else rankdata(raw) / n
    return frame


def part_detector_scores(results: Sequence[ModuleAResult]) -> pd.DataFrame:
    """Per part, each detector's worst-parameter percentile (E2 step 8). The max over these four columns is
    exactly module_a's max-combined severity for the part."""
    pct = TEMP_detector_percentiles(results)
    return pct.groupby(_PART_KEY, sort=False)[list(DETECTORS)].max().reset_index()


def run_module_a(test_set: HeldOutTestSet) -> list[ModuleAResult]:
    """module_a's detect() once per lot, in lot order, each lot's history being every earlier lot of the set."""
    results: list[ModuleAResult] = []
    history = []
    for lot in test_set.lots:
        frames = compute(lot.dataset)
        results += module_a_detect.detect(frames, prior_frames=list(history))
        history += frames
    return results


def module_a_table(test_set: HeldOutTestSet, results: Sequence[ModuleAResult] | None = None) -> pd.DataFrame:
    """One row per part: family, ground truth and the four detectors' part-level percentiles."""
    if results is None:
        results = run_module_a(test_set)
    labels = test_set.labels()
    parts = part_detector_scores(results)
    table = labels.merge(parts, on=_PART_KEY, how="left", validate="one_to_one")
    unscored = table[list(DETECTORS)].isna().any(axis=1)
    if unscored.any():
        missing = table.loc[unscored, _PART_KEY].head(5).to_dict("records")
        raise ValueError(f"{int(unscored.sum())} held-out parts got no Module A score, e.g. {missing}")
    return table


def evaluate_module_a(table: pd.DataFrame, scores, threshold: float) -> dict:
    """Operating-point metrics at `threshold`, per family and per defect archetype, plus the fixed-flag-rate
    monitoring view."""
    scores = np.asarray(scores, dtype=float)
    y = table["is_defective"].to_numpy(bool)
    flagged = scores >= threshold
    by_family = {fam: classification_metrics(y[idx], flagged[idx])
                 for fam, idx in table.groupby("family", sort=True).indices.items()}
    by_archetype = {arch: {"n": int(idx.size), "recall": float(flagged[idx].mean())}  # healthy rows: no type
                    for arch, idx in table.groupby("defect_type", sort=True).indices.items()}
    return {
        "threshold": float(threshold),
        "overall": classification_metrics(y, flagged),
        "by_family": by_family,
        "by_archetype": by_archetype,
        "recall_at_flag_rates": recall_at_flag_rates(scores, y).to_dict("records"),
    }


# --- Module B -----------------------------------------------------------------------------------------------

def module_b_table(test_set: HeldOutTestSet) -> pd.DataFrame:
    """One row per (lot, part, parameter, horizon): Module B's forecast and interval, the three physics
    baselines on the same input, the real 168h value, and the ground-truth label."""
    rows = []
    for lot in test_set.lots:
        frames = compute(lot.dataset)
        actual = {(f.lot_id, f.component_id, f.parameter): f.value_168h for f in frames}
        labels = ground_truth_labels(lot)
        defective = dict(zip(zip(labels["lot_id"], labels["component_id"]), labels["is_defective"]))
        full = [to_module_b_input(f) for f in frames]
        for view in (full, [view_at_24h(i) for i in full]):
            results = module_b.predict(view)
            baselines = physics_baselines(view)
            for inp, res in zip(view, results):
                key = (inp.lot_id, inp.component_id, inp.parameter)
                base = baselines[key]
                rows.append({
                    "family": test_set.family, "lot_id": inp.lot_id, "component_id": inp.component_id,
                    "parameter": inp.parameter, "horizon": horizon_of(inp),
                    "actual_168h": actual[key],
                    "predicted_168h": res.predicted_168h,
                    "interval_lower": res.interval_lower, "interval_upper": res.interval_upper,
                    "persistence": base.persistence, "linear": base.linear, "power_law": base.power_law,
                    "forecast_unavailable": res.forecast_unavailable,
                    "exceeds_safety_slope": res.exceeds_safety_slope,
                    "is_defective": bool(defective[(inp.lot_id, inp.component_id)]),
                })
    table = pd.DataFrame(rows)
    if table["actual_168h"].isna().any():
        raise ValueError("a held-out frame has no 168h reading to score against")
    return table


def summarize_module_b(table: pd.DataFrame) -> pd.DataFrame:
    """Per (family, parameter, horizon): MAE of the model and of each physics baseline on the parts the
    model forecast (an unavailable forecast is counted, never scored as zero), CQR interval coverage against
    its target, and the early-reject flag's recall / false-alarm rate as monitoring."""
    rows = []
    for (family, parameter, horizon), g in table.groupby(["family", "parameter", "horizon"], sort=True):
        ok = g[~g["forecast_unavailable"].astype(bool)]
        row = {"family": family, "parameter": parameter, "horizon": horizon,
               "n": len(g), "n_forecast": len(ok), "n_unavailable": int(len(g) - len(ok))}
        if len(ok):
            actual = ok["actual_168h"].to_numpy(float)
            row["mae_model"] = float(np.mean(np.abs(ok["predicted_168h"].to_numpy(float) - actual)))
            for b in BASELINES:
                row[f"mae_{b}"] = float(np.mean(np.abs(ok[b].to_numpy(float) - actual)))
            inside = (actual >= ok["interval_lower"].to_numpy(float)) & (actual <= ok["interval_upper"].to_numpy(float))
            row["coverage"] = float(inside.mean())
            row["mean_interval_width"] = float(np.mean(ok["interval_upper"] - ok["interval_lower"]))
            best = min(BASELINES, key=lambda b: row[f"mae_{b}"])
            row["best_baseline"] = best
            row["model_beats_best_baseline"] = bool(row["mae_model"] < row[f"mae_{best}"])
            flags = ok["exceeds_safety_slope"].astype(bool).to_numpy()
            y = ok["is_defective"].astype(bool).to_numpy()
            row["early_reject_recall"] = float(flags[y].mean()) if y.any() else None
            row["early_reject_false_alarm_rate"] = float(flags[~y].mean()) if (~y).any() else None
        row["target_coverage"] = DEFAULT_CONFIDENCE_LEVEL
        rows.append(row)
    return pd.DataFrame(rows)
