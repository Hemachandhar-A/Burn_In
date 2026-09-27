"""E5 step 6 (session P1.7): the Module A combination-strategy bake-off, and the harness-derived thresholds it
writes to config/harness_thresholds.yaml for module_a to apply in P3.3 (E2 step 8, Part 5.1).

Candidates (context.md 6.1), all over the same four part-level detector percentiles harness.scoring produces:
    max               - module_a's default: the part's severity is its highest detector percentile
    weighted_average  - a convex combination of the four; weights searched on a 0.1-step simplex grid
    meta_model        - a small supervised model (scikit-learn LogisticRegression) on the synthetic labels,
                        legitimate only because the harness holds ground truth a real deployment would not

Protocol: leave-one-family-out over the held-out generator families (E5 step 6 - "the winner on held-out
families"). For each fold, every strategy is fit - weights / model and its REVIEW threshold at the locked 10:1
cost - on the other families only, then scored on the held-out family at that threshold. The winner has the
lowest mean held-out cost; an exact tie goes to the earlier strategy in STRATEGIES, so `max` (the stated
default hypothesis) is only displaced by a strategy that actually beats it. The shipped thresholds are then
re-tuned for the winner on every family pooled.

Everything is seeded (the held-out sets, module_a's own random_state, LogisticRegression's lbfgs is
deterministic), so the same seed reproduces the same winner and thresholds - pinned by test_p17_bakeoff.

Run `python -m harness.bakeoff` to regenerate config/harness_thresholds.yaml and harness/results/
p17_evaluation.json (the Module A/B scoring and bake-off numbers P1.8's PPT tables are built from).
"""
import argparse
import itertools
import json
import typing
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.special import expit
from sklearn.linear_model import LogisticRegression

from contracts import HarnessThresholds
from generator.families import HELD_OUT_FAMILY_NAMES
from harness import scoring
from harness.held_out import generate_held_out_sets

STRATEGIES: tuple[str, ...] = typing.get_args(HarnessThresholds.model_fields["combination_strategy"].annotation)
HARNESS_SEED = 2026  # the one seed the shipped thresholds are derived from
WEIGHT_GRID_STEP = 0.1
_REPO_ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS_PATH = _REPO_ROOT / "config" / "harness_thresholds.yaml"
RESULTS_PATH = _REPO_ROOT / "harness" / "results" / "p17_evaluation.json"
_DETECTORS = list(scoring.DETECTORS)


@dataclass(frozen=True)
class FittedStrategy:
    """A fitted candidate, fully described by `params` - so the same scores can be rebuilt from the
    TEMP_combination_params written beside the thresholds, without the scikit-learn object."""
    name: str
    params: Mapping = field(default_factory=dict)

    def score(self, table: pd.DataFrame) -> np.ndarray:
        X = table[_DETECTORS].to_numpy(dtype=float)
        if self.name == "max":
            return X.max(axis=1)
        if self.name == "weighted_average":
            return X @ np.array([self.params["weights"][d] for d in _DETECTORS])
        if self.name == "meta_model":  # LogisticRegression's own predict_proba, from its fitted parameters
            coef = np.array([self.params["coefficients"][d] for d in _DETECTORS])
            return expit(X @ coef + self.params["intercept"])
        raise ValueError(f"unknown combination strategy {self.name!r}; expected one of {STRATEGIES}")


def _weight_grid(step: float = WEIGHT_GRID_STEP) -> list[tuple[float, ...]]:
    k = round(1 / step)
    return [tuple(c / k for c in combo) for combo in itertools.product(range(k + 1), repeat=len(_DETECTORS))
            if sum(combo) == k]


def fit_strategy(name: str, train: pd.DataFrame,
                 fn_fp_cost_ratio: float = scoring.REVIEW_FN_FP_COST_RATIO) -> FittedStrategy:
    """Fit one candidate on `train` (part-level detector percentiles + is_defective)."""
    if name == "max":
        return FittedStrategy("max")
    X = train[_DETECTORS].to_numpy(dtype=float)
    y = train["is_defective"].to_numpy(bool)
    if name == "weighted_average":
        best_cost, best_w = np.inf, None
        for w in _weight_grid():
            s = X @ np.array(w)
            cost = scoring.expected_cost(y, s >= scoring.tune_threshold(s, y, fn_fp_cost_ratio), fn_fp_cost_ratio)
            if cost < best_cost:  # strict: the first grid point wins a tie, so the search is order-stable
                best_cost, best_w = cost, w
        return FittedStrategy(name, {"weights": dict(zip(_DETECTORS, best_w))})
    if name == "meta_model":
        model = LogisticRegression(max_iter=1000).fit(X, y)
        params = {"coefficients": dict(zip(_DETECTORS, map(float, model.coef_[0]))),
                  "intercept": float(model.intercept_[0])}
        return FittedStrategy(name, params)
    raise ValueError(f"unknown combination strategy {name!r}; expected one of {STRATEGIES}")


def leave_one_family_out(table: pd.DataFrame,
                         fn_fp_cost_ratio: float = scoring.REVIEW_FN_FP_COST_RATIO) -> pd.DataFrame:
    families = sorted(table["family"].unique())
    if len(families) < 2:
        raise ValueError(f"leave-one-family-out needs at least two families, got {families}")
    rows = []
    for held_out in families:
        train, test = table[table["family"] != held_out], table[table["family"] == held_out]
        for name in STRATEGIES:
            fitted = fit_strategy(name, train, fn_fp_cost_ratio)
            train_scores = fitted.score(train)
            threshold = scoring.tune_threshold(train_scores, train["is_defective"], fn_fp_cost_ratio)
            m = scoring.classification_metrics(test["is_defective"], fitted.score(test) >= threshold,
                                               fn_fp_cost_ratio)
            rows.append({"strategy": name, "held_out_family": held_out, "threshold": threshold, **m})
    return pd.DataFrame(rows)


def choose_winner(folds: pd.DataFrame) -> str:
    mean_cost = folds.groupby("strategy")["cost"].mean()
    ordered = [s for s in STRATEGIES if s in mean_cost.index]
    return min(ordered, key=lambda s: (mean_cost[s], ordered.index(s)))


def derive_thresholds(table: pd.DataFrame, strategy: str) -> HarnessThresholds:
    """REVIEW at the locked 10:1 cost, REJECT at 1:1 (scoring.REJECT_FN_FP_COST_RATIO), both for `strategy`
    fit on the whole table. REJECT is never looser than REVIEW."""
    fitted = fit_strategy(strategy, table)
    scores, y = fitted.score(table), table["is_defective"]
    review = scoring.tune_threshold(scores, y, scoring.REVIEW_FN_FP_COST_RATIO)
    reject = max(review, scoring.tune_threshold(scores, y, scoring.REJECT_FN_FP_COST_RATIO))
    return HarnessThresholds(module_a_review_threshold=review, module_a_reject_threshold=reject,
                             combination_strategy=strategy)


TEMP_PARAMS_KEY = "TEMP_combination_params"


def write_harness_thresholds(thresholds: HarnessThresholds, path: Path = THRESHOLDS_PATH,
                             provenance: Iterable[str] = (), temp_params: Mapping | None = None) -> None:
    """HarnessThresholds' fields as YAML keys (P3.3 loads it with HarnessThresholds(**yaml)); how the numbers
    were produced goes in comments. The one extra key, TEMP_combination_params, carries the winner's fitted
    parameters, which HarnessThresholds has no field for (CONTRACT_CHANGES.md, 2026-09-27 P1 - bake-off
    winner); HarnessThresholds ignores unknown keys, so the contracted load is unaffected."""
    header = ["Harness-derived (E5 step 6, session P1.7) - never hand-edit; regenerate with",
              "`python -m harness.bakeoff`. Read by module_a in P3.3 as contracts.HarnessThresholds (Part 5.1).",
              *provenance]
    data = thresholds.model_dump()
    if temp_params:
        data[TEMP_PARAMS_KEY] = _jsonable(temp_params)
    body = yaml.safe_dump(data, sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"# {line}\n" for line in header) + body, encoding="utf-8")


def load_harness_thresholds(path: Path = THRESHOLDS_PATH) -> HarnessThresholds:
    return HarnessThresholds(**yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def load_fitted_strategy(path: Path = THRESHOLDS_PATH) -> FittedStrategy:
    """The winning combination, rebuilt from the thresholds file (strategy + TEMP_combination_params)."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return FittedStrategy(HarnessThresholds(**raw).combination_strategy, raw.get(TEMP_PARAMS_KEY) or {})


def module_a_tables(sets: Mapping) -> pd.DataFrame:
    return pd.concat([scoring.module_a_table(s) for s in sets.values()], ignore_index=True)


def run_bakeoff(*, seed: int = HARNESS_SEED, families: Sequence[str] = HELD_OUT_FAMILY_NAMES,
                score_module_b: bool = False, **held_out_kwargs) -> dict:
    """The whole of E5 steps 4-6 on freshly generated held-out sets. Returns a JSON-able report."""
    sets = generate_held_out_sets(seed=seed, families=families, **held_out_kwargs)
    table = module_a_tables(sets)
    folds = leave_one_family_out(table)
    winner = choose_winner(folds)
    thresholds = derive_thresholds(table, winner)
    fitted = fit_strategy(winner, table)
    scores = fitted.score(table)
    report = {
        "seed": seed,
        "families": list(sets),
        "held_out_sets": {name: {"lots": len(s.lots), "parts": s.n_parts, "defective": s.n_defective,
                                 "archetype_counts": dict(s.archetype_counts)} for name, s in sets.items()},
        "cost_ratios": {"review": scoring.REVIEW_FN_FP_COST_RATIO, "reject": scoring.REJECT_FN_FP_COST_RATIO},
        "folds": folds.to_dict("records"),
        "mean_held_out_cost": folds.groupby("strategy")["cost"].mean().reindex(STRATEGIES).to_dict(),
        "winner": winner,
        "winner_params": _jsonable(fitted.params),
        "thresholds": thresholds.model_dump(),
        # every candidate's pooled thresholds, so a Lead decision against the winner has its numbers ready
        "thresholds_by_strategy": {name: derive_thresholds(table, name).model_dump() for name in STRATEGIES},
        "params_by_strategy": {name: _jsonable(fit_strategy(name, table).params) for name in STRATEGIES},
        "module_a": {
            "review": scoring.evaluate_module_a(table, scores, thresholds.module_a_review_threshold),
            "reject": scoring.evaluate_module_a(table, scores, thresholds.module_a_reject_threshold),
        },
    }
    if score_module_b:
        b = pd.concat([scoring.module_b_table(s) for s in sets.values()], ignore_index=True)
        report["module_b"] = scoring.summarize_module_b(b).to_dict("records")
    return report


def _jsonable(obj):
    if isinstance(obj, Mapping):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer, np.bool_)):
        return obj.item()
    return obj


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=HARNESS_SEED)
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_PATH)
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    args = parser.parse_args(argv)
    report = run_bakeoff(seed=args.seed, score_module_b=True)
    th = HarnessThresholds(**report["thresholds"])
    means = ", ".join(f"{k} {v:.4f}" for k, v in report["mean_held_out_cost"].items())
    alt = "; ".join(f"{k}: review {v['module_a_review_threshold']:.4f} / reject {v['module_a_reject_threshold']:.4f}"
                    for k, v in report["thresholds_by_strategy"].items())
    write_harness_thresholds(th, args.thresholds, temp_params=report["winner_params"], provenance=[
        f"seed {report['seed']}; held-out families: {', '.join(report['families'])}",
        f"leave-one-family-out mean cost per part (FN:FP = {scoring.REVIEW_FN_FP_COST_RATIO:g}:1): {means}",
        (f"REVIEW tuned at FN:FP {scoring.REVIEW_FN_FP_COST_RATIO:g}:1, REJECT at "
        f"{scoring.REJECT_FN_FP_COST_RATIO:g}:1 (disclosed judgment call - harness/scoring.py)"),
        "Inputs: each detector's worst-parameter within-lot percentile, 0-1 (E2 steps 5, 8); the thresholds",
        "are on the winning strategy's score scale (meta_model: a probability, 0-1).",
        f"All candidates' pooled thresholds (harness/results/p17_evaluation.json): {alt}",
    ])
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(_jsonable(report), indent=2, allow_nan=False), encoding="utf-8")
    print(f"winner: {report['winner']}  ({means})")
    print(f"thresholds: {th.model_dump()}")


if __name__ == "__main__":
    main()
