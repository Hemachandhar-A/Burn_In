"""S6X: the scoring-variant engine - data sides, sequential variant scoring, threshold tuning and lot-bootstrap
metrics (docs/SCORING_EXPERIMENT_PLAN.md). Used by scripts/scoring_experiment.py and its tests.

Nothing here changes shipped behaviour: it calls module_a.scoring (the optional alternative scorers) and the
repo's own cost-sensitive optimiser (harness.scoring.tune_threshold). Thresholds are tuned ONLY on the TUNING side
and written to a file; the evaluation reads them back (the tuner is never called on evaluation data).

Fast path: each lot's raw detector scores are computed once (`module_a.scoring.compute_lot_raw`) and every variant is
then a cheap function of them (`frame_severities`); tests/unit/harness/test_variants.py pins the fast path against
`module_a.detect.detect(frames, scoring=...)` so the two cannot drift.
"""
from __future__ import annotations

import dataclasses
import math
import pickle
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from contracts import ScreeningConfig
from features.compute import compute
from generator.families import FAMILIES, GeneratorFamily, resolve_family
from generator.lot import GeneratedLot, generate_lot
from generator.measurement import MeasurementParams
from generator.trajectories import TrajectoryParams
from harness import scoring as hs
from harness.held_out import ground_truth_labels
from module_a.scoring import (LotRaw, ScoringConfig, ScoringReference, compute_lot_raw, frame_severities)

PART_NUMBER = "PN-SCORE"
ACCOUNT_ID = "s6x"
FAMILY_NAMES: tuple[str, ...] = tuple(FAMILIES)
N_MIN = 300
ANCHOR_LOTS = 8  # first tuning-side lots of a family: the frozen ECOD anchor, excluded from threshold tuning
BOOTSTRAP_REPS = 1000
BOOTSTRAP_SEED = 20261003
FN_COST = hs.FN_FP_COST_RATIO


@dataclass(frozen=True)
class Side:
    name: str
    seed: int
    prefix: str
    lots_per_family: int


SIDES: Mapping[str, Side] = {
    "tune": Side("tune", 6101, "SC-TUNE", 100),
    "eval": Side("eval", 6202, "SC-EVAL", 150),
    "rob": Side("rob", 6303, "SC-ROB", 150),
    "clean": Side("clean", 6404, "SC-CLEAN", 40),
}
# Seeds that must never be reused by this experiment (shipped thresholds, sensitivity, Module B MAE / training).
FORBIDDEN_SEEDS = frozenset({2026, 5101, 7001, *range(14)})

SETTINGS = ("prev_1", "prev_3", "noise_x2")


@dataclass(frozen=True)
class Variant:
    name: str
    calibration: str  # rank | absolute | reference
    combination: str = "max"
    history_lots: int | None = None  # K, for the reference calibration

    def config(self, *, reference: ScoringReference | None, anchor: ScoringReference | None,
               review: float | None = None, reject: float | None = None) -> ScoringConfig:
        return ScoringConfig(calibration=self.calibration, combination=self.combination, reference=reference,
                             ecod_anchor=anchor, n_min=N_MIN, review_threshold=review, reject_threshold=reject)


def stage_a_variants() -> list[Variant]:
    return [Variant("V0", "rank"), Variant("V1", "absolute"),
            Variant("V2k2", "reference", history_lots=2), Variant("V2k5", "reference", history_lots=5),
            Variant("V2k10", "reference", history_lots=10)]


def stage_b_variants(calibration_variant: Variant) -> list[Variant]:
    """C0 / C1 / C2 on one calibration; C0 is the calibration variant itself (its name carries no suffix). A rank
    calibration only has C0."""
    if calibration_variant.calibration == "rank":
        return [calibration_variant]
    c0 = dataclasses.replace(calibration_variant, combination="max")
    return [c0] + [dataclasses.replace(calibration_variant, name=f"{calibration_variant.name}-{c}", combination=m)
                   for c, m in (("C1", "mean"), ("C2", "hybrid"))]


# --- data ------------------------------------------------------------------------------------------------------

def assert_sides_disjoint() -> None:
    seeds = [s.seed for s in SIDES.values()]
    prefixes = [s.prefix for s in SIDES.values()]
    if len(set(seeds)) != len(seeds) or len(set(prefixes)) != len(prefixes):
        raise AssertionError("tuning / evaluation / robustness / clean sides share a seed or an id prefix")
    bad = FORBIDDEN_SEEDS & set(seeds)
    if bad:
        raise AssertionError(f"seeds {sorted(bad)} are used elsewhere (shipped thresholds, sensitivity, Module B)")


def setting_family(key: str) -> GeneratorFamily:
    """A generator family for a robustness setting, built from the baseline family's own config objects (the same
    construction as scripts/sensitivity.py on branch evidence-measurements: noise scales the measurement and tester
    noise, prevalence fixes the defect prevalence)."""
    base = FAMILIES["baseline"]
    if key in ("prev_1", "prev_3"):
        prev = {"prev_1": 0.01, "prev_3": 0.03}[key]
        cfg = ScreeningConfig(defect_prevalence_range=(prev, prev))
        return GeneratorFamily(name=f"s6x_{key}", description=f"Baseline with defect prevalence {prev:.0%}.",
                               config=cfg, trajectory_params=TrajectoryParams(), measurement_params=MeasurementParams())
    if key == "noise_x2":
        m = MeasurementParams()
        meas = MeasurementParams(noise_frac={k: 2.0 * v for k, v in m.noise_frac.items()},
                                 tester_offset_sigma={k: 2.0 * v for k, v in m.tester_offset_sigma.items()})
        return GeneratorFamily(name="s6x_noise_x2", description="Baseline with measurement and tester noise x2.",
                               config=ScreeningConfig(), trajectory_params=TrajectoryParams(), measurement_params=meas)
    if key in FAMILIES:
        return base if key == "baseline" else FAMILIES[key]
    raise KeyError(key)


def clean_family(name: str) -> GeneratorFamily:
    """The named family with defect prevalence forced to zero (everything else unchanged)."""
    family = resolve_family(name)
    return dataclasses.replace(family, name=f"{family.name}__clean",
                               config=family.config.model_copy(update={"defect_prevalence_range": (0.0, 0.0)}))


def generate_lots(side: Side, key: str, family: GeneratorFamily, n_lots: int | None = None) -> list[GeneratedLot]:
    assert_sides_disjoint()
    n = side.lots_per_family if n_lots is None else n_lots
    return [generate_lot(f"{side.prefix}-{key}-{i:04d}", PART_NUMBER, side.seed, account_id=ACCOUNT_ID,
                         family=family) for i in range(n)]


@dataclass
class Prepared:
    """One (side, family) sequence: raw detector scores per lot, part labels, and (optionally) baseline flags."""
    side: str
    key: str
    raws: list[LotRaw]
    labels: pd.DataFrame  # lot_id, component_id, family, is_defective, defect_type
    baselines: pd.DataFrame | None = None


def prepare(side: Side, key: str, family: GeneratorFamily, *, n_lots: int | None = None,
            with_baselines: bool = False, cache_dir: Path | None = None) -> Prepared:
    """Generate the lots, compute raw scores (and baseline flags). Cached to `cache_dir` (pickle) when given."""
    n = side.lots_per_family if n_lots is None else n_lots
    path = None if cache_dir is None else Path(cache_dir) / f"prep_{side.name}_{key}_{n}_{int(with_baselines)}.pkl"
    if path is not None and path.exists():
        return pickle.loads(path.read_bytes())
    lots = generate_lots(side, key, family, n)
    raws = [compute_lot_raw(compute(lot.dataset)) for lot in lots]
    labels = pd.concat([ground_truth_labels(lot) for lot in lots], ignore_index=True)
    baselines = None
    if with_baselines:
        from harness import comparison as cmp
        from harness import industry_baselines as ib
        pat = ib.fit_static_pat(cmp.reference_lots(side.seed, cmp.PAT_REFERENCE_LOTS, PART_NUMBER))
        baselines = pd.concat([cmp._baseline_parts(lot.dataset, pat) for lot in lots], ignore_index=True)
        for name in cmp.BASELINES:
            baselines[f"{name}_flagged"] = baselines[f"{name}_flagged"].fillna(False).astype(bool)
            baselines[f"{name}_evaluable"] = baselines[f"{name}_evaluable"].fillna(False).astype(bool)
    prepared = Prepared(side.name, key, raws, labels, baselines)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(prepared))
        tmp.replace(path)
    return prepared


# --- scoring a sequence of lots under a variant ------------------------------------------------------------------

def rank_frame_scores(raw: LotRaw) -> np.ndarray:
    """Today's V0 severity per frame, live configuration (no Isolation Forest history): max over the four detectors
    of rank / n within the lot, absent MCD as 0.0 and the inactive Isolation Forest as 0.0 - exactly
    module_a.detect._detect_single_lot step 5."""
    n = len(raw.z)
    if n == 1:
        return np.array([0.5])
    mcd = np.nan_to_num(raw.mcd_d, nan=0.0)
    parts = [rankdata(a) / n for a in (raw.z, mcd, np.zeros(n), raw.ecod)]
    return np.maximum.reduce(parts)


def _part_level(raw: LotRaw, frame_score: np.ndarray, frame_override: np.ndarray | None) -> pd.DataFrame:
    codes, uniques = pd.factorize(np.array(raw.component_ids))
    score = np.full(len(uniques), -np.inf)
    np.maximum.at(score, codes, frame_score)
    override = np.zeros(len(uniques), dtype=bool)
    if frame_override is not None:
        np.logical_or.at(override, codes, frame_override)
    return pd.DataFrame({"lot_id": raw.lot_id, "component_id": uniques, "score": score, "override": override})


def score_sequence(raws: Sequence[LotRaw], variant: Variant, anchor: ScoringReference | None) -> pd.DataFrame:
    """Part-level (lot_id, component_id, score, override) for an ordered sequence of lots. A reference variant's
    reference for lot i is the pooled raw scores of the `history_lots` lots before it (the lot itself excluded)."""
    out = []
    for i, raw in enumerate(raws):
        if variant.calibration == "rank":
            out.append(_part_level(raw, rank_frame_scores(raw), None))
            continue
        ref = None
        if variant.calibration == "reference" and i > 0:
            ref = ScoringReference.from_raw(raws[max(0, i - variant.history_lots):i])
        sev = frame_severities(raw, variant.config(reference=ref, anchor=anchor))
        out.append(_part_level(raw, sev.combined, sev.override))
    return pd.concat(out, ignore_index=True)


def make_anchor(tune: Mapping[str, Prepared], family_key: str) -> ScoringReference:
    return ScoringReference.from_raw(tune[family_key].raws[:ANCHOR_LOTS])


def score_side(prepared: Mapping[str, Prepared], variant: Variant, anchors: Mapping[str, ScoringReference],
               *, skip_first: int = 0) -> pd.DataFrame:
    """Part table over every family of a side: labels + score + override + family. `skip_first` drops that many
    leading lots per family from the OUTPUT only (they still serve as history)."""
    frames = []
    for key, prep in prepared.items():
        scores = score_sequence(prep.raws, variant, anchors.get(key))
        scores = scores[~scores["lot_id"].isin({r.lot_id for r in prep.raws[:skip_first]})]
        table = prep.labels.merge(scores, on=["lot_id", "component_id"], how="inner", validate="one_to_one")
        table["family"] = key
        frames.append(table)
    return pd.concat(frames, ignore_index=True)


# --- thresholds ------------------------------------------------------------------------------------------------

def tune_thresholds(table: pd.DataFrame) -> dict[str, float]:
    """REVIEW (FN:FP 20:1) and REJECT (10:1) from harness.scoring.tune_threshold on `table` (tuning data only).
    Parts the hybrid override already flags are flagged at any REVIEW threshold, so they add a constant to the cost
    and REVIEW is tuned over the remaining parts."""
    y = table["is_defective"].to_numpy(bool)
    s = table["score"].to_numpy(float)
    forced = table["override"].to_numpy(bool)
    free = ~forced
    review = hs.tune_threshold(s[free], y[free], hs.REVIEW_FN_FP_COST_RATIO)
    reject = hs.tune_threshold(s, y, hs.FN_FP_COST_RATIO)
    return {"review": float(review), "reject": float(reject)}


def apply_thresholds(table: pd.DataFrame, thresholds: Mapping[str, float]) -> pd.DataFrame:
    table = table.copy()
    table["review_flagged"] = (table["score"] >= thresholds["review"]) | table["override"]
    table["reject_flagged"] = table["score"] >= thresholds["reject"]
    return table


# --- metrics with lot-bootstrap CIs --------------------------------------------------------------------------------

def _ratio(num, den):
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den, np.nan)


def lot_bootstrap_metrics(table: pd.DataFrame, flag_col: str, *, judged_col: str | None = None,
                          reps: int = BOOTSTRAP_REPS, seed: int = BOOTSTRAP_SEED) -> dict:
    """Flag rate, recall, precision, false alarms, missed and cost per part (FN:FP 10:1) with 95% percentile CIs
    from resampling whole lots. Metrics are over the parts the method could judge (`judged_col`, default all)."""
    judged = table if judged_col is None else table[table[judged_col].astype(bool)]
    y = judged["is_defective"].to_numpy(bool)
    f = judged[flag_col].to_numpy(bool)
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
    row = {"n_parts": int(n.sum()), "n_defective": int(y.sum()), "n_flagged": int(f.sum()),
           "false_alarms": int((f & ~y).sum()), "missed": int((~f & y).sum())}
    for k, v in point.items():
        finite = np.isfinite(boot[k])
        lo, hi = np.percentile(boot[k][finite], [2.5, 97.5]) if finite.any() else (math.nan, math.nan)
        row.update({k: v, f"{k}_ci_lo": float(lo), f"{k}_ci_hi": float(hi)})
    return row


def per_family_cost(table: pd.DataFrame, flag_col: str) -> dict[str, float]:
    out = {}
    for fam, g in table.groupby("family", sort=True):
        y, f = g["is_defective"].to_numpy(bool), g[flag_col].to_numpy(bool)
        out[fam] = hs.expected_cost(y, f, FN_COST)
    return out


def leave_one_family_out_thresholds(tune_table: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Thresholds for each family, tuned on the OTHER families' tuning parts (S6)."""
    return {fam: tune_thresholds(tune_table[tune_table["family"] != fam]) for fam in sorted(tune_table["family"].unique())}


def merge_baseline_flags(table: pd.DataFrame, baselines: pd.DataFrame) -> pd.DataFrame:
    return table.merge(baselines, on=["lot_id", "component_id"], how="left", validate="one_to_one")


def jsonable(obj):
    if isinstance(obj, Mapping):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer, np.bool_)):
        return obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj
