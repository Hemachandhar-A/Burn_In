"""module_a/scoring.py - OPTIONAL alternative score calibrations / combinations (experiment S6X).

Nothing here is used unless a caller passes `scoring=` to `module_a.detect.detect`; with `scoring=None` (the default)
detect() runs today's code unchanged. See docs/SCORING_EXPERIMENT_PLAN.md for the variants and why they exist.

    calibration  "rank"       today: rank-percentile of each detector's score within the lot (V0)
                 "absolute"   V1: -log10(p) from a normal tail (z) / chi-square tail (MCD); ECOD, whose score is a
                              lot-relative empirical quantity, is mapped by a conformal p-value against a frozen
                              `ecod_anchor` (left out when no anchor is supplied)
                 "reference"  V2: -log10 of a conformal p-value against the raw scores of EARLIER lots
                              (`reference`); below `n_min` reference parts a detector falls back to V1
    combination  "max"        maximum of the available detectors' severities (today's rule)
                 "mean"       C1: mean of the available detectors' severities
                 "hybrid"     C2: the mean, plus an override: any single detector with p <= override_p forces the
                              part to at least REVIEW

The Isolation Forest is never part of a non-"rank" variant. Detector scores are the same ones detect() computes
(`compute_lot_raw` mirrors the MCD and ECOD steps of `_detect_single_lot`; a unit test pins that they agree exactly).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

import numpy as np
from pyod.models.ecod import ECOD
from scipy.stats import chi2, norm
from sklearn.covariance import MinCovDet

from contracts import FeatureFrame
from features.compute import build_mcd_matrix
from module_a.detect import _MCD_LOT_SIZE_FLOOR, _RANDOM_STATE, _value_matrix

_LN10 = math.log(10.0)
DETECTORS = ("robust_z", "mcd", "ecod")


@dataclass(frozen=True)
class ScoringReference:
    """Raw detector scores from earlier lots: |z| and ECOD per parameter, MCD distance once per component."""

    robust_z: Mapping[str, np.ndarray]
    ecod: Mapping[str, np.ndarray]
    mcd: np.ndarray
    n_parts: int

    @staticmethod
    def from_raw(raws: Sequence["LotRaw"]) -> "ScoringReference":
        z: dict[str, list[np.ndarray]] = {}
        e: dict[str, list[np.ndarray]] = {}
        mcd: list[np.ndarray] = []
        n_parts = 0
        for raw in raws:
            for param in sorted(set(raw.parameters)):
                idx = np.array([p == param for p in raw.parameters])
                z.setdefault(param, []).append(raw.z[idx])
                e.setdefault(param, []).append(raw.ecod[idx])
            first = {}
            for i, cid in enumerate(raw.component_ids):
                first.setdefault(cid, i)
            sel = np.array(sorted(first.values()), dtype=int)
            n_parts += len(sel)
            if len(sel):
                vals = raw.mcd_d[sel]
                mcd.append(vals[~np.isnan(vals)])
        return ScoringReference(
            robust_z={k: np.sort(np.concatenate(v)) for k, v in z.items()},
            ecod={k: np.sort(np.concatenate(v)) for k, v in e.items()},
            mcd=np.sort(np.concatenate(mcd)) if mcd else np.empty(0),
            n_parts=n_parts,
        )


@dataclass(frozen=True)
class ScoringConfig:
    calibration: Literal["rank", "absolute", "reference"] = "rank"
    combination: Literal["max", "mean", "hybrid"] = "max"
    reference: ScoringReference | None = None
    ecod_anchor: ScoringReference | None = None
    n_min: int = 300
    override_p: float = 1e-4
    # Tier cut-offs on the variant's own severity scale. None -> config/harness_thresholds.yaml, which is only
    # meaningful for the "rank" scale; non-rank variants must supply both.
    review_threshold: float | None = None
    reject_threshold: float | None = None

    def __post_init__(self) -> None:
        if self.calibration not in ("rank", "absolute", "reference"):
            raise ValueError(f"unknown calibration {self.calibration!r}")
        if self.combination not in ("max", "mean", "hybrid"):
            raise ValueError(f"unknown combination {self.combination!r}")
        if self.calibration == "rank" and self.combination != "max":
            raise ValueError("rank calibration is only defined with the max combination")
        if self.n_min < 1:
            raise ValueError("n_min must be >= 1")
        if not 0.0 < self.override_p < 1.0:
            raise ValueError("override_p must be in (0, 1)")

    @property
    def is_legacy(self) -> bool:
        return self.calibration == "rank" and self.combination == "max"


@dataclass(frozen=True)
class LotRaw:
    """One lot's per-frame raw detector scores, aligned with `component_ids` / `parameters`."""

    lot_id: str
    lot_size: int
    component_ids: list[str]
    parameters: list[str]
    below_median: np.ndarray  # bool: direction of the worst-checkpoint z
    z: np.ndarray             # |worst-checkpoint robust z|
    mcd_d: np.ndarray         # sqrt of MCD squared Mahalanobis distance, max over checkpoints; NaN if no MCD
    mcd_sev1: np.ndarray      # max over checkpoints of -log10 chi-square upper tail (df = #parameters); NaN if no MCD
    ecod: np.ndarray


@dataclass(frozen=True)
class FrameSeverities:
    sev_z: np.ndarray
    sev_mcd: np.ndarray    # NaN where unavailable
    sev_ecod: np.ndarray   # NaN where unavailable
    combined: np.ndarray
    override: np.ndarray   # bool; only ever True for the hybrid combination
    ecod_source: str = ""  # which mapping ECOD used for this lot (diagnostics)


# ---------------------------------------------------------------------------------------------------------------
# Raw scores
# ---------------------------------------------------------------------------------------------------------------

def compute_lot_raw(frames: Sequence[FeatureFrame]) -> LotRaw:
    """The detectors' raw scores for ONE lot (all frames share lot_id). Mirrors `_detect_single_lot`'s steps 1, 2
    and 4; the Isolation Forest is not computed."""
    frames = list(frames)
    lot_size = frames[0].lot_size
    mcd_d: dict[str, float] = {}
    mcd_sev: dict[str, float] = {}
    if lot_size >= _MCD_LOT_SIZE_FLOOR:
        for checkpoint in sorted({ck for f in frames for ck in f.robust_z}):
            component_ids, _params, matrix = build_mcd_matrix(frames, checkpoint)
            if len(component_ids) < _MCD_LOT_SIZE_FLOOR or not matrix or len(matrix[0]) == 0:
                continue
            X = np.array(matrix, dtype=float)
            try:
                mcd = MinCovDet(random_state=_RANDOM_STATE)
                mcd.fit(X)
                sq = mcd.mahalanobis(X)
            except (ValueError, np.linalg.LinAlgError):
                continue
            sev = chi2_neg_log10_sf(sq, X.shape[1])
            for cid, s2, sv in zip(component_ids, sq, sev):
                d = float(np.sqrt(s2))
                if cid not in mcd_d or d > mcd_d[cid]:
                    mcd_d[cid] = d
                if cid not in mcd_sev or sv > mcd_sev[cid]:
                    mcd_sev[cid] = float(sv)

    by_param: dict[str, list[FeatureFrame]] = {}
    for f in frames:
        by_param.setdefault(f.parameter, []).append(f)
    ecod_by_key: dict[tuple[str, str], float] = {}
    for param, pframes in by_param.items():
        X = _value_matrix(pframes)
        if X.shape[0] == 0:
            continue
        clf = ECOD(contamination=0.1)
        clf.fit(X)
        for frame, score in zip(pframes, clf.decision_scores_):
            ecod_by_key[(frame.component_id, frame.parameter)] = float(score)

    worst = [max(f.robust_z.values(), key=abs) if f.robust_z else 0.0 for f in frames]
    return LotRaw(
        lot_id=frames[0].lot_id,
        lot_size=lot_size,
        component_ids=[f.component_id for f in frames],
        parameters=[f.parameter for f in frames],
        below_median=np.array([w < 0 for w in worst], dtype=bool),
        z=np.array([abs(w) for w in worst], dtype=float),
        mcd_d=np.array([mcd_d.get(f.component_id, np.nan) for f in frames], dtype=float),
        mcd_sev1=np.array([mcd_sev.get(f.component_id, np.nan) for f in frames], dtype=float),
        ecod=np.array([ecod_by_key.get((f.component_id, f.parameter), 0.0) for f in frames], dtype=float),
    )


# ---------------------------------------------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------------------------------------------

def chi2_neg_log10_sf(x: np.ndarray, df: int) -> np.ndarray:
    """-log10 of the chi-square upper-tail probability, finite far into the tail. scipy's `chi2.logsf` returns -inf
    once the probability underflows (a squared distance beyond about 1,600 at 3 dimensions), which would turn a
    huge outlier's severity into infinity; there the incomplete-gamma asymptotic series is used instead:
    log Q(a, y) ~ (a-1) ln y - y - lgamma(a) + ln(1 + (a-1)/y + (a-1)(a-2)/y^2 + ...), a = df/2, y = x/2."""
    x = np.asarray(x, dtype=float)
    out = -chi2.logsf(x, df) / _LN10
    tail = ~np.isfinite(out)
    if tail.any():
        a, y = df / 2.0, x[tail] / 2.0
        series, term = np.ones_like(y), np.ones_like(y)
        for j in range(1, 40):
            term = term * (a - j) / y
            series = series + term
            if np.all(np.abs(term) < 1e-17):
                break
        log_q = (a - 1.0) * np.log(y) - y - math.lgamma(a) + np.log(series)
        out[tail] = -log_q / _LN10
    return out


def _sev_z_absolute(z: np.ndarray) -> np.ndarray:
    """-log10 of the two-sided normal tail probability of |z|."""
    return -(math.log(2.0) + norm.logsf(z)) / _LN10


def conformal_severity(values: np.ndarray, sorted_reference: np.ndarray) -> np.ndarray:
    """-log10 of p = (1 + #{reference >= value}) / (1 + N). Needs the reference sorted ascending."""
    n = len(sorted_reference)
    ge = n - np.searchsorted(sorted_reference, values, side="left")
    return -np.log10((1.0 + ge) / (1.0 + n))


def frame_severities(raw: LotRaw, scoring: ScoringConfig) -> FrameSeverities:
    """Per-frame detector severities and their combination under a non-rank `scoring`."""
    if scoring.calibration == "rank":
        raise ValueError("frame_severities is for the absolute / reference calibrations; rank is detect()'s own path")
    n = len(raw.z)
    params = np.array(raw.parameters)
    ref = scoring.reference if scoring.calibration == "reference" else None
    anchor = scoring.ecod_anchor
    use_ref = ref is not None and ref.n_parts >= scoring.n_min

    sev_z = np.full(n, np.nan)
    sev_ecod = np.full(n, np.nan)
    absolute_z = _sev_z_absolute(raw.z)
    ecod_source = "none"
    for param in sorted(set(raw.parameters)):
        idx = params == param
        if use_ref and param in ref.robust_z:
            sev_z[idx] = conformal_severity(raw.z[idx], ref.robust_z[param])
        else:
            sev_z[idx] = absolute_z[idx]
        if use_ref and param in ref.ecod:
            sev_ecod[idx] = conformal_severity(raw.ecod[idx], ref.ecod[param])
            ecod_source = "reference"
        elif anchor is not None and anchor.n_parts >= scoring.n_min and param in anchor.ecod:
            sev_ecod[idx] = conformal_severity(raw.ecod[idx], anchor.ecod[param])
            ecod_source = "anchor"
    have_mcd = ~np.isnan(raw.mcd_d)
    if use_ref and len(ref.mcd) >= scoring.n_min:
        sev_mcd = np.where(have_mcd, conformal_severity(np.nan_to_num(raw.mcd_d), ref.mcd), np.nan)
    else:
        sev_mcd = raw.mcd_sev1.copy()

    stack = np.vstack([sev_z, sev_mcd, sev_ecod])
    with np.errstate(all="ignore"):
        if scoring.combination == "max":
            combined = np.nanmax(stack, axis=0)
        else:
            combined = np.nanmean(stack, axis=0)
    override = np.zeros(n, dtype=bool)
    if scoring.combination == "hybrid":
        cutoff = -math.log10(scoring.override_p)
        with np.errstate(invalid="ignore"):
            override = (np.nan_to_num(stack, nan=-np.inf) >= cutoff).any(axis=0)
    return FrameSeverities(sev_z=sev_z, sev_mcd=sev_mcd, sev_ecod=sev_ecod, combined=combined,
                           override=override, ecod_source=ecod_source)


# ---------------------------------------------------------------------------------------------------------------
# Results (what detect(scoring=...) returns for a non-rank variant)
# ---------------------------------------------------------------------------------------------------------------

def detect_lot_scored(frames: Sequence[FeatureFrame], scoring: ScoringConfig):
    """ModuleAResult per frame of ONE lot under a non-rank `scoring`. Tier rule is detect()'s own: REJECT at or above
    the reject threshold (below-median direction capped to REVIEW), REVIEW at or above the review threshold or on a
    hybrid override, else PASS. combined_severity is on the variant's own scale (-log10 p, or its mean)."""
    from contracts import ModuleAResult

    if scoring.review_threshold is None or scoring.reject_threshold is None:
        raise ValueError("a non-rank scoring needs review_threshold and reject_threshold on its own severity scale")
    frames = list(frames)
    raw = compute_lot_raw(frames)
    sev = frame_severities(raw, scoring)
    results = []
    for i, frame in enumerate(frames):
        combined = float(sev.combined[i])
        direction = "below_median" if raw.below_median[i] else "above_median"
        cap = None
        if combined >= scoring.reject_threshold:
            if direction == "below_median":
                tier, cap = "REVIEW", "below_median_direction_cap"
            else:
                tier = "REJECT"
        elif combined >= scoring.review_threshold or bool(sev.override[i]):
            tier = "REVIEW"
        else:
            tier = "PASS"
        explainable = np.nanmax([sev.sev_z[i], sev.sev_mcd[i]]) if not np.isnan(sev.sev_mcd[i]) else sev.sev_z[i]
        top = np.nanmax([sev.sev_z[i], sev.sev_mcd[i], sev.sev_ecod[i]])
        mcd_tag = not np.isnan(raw.mcd_d[i])
        results.append(ModuleAResult(
            component_id=frame.component_id, lot_id=frame.lot_id, parameter=frame.parameter,
            robust_z=float(raw.z[i]),
            mcd_distance=float(raw.mcd_d[i]) if mcd_tag else None,
            isolation_forest_score=None,
            ecod_score=float(raw.ecod[i]),
            explainable_tags={"robust_z": True, "mcd": bool(mcd_tag), "isolation_forest": False, "ecod": False},
            direction=direction, severity_tier=tier, severity_cap_reason=cap, combined_severity=combined,
            explainable_corroboration=bool(explainable >= top - 1e-10),
        ))
    return results
