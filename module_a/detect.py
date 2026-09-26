"""module_a/detect.py — real implementation through P3.2 + lot_id patch + multi-lot fix.

Sessions completed:
  P3.0      Stub — correctly-shaped fixed fake data
  P3.1      E2 steps 1-3: robust z-scalar, per-checkpoint MCD, pooled Isolation Forest
  P3.2      E2 steps 4-6: ECOD (PyOD), percentile-normalise + max-combine, direction-awareness cap
  lot_id    Populate ModuleAResult.lot_id from FeatureFrame (new contract field from develop merge).
  multi-lot FIX: detect() now groups frames by lot_id and processes each lot independently.
            Previously, passing multiple lots in one call would compute lot-relative statistics
            (MCD, ECOD, percentile ranks, lot_size) across the pooled set, silently corrupting
            every per-lot result. Confirmed with real numbers: MCD 213.92 (batched) vs 145.39
            (alone) for the same component. Fix: public detect() routes to _detect_single_lot()
            per lot and concatenates results preserving input order.

Contract:
  Input:  list[FeatureFrame]                 — from features.compute() (P2). May span multiple
                                               lots; each lot is processed independently.
          prior_frames: list[FeatureFrame]   — pooled cross-lot history for the same
                                               part number(s), used to train IF only.
                                               These intentionally span lots (E2 step 3).
  Output: list[ModuleAResult]               — one result per input frame, same order.

E2 step notes
-------------
Step 4 — ECOD (pyod.models.ecod.ECOD):
  Fit on the current lot's [value_0h, value_24h] matrix — lot-relative, like z-score/MCD.
  PyOD's ECOD is parameter-free and deterministic.
  Raw anomaly score from decision_scores_ (higher = more anomalous).
  Tagged not-explainable (E2 step 7) — ecod=False.
  Note: contracts.py comment shows "ecod": True but E2 step 7 spec says ECOD is not
  explainable — we follow the spec. The comment is a documentation inconsistency.

Step 5 — Percentile-normalise + max-combine:
  Each detector's raw score is converted to a percentile rank (0–1) within the lot:
    percentile_rank(score, all_scores) = rank(score) / n  [scipy.stats.rankdata]
  For absent scores (cold-start IF → None, small-lot MCD → None): absent detector
  arrays are all 0.0, so rankdata gives (n+1)/(2n) ≈ 0.5 to all components (average
  rank of tied zeros). This floor is always < _CAP_PERCENTILE_THRESHOLD for n >= 2,
  so it cannot alone trigger spurious capping — confirmed in test_p32_hardening.py.
  Combined severity: max(z_pct, mcd_pct, iso_pct, ecod_pct).

Step 6 — Direction-awareness cap:
  E2 step 6 (verbatim): "a below-median (benign-direction) deviation is capped at
  WATCH-eligible severity, never REJECT-eligible on that basis alone."
  In the contracted Literal (PASS/REVIEW/REJECT): WATCH-eligible = capped to REVIEW.
  The cap fires when:
    direction == "below_median" AND combined_severity >= _CAP_THRESHOLD
  When it fires: severity_cap_reason = "below_median_direction_cap"
  The cap applies unconditionally (no recycled-part exception yet — stretch feature).
  WARNING: do NOT remove this cap. See E2 pitfall note.

Step 7 — Explainable tags: robust_z=True, mcd=True/False, isolation_forest=False, ecod=False.

Severity tier (TEMP — real harness thresholds wired in P3.3):
  PASS for all parts. The cap logic is active and severity_cap_reason is populated
  when the cap fires, so P3.3 only needs to wire the thresholds, not add cap logic.

AGENTS.md rules:
  R1  — output matches contracts.py exactly
  R3  — only module_a/ touched; features/ and pyod/ called, never edited
  R4  — contracts.py read-only
  R9  — fixed seeds everywhere (random_state=42)
"""

from __future__ import annotations

import numpy as np
from scipy.stats import rankdata
from sklearn.covariance import MinCovDet
from sklearn.ensemble import IsolationForest
from pyod.models.ecod import ECOD

from contracts import FeatureFrame, ModuleAResult
from features.compute import build_mcd_matrix

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MCD_LOT_SIZE_FLOOR: int = 30
_RANDOM_STATE: int = 42

# Provisional cap threshold for direction-awareness (step 6).
# A combined percentile >= this is considered "would have been REVIEW/REJECT territory"
# and triggers the below_median cap. Real harness thresholds replace this in P3.3.
_CAP_PERCENTILE_THRESHOLD: float = 0.80


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect(
    frames: list[FeatureFrame],
    prior_frames: list[FeatureFrame] | None = None,
) -> list[ModuleAResult]:
    """Score every FeatureFrame in *frames* and return a ModuleAResult per frame.

    Parameters
    ----------
    frames:
        FeatureFrames for one or more lots. All lot-relative statistics (MCD, ECOD,
        percentile ranks) are computed per lot_id. Order is preserved in the output.
    prior_frames:
        FeatureFrames from *previous* lots of the same part number(s), used as the
        Isolation Forest's training set only. These intentionally span lots (E2 step 3).
        Omit or pass [] for cold start.

    Returns
    -------
    list[ModuleAResult]
        Same length and order as *frames*. Empty input → empty output.
    """
    if not frames:
        return []

    if prior_frames is None:
        prior_frames = []

    # Build IF models once from prior_frames (intentionally cross-lot pooled, E2 step 3).
    if_models = _build_if_models(prior_frames)

    # Group frames by lot_id, preserving insertion order (Python 3.7+ dict guarantee).
    lots: dict[str, list[tuple[int, FeatureFrame]]] = {}
    for idx, frame in enumerate(frames):
        lots.setdefault(frame.lot_id, []).append((idx, frame))

    # Process each lot independently and collect (original_index, result) pairs.
    indexed_results: list[tuple[int, ModuleAResult]] = []
    for lot_frames_indexed in lots.values():
        original_indices = [t[0] for t in lot_frames_indexed]
        lot_frames = [t[1] for t in lot_frames_indexed]
        lot_results = _detect_single_lot(lot_frames, if_models)
        indexed_results.extend(zip(original_indices, lot_results))

    # Restore original input order.
    indexed_results.sort(key=lambda t: t[0])
    return [r for _, r in indexed_results]


# ---------------------------------------------------------------------------
# Private: per-lot processing
# ---------------------------------------------------------------------------

def _detect_single_lot(
    frames: list[FeatureFrame],
    if_models: dict[str, IsolationForest],
) -> list[ModuleAResult]:
    """Score all frames from a *single* lot. Called once per lot_id by detect().

    All statistics (MCD, ECOD, percentile ranks) are computed over `frames` only,
    which all share the same lot_id. IF models are passed in pre-built from prior_frames.
    """
    lot_size = frames[0].lot_size
    n = len(frames)

    # ------------------------------------------------------------------
    # Step 2 — MCD per checkpoint (lot-relative)
    # ------------------------------------------------------------------
    mcd_by_component: dict[str, float] = {}

    if lot_size >= _MCD_LOT_SIZE_FLOOR:
        checkpoints = sorted({ck for f in frames for ck in f.robust_z})
        for checkpoint in checkpoints:
            component_ids, _params, matrix = build_mcd_matrix(frames, checkpoint)
            if len(component_ids) < _MCD_LOT_SIZE_FLOOR or not matrix or len(matrix[0]) == 0:
                continue
            X = np.array(matrix, dtype=float)
            try:
                mcd = MinCovDet(random_state=_RANDOM_STATE)
                mcd.fit(X)
                distances = mcd.mahalanobis(X)
                for cid, dist in zip(component_ids, distances):
                    d = float(np.sqrt(dist))
                    if cid not in mcd_by_component or d > mcd_by_component[cid]:
                        mcd_by_component[cid] = d
            except (ValueError, np.linalg.LinAlgError):
                # Expected failure: singular / not-full-rank covariance matrix.
                # Any other exception in this block is a real bug and must propagate.
                pass

    # ------------------------------------------------------------------
    # Step 4 — ECOD (lot-relative, PyOD)
    # Group current lot's frames by parameter; fit one ECOD per parameter.
    # ------------------------------------------------------------------
    frames_by_param: dict[str, list[FeatureFrame]] = {}
    for f in frames:
        frames_by_param.setdefault(f.parameter, []).append(f)

    ecod_scores_by_cid_param: dict[tuple[str, str], float] = {}
    for param, pframes in frames_by_param.items():
        X = _value_matrix(pframes)
        if X.shape[0] == 0:
            continue
        clf_ecod = ECOD(contamination=0.1)  # default contamination; score not threshold
        clf_ecod.fit(X)
        # decision_scores_: higher = more anomalous (PyOD convention)
        for frame, score in zip(pframes, clf_ecod.decision_scores_):
            ecod_scores_by_cid_param[(frame.component_id, frame.parameter)] = float(score)

    # ------------------------------------------------------------------
    # Step 5 — Percentile-normalise each detector within this lot, then max-combine.
    # ------------------------------------------------------------------

    # Robust z scalars
    z_raw = np.array([
        abs(max(f.robust_z.values(), key=abs)) if f.robust_z else 0.0
        for f in frames
    ])

    # MCD distances (absent → 0.0, see docstring note on absent-detector floor)
    mcd_raw = np.array([
        mcd_by_component.get(f.component_id, 0.0) if lot_size >= _MCD_LOT_SIZE_FLOOR else 0.0
        for f in frames
    ])

    # IF scores (absent/cold-start → 0.0; sklearn IF convention: lower = more anomalous,
    # so we negate: higher = more anomalous, consistent with ECOD and z-score).
    iso_raw = np.array([
        -float(if_models[f.parameter].score_samples(_value_matrix([f]))[0])
        if f.parameter in if_models else 0.0
        for f in frames
    ])

    # ECOD scores
    ecod_raw = np.array([
        ecod_scores_by_cid_param.get((f.component_id, f.parameter), 0.0)
        for f in frames
    ])

    # Percentile rank (0–1). rankdata uses 'average' for ties by default.
    def _pct(arr: np.ndarray) -> np.ndarray:
        if n == 1:
            return np.array([0.5])  # single-element lot: mid-range percentile
        return rankdata(arr) / n

    z_pct   = _pct(z_raw)
    mcd_pct = _pct(mcd_raw)
    iso_pct = _pct(iso_raw)
    ecod_pct = _pct(ecod_raw)

    # Combined severity: max across all four detectors.
    combined = np.maximum.reduce([z_pct, mcd_pct, iso_pct, ecod_pct])

    # ------------------------------------------------------------------
    # Build one result per frame.
    # ------------------------------------------------------------------
    results: list[ModuleAResult] = []
    for i, frame in enumerate(frames):
        # Step 1: worst-checkpoint z scalar and direction
        z_values = list(frame.robust_z.values())
        worst_z = max(z_values, key=abs) if z_values else 0.0
        direction: str = "below_median" if worst_z < 0 else "above_median"
        robust_z_scalar = abs(worst_z)

        # Step 2: MCD
        mcd_distance: float | None = None
        mcd_tag: bool = False
        if lot_size >= _MCD_LOT_SIZE_FLOOR:
            raw = mcd_by_component.get(frame.component_id)
            mcd_distance = raw
            mcd_tag = raw is not None

        # Step 3: IF score (restore sklearn sign for storage: lower = more anomalous)
        iso_score: float | None = None
        if frame.parameter in if_models:
            X_cur = _value_matrix([frame])
            if X_cur.shape[0] > 0:
                iso_score = float(if_models[frame.parameter].score_samples(X_cur)[0])

        # Step 4: ECOD score
        ecod_score = ecod_scores_by_cid_param.get((frame.component_id, frame.parameter), 0.0)

        # Step 6: direction-awareness cap (WARNING: do NOT remove — E2 pitfall note)
        severity_cap_reason: str | None = None
        if direction == "below_median" and combined[i] >= _CAP_PERCENTILE_THRESHOLD:
            severity_cap_reason = "below_median_direction_cap"

        results.append(ModuleAResult(
            component_id=frame.component_id,
            lot_id=frame.lot_id,
            parameter=frame.parameter,
            robust_z=robust_z_scalar,
            mcd_distance=mcd_distance,
            isolation_forest_score=iso_score,
            ecod_score=ecod_score,
            explainable_tags={
                "robust_z": True,
                "mcd": mcd_tag,
                "isolation_forest": False,  # E2 step 7: IF not explainable
                "ecod": False,              # E2 step 7: ECOD not explainable
            },
            direction=direction,
            severity_tier="PASS",   # TEMP — real thresholds wired in P3.3
            severity_cap_reason=severity_cap_reason,
        ))

    return results


def _build_if_models(
    prior_frames: list[FeatureFrame],
) -> dict[str, IsolationForest]:
    """Train one IsolationForest per parameter from prior_frames.

    prior_frames intentionally span multiple lots (E2 step 3: pooled cross-lot history).
    Returns empty dict on cold start (no prior_frames).
    """
    prior_by_param: dict[str, list[FeatureFrame]] = {}
    for f in prior_frames:
        prior_by_param.setdefault(f.parameter, []).append(f)

    if_models: dict[str, IsolationForest] = {}
    for param, pframes in prior_by_param.items():
        if not pframes:
            continue
        X_prior = _value_matrix(pframes)
        if X_prior.shape[0] == 0:
            continue
        clf = IsolationForest(random_state=_RANDOM_STATE)
        clf.fit(X_prior)
        if_models[param] = clf

    return if_models


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _value_matrix(frames: list[FeatureFrame]) -> np.ndarray:
    """Feature matrix for IF and ECOD: [value_0h, value_24h] per frame."""
    if not frames:
        return np.empty((0, 2))
    rows = [[f.value_0h, f.value_24h] for f in frames]
    return np.array(rows, dtype=float)
