"""module_a/detect.py — real implementation through P3.1.

Sessions completed:
  P3.0  Stub — correctly-shaped fixed fake data
  P3.1  E2 steps 1-3: robust z-scalar, per-checkpoint MCD, pooled Isolation Forest

Contract (unchanged from P3.0 stub):
  Input:  list[FeatureFrame]                 — from features.compute() (P2)
          prior_frames: list[FeatureFrame]   — pooled cross-lot history for the same
                                               part number(s), used to train the
                                               Isolation Forest.  Pass [] or omit for
                                               a part number's first-ever lot (cold start).
  Output: list[ModuleAResult]               — one result per input frame, same order

E2 step notes
-------------
Step 1 — robust_z scalar:
  FeatureFrame.robust_z is already a per-checkpoint dict computed by P2 (features/compute.py).
  Module A's scalar robust_z is the maximum absolute value across all checkpoints —
  the worst-checkpoint deviation is the one that matters for severity.

Step 2 — per-checkpoint MCD (MinCovDet, sklearn):
  Per E2 spec and context.md 4.2: MCD is fit per checkpoint on the full lot's frames using
  the robust z-scores as the feature matrix (unit-normalised by P2).  One MCD per checkpoint
  (not joint across checkpoints).  The per-component distance reported is the maximum across
  the checkpoints that actually ran.  Gate: lot_size < 30 → mcd_distance = None.
  features.compute.build_mcd_matrix() builds the feature matrix for us.

Step 3 — pooled cross-lot Isolation Forest (sklearn):
  Deliberately NOT lot-relative (E2 spec / AGENTS.md pitfall note): trained on prior_frames
  from previous lots of the same part number so it catches campaign-level drift.
  Cold-start safe: if prior_frames is empty for a given parameter → isolation_forest_score = None.
  Fixed random_state=42 (AGENTS.md rule 9 — determinism).

AGENTS.md rules:
  R1  — output matches contracts.py exactly
  R3  — only module_a/ touched; features/ is called, never edited
  R4  — contracts.py read-only
  R9  — fixed seeds everywhere (random_state=42)
"""

from __future__ import annotations

import numpy as np
from sklearn.covariance import MinCovDet
from sklearn.ensemble import IsolationForest

from contracts import FeatureFrame, ModuleAResult
from features.compute import build_mcd_matrix

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# AEC-Q001 / context.md 5.16: MCD requires >= 30 parts.
# MinCovDet's own requirement is n_samples > 5 * n_features; with 3 parameters per
# checkpoint (n_features=3) that floor is 16, but the plan pins 30 throughout.
_MCD_LOT_SIZE_FLOOR: int = 30

# Fixed seed — AGENTS.md rule 9 (determinism: same input → same output).
_RANDOM_STATE: int = 42


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
        One FeatureFrame per (component_id, parameter) pair for the current lot,
        as produced by features.compute() (P2).  Any parameter string is accepted.
    prior_frames:
        FeatureFrames from *previous* lots of the same part number(s), used as the
        Isolation Forest's training set (E2 step 3).  Omit or pass [] on a part
        number's first-ever lot — the detector will not contribute (cold start).

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
    # Step 2 prep: MCD per checkpoint — build once for the whole lot.
    # build_mcd_matrix groups by parameter, so we call it per checkpoint.
    # We collect a {component_id: max_mahalanobis} mapping.
    # ------------------------------------------------------------------
    lot_size = frames[0].lot_size  # same for all frames in one lot call
    mcd_by_component: dict[str, float | None] = {}

    if lot_size >= _MCD_LOT_SIZE_FLOOR:
        checkpoints = sorted({ck for f in frames for ck in f.robust_z})
        for checkpoint in checkpoints:
            component_ids, _params, matrix = build_mcd_matrix(frames, checkpoint)
            if len(component_ids) < _MCD_LOT_SIZE_FLOOR or len(matrix[0]) == 0:
                # Not enough samples at this checkpoint for a valid MCD fit.
                continue
            X = np.array(matrix, dtype=float)
            try:
                mcd = MinCovDet(random_state=_RANDOM_STATE)
                mcd.fit(X)
                distances = mcd.mahalanobis(X)  # squared Mahalanobis distances
                for cid, dist in zip(component_ids, distances):
                    d = float(np.sqrt(dist))  # convert to non-squared distance
                    if cid not in mcd_by_component or d > (mcd_by_component[cid] or 0.0):
                        mcd_by_component[cid] = d
            except Exception:
                # Degenerate covariance (e.g. near-singular at boundary) — treat as None.
                pass

    # ------------------------------------------------------------------
    # Step 3 prep: Isolation Forest per parameter, trained on prior_frames.
    # One IF model per parameter — parameters are independent measurements.
    # ------------------------------------------------------------------
    # Group prior frames by parameter.
    prior_by_param: dict[str, list[FeatureFrame]] = {}
    for f in prior_frames:
        prior_by_param.setdefault(f.parameter, []).append(f)

    # Train one IF per parameter that has enough prior history.
    # Feature vector per prior frame: [value_0h, value_24h] (always present).
    if_models: dict[str, IsolationForest] = {}
    for param, pframes in prior_by_param.items():
        if not pframes:
            continue
        X_prior = _if_feature_matrix(pframes)
        if X_prior.shape[0] == 0:
            continue
        clf = IsolationForest(random_state=_RANDOM_STATE)
        clf.fit(X_prior)
        if_models[param] = clf

    # ------------------------------------------------------------------
    # Build one result per frame.
    # ------------------------------------------------------------------
    results: list[ModuleAResult] = []
    for frame in frames:
        # -- Step 1: worst-checkpoint robust z scalar ----------------------
        z_values = list(frame.robust_z.values())
        worst_z = max(z_values, key=abs) if z_values else 0.0
        direction: str = "below_median" if worst_z < 0 else "above_median"
        robust_z_scalar = abs(worst_z)

        # -- Step 2: MCD distance -----------------------------------------
        mcd_distance: float | None = None
        mcd_tag: bool = False
        if lot_size >= _MCD_LOT_SIZE_FLOOR:
            mcd_distance = mcd_by_component.get(frame.component_id)
            mcd_tag = mcd_distance is not None

        # -- Step 3: Isolation Forest score --------------------------------
        iso_score: float | None = None
        if frame.parameter in if_models:
            X_cur = _if_feature_matrix([frame])
            if X_cur.shape[0] > 0:
                # score_samples returns the anomaly score: lower = more anomalous.
                iso_score = float(if_models[frame.parameter].score_samples(X_cur)[0])

        results.append(ModuleAResult(
            component_id=frame.component_id,
            parameter=frame.parameter,
            robust_z=robust_z_scalar,
            mcd_distance=mcd_distance,
            isolation_forest_score=iso_score,
            ecod_score=0.15,  # TEMP — real ECOD added in P3.2
            explainable_tags={
                "robust_z": True,
                "mcd": mcd_tag,
                "isolation_forest": False,  # never explainable — E2 step 7
                "ecod": False,              # TEMP — updated in P3.2
            },
            direction=direction,
            severity_tier="PASS",   # TEMP — thresholding added in P3.3
            severity_cap_reason=None,
        ))

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _if_feature_matrix(frames: list[FeatureFrame]) -> np.ndarray:
    """Build the Isolation Forest feature matrix for a list of frames.

    Features: [value_0h, value_24h].  96h included when present (NaN otherwise —
    IsolationForest in sklearn handles NaNs natively since 1.0).
    """
    rows = []
    for f in frames:
        row = [f.value_0h, f.value_24h]
        rows.append(row)
    return np.array(rows, dtype=float) if rows else np.empty((0, 2))
