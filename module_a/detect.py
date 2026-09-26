"""module_a/detect.py — real implementation through P3.2.

Sessions completed:
  P3.0  Stub — correctly-shaped fixed fake data
  P3.1  E2 steps 1-3: robust z-scalar, per-checkpoint MCD, pooled Isolation Forest
  P3.2  E2 steps 4-6: ECOD (PyOD), percentile-normalise + max-combine, direction-awareness cap

Contract (unchanged):
  Input:  list[FeatureFrame]                 — from features.compute() (P2)
          prior_frames: list[FeatureFrame]   — pooled cross-lot history for the same
                                               part number(s), used to train IF only.
  Output: list[ModuleAResult]               — one result per input frame, same order

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
  For absent scores (cold-start IF → None, small-lot MCD → None): contribute 0.0
  (most-benign interpretation — no signal, no severity boost).
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
        One FeatureFrame per (component_id, parameter) pair for the current lot.
    prior_frames:
        FeatureFrames from *previous* lots of the same part number(s), used as the
        Isolation Forest's training set only.  Omit or pass [] for cold start.

    Returns
    -------
    list[ModuleAResult]
        Same length and order as *frames*.  Empty input → empty output.
    """
    if not frames:
        return []

    if prior_frames is None:
        prior_frames = []

    # ------------------------------------------------------------------
    # Step 2 — MCD per checkpoint (lot-relative)
    # ------------------------------------------------------------------
    lot_size = frames[0].lot_size
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
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Step 3 — Isolation Forest (pooled cross-lot, NOT lot-relative)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Step 4 — ECOD (lot-relative, PyOD)
    # Group frames by parameter; fit one ECOD per parameter.
    # ------------------------------------------------------------------
    # Group current frames by parameter for ECOD.
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
    # Step 5 — Percentile-normalise each detector within the lot, then
    # max-combine. We need lot-wide arrays per detector.
    # Collect raw scores across all frames first, then rank.
    # ------------------------------------------------------------------
    n = len(frames)

    # Robust z scalars
    z_raw = np.array([
        abs(max(f.robust_z.values(), key=abs)) if f.robust_z else 0.0
        for f in frames
    ])

    # MCD distances (None → 0.0 for ranking purposes)
    mcd_raw = np.array([
        mcd_by_component.get(f.component_id, 0.0) if lot_size >= _MCD_LOT_SIZE_FLOOR else 0.0
        for f in frames
    ])

    # IF scores (None → 0.0 = most benign; note: sklearn IF score is negated anomaly,
    # so more negative = more anomalous; we negate to make higher = more anomalous).
    iso_available = np.array([
        f.parameter in if_models for f in frames
    ])
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

    z_pct = _pct(z_raw)
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

        # Step 3: IF score (already negated for ranking; restore sign for storage)
        iso_score: float | None = None
        if frame.parameter in if_models:
            X_cur = _value_matrix([frame])
            if X_cur.shape[0] > 0:
                # score_samples: lower = more anomalous (sklearn convention)
                iso_score = float(if_models[frame.parameter].score_samples(X_cur)[0])

        # Step 4: ECOD score
        ecod_score = ecod_scores_by_cid_param.get((frame.component_id, frame.parameter), 0.0)

        # Step 6: direction-awareness cap
        # Cap fires when: direction == below_median AND combined percentile is high enough
        # that it would pull severity toward REJECT territory.
        # severity_cap_reason populated now; severity_tier wired to thresholds in P3.3.
        severity_cap_reason: str | None = None
        if direction == "below_median" and combined[i] >= _CAP_PERCENTILE_THRESHOLD:
            severity_cap_reason = "below_median_direction_cap"

        results.append(ModuleAResult(
            component_id=frame.component_id,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _value_matrix(frames: list[FeatureFrame]) -> np.ndarray:
    """Feature matrix for IF and ECOD: [value_0h, value_24h] per frame."""
    if not frames:
        return np.empty((0, 2))
    rows = [[f.value_0h, f.value_24h] for f in frames]
    return np.array(rows, dtype=float)
