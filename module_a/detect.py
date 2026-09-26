"""module_a/detect.py — P3.0 STUB.

Session: P3.0 — Stub (IMPLEMENTATION_PLAN.md Part 10, P3 section)
Prerequisite: G0 (contracts frozen, both lockfiles clean)

Purpose
-------
Returns a correctly-shaped list[ModuleAResult] with fixed fake-but-valid scores
so that P5.1 can call detect() from the first day without waiting on P2.4's
real FeatureFrame production (R6 — stub your own output before someone needs it).

Contract
--------
Input:  list[FeatureFrame]   (from contracts.py — P2's output)
Output: list[ModuleAResult]  (from contracts.py — one result per input frame)

The function signature and return type are FROZEN and must not change in later
sessions (P3.1–P3.3 fill in real logic, they do not rename or reshape this call).

Fake values chosen to be plausible, never all-zero (which would look broken):
  - robust_z         : 0.8   (a mild positive deviation — plausible PASS)
  - mcd_distance     : 1.2 if lot_size >= 30, else None  (context.md 4.2 ceiling)
  - isolation_forest : None  (cold-start stub — conservative, always safe)
  - ecod_score       : 0.15  (low tail probability — PASS range)
  - direction        : "above_median"
  - severity_tier    : "PASS"
  - explainable_tags : all four keys present, values plausible
  - severity_cap_reason: None (no cap applied in stub)

AGENTS.md rules honoured here:
  R1  — output shape matches contracts.py exactly, no guessed fields
  R3  — only module_a/ is touched; contracts.py is read-only
  R4  — contracts.py is imported, never edited
  R6  — stub exists before P5.1 needs it
"""

from contracts import FeatureFrame, ModuleAResult

# ---------------------------------------------------------------------------
# Stub fixed values — plausible, non-zero, not algorithm output
# ---------------------------------------------------------------------------
_STUB_ROBUST_Z: float = 0.8
_STUB_MCD_LARGE_LOT: float = 1.2       # returned when lot_size >= 30
_STUB_ECOD_SCORE: float = 0.15

# MCD is undefined for lots below the 5-feature-MCD ceiling (context.md 4.2):
# n_samples > 5 * n_features  =>  n_samples > 15 (3 params × 5) but the plan
# uses the AEC-Q001 min of 30 as the practical threshold throughout.
_MCD_LOT_SIZE_FLOOR: int = 30


def detect(frames: list[FeatureFrame]) -> list[ModuleAResult]:
    """Return a ModuleAResult for every FeatureFrame in *frames*.

    P3.0 STUB — returns fixed fake data matching the contracted output shape.
    Real scoring logic is added in sessions P3.1–P3.3.

    Parameters
    ----------
    frames:
        One FeatureFrame per (component_id, parameter) pair, as produced by
        features.compute() (P2).  Any parameter string is accepted — Module A
        does not restrict to {iddq, leakage, prop_delay} (contracts.py note,
        context.md 5.9).

    Returns
    -------
    list[ModuleAResult]
        One result per frame, in the same order as *frames*.
        Empty input returns an empty list.
    """
    results: list[ModuleAResult] = []

    for frame in frames:
        # MCD is undefined for small lots (context.md 4.2 / plan 5.1 note).
        mcd_distance: float | None = (
            _STUB_MCD_LARGE_LOT if frame.lot_size >= _MCD_LOT_SIZE_FLOOR else None
        )

        result = ModuleAResult(
            component_id=frame.component_id,
            parameter=frame.parameter,
            robust_z=_STUB_ROBUST_Z,
            mcd_distance=mcd_distance,
            # Isolation Forest stub is always None — cold-start is the safest
            # default; the real detector in P3.1 will return a score once
            # cross-lot history exists for this part number.
            isolation_forest_score=None,
            ecod_score=_STUB_ECOD_SCORE,
            # All four detectors tagged: robust_z and mcd are explainable,
            # isolation_forest and ecod are not (E2 step 7 / AGENTS.md rule 11).
            explainable_tags={
                "robust_z": True,
                "mcd": True,
                "isolation_forest": False,
                "ecod": False,
            },
            direction="above_median",
            severity_tier="PASS",
            severity_cap_reason=None,
        )
        results.append(result)

    return results
