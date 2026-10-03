"""module_a/settings.py - the Module A scoring switch and the V1 ("absolute") constants (session I2a).

`MODULE_A_SCORING` selects how fusion/pipeline.py scores Module A:

    rank      (default) today's behaviour: rank-percentile of each detector within the lot, max-combined, tiers from
              config/harness_thresholds.yaml. `module_a_scoring_config()` returns None, so detect() runs unchanged.
    absolute  V1 (docs/SCORING_EXPERIMENT_RESULT.md): z-score -> normal tail, MCD -> chi-square tail, max-combined,
              severity s = -log10 p, tiers decided on s with the two thresholds below. `combined_severity` stays in
              [0, 1) as a monotone transform of s (display scale only) and `severity_log10p` carries s.

The switch is read on every call (not at import) so a process can be pointed at either mode by its environment.
"""
from __future__ import annotations

import math
import os

# ONE named place for the V1 tier thresholds, on the -log10(p) scale. Tuned by the cost-sensitive optimiser
# (harness.scoring.tune_threshold: REVIEW at FN:FP 20:1, REJECT at 10:1) on the TUNING side, seed 6101, of the scoring
# experiment (docs/SCORING_EXPERIMENT_RESULT.md; exact tuned values 2.9561 and 3.4186). SYNTHETIC labels; not
# derived from field data. They are NOT part of contracts.HarnessThresholds or config/harness_thresholds.yaml, which
# hold rank percentiles on a different scale.
ABSOLUTE_REVIEW_THRESHOLD: float = 2.956
ABSOLUTE_REJECT_THRESHOLD: float = 3.419

# V1F (session I2c, docs/ADOPTION_PLAN_ADDENDUM.md): in absolute mode the MCD leg runs only for lots of at least this many
# parts (the standard lot size from the zero-failure derivation); below it only the robust-z leg scores. Why: the chi-square
# reference for the MCD distance is badly over-confident at small n (clean-lot MCD-leg flag share 0.147 at n = 30, 0.072 at
# n = 50, 0.050 at n = 60, 0.032 at n = 77; docs/evidence_data/adoption/calibration_summary.md), reproduced on pure Gaussian
# data, so it is the estimator at finite n. The tier thresholds below were tuned at n = 77. Rank mode is unaffected.
MCD_MIN_PARTS_ABSOLUTE: int = 77

# Display transform T(s) = 1 - exp(-s / S0). S0 = 5 maps REJECT (3.419) to 0.495 and REVIEW (2.956) to 0.447, so the
# tiers straddle the middle of a 0-1 scale; s = 15 reads 0.95. Cosmetic: tiers and ranks are decided on s.
DISPLAY_S0: float = 5.0
_T_CEILING: float = 1.0 - 1e-12  # keep combined_severity strictly below 1.0

_MODES = ("rank", "absolute")


def module_a_scoring() -> str:
    """The configured mode, from the environment variable MODULE_A_SCORING; "rank" when unset or empty."""
    value = os.environ.get("MODULE_A_SCORING", "").strip().lower()
    if not value:
        return "rank"
    if value not in _MODES:
        raise ValueError(f"MODULE_A_SCORING must be one of {_MODES}, got {value!r}")
    return value


def module_a_scoring_config():
    """The `scoring` argument for module_a.detect.detect: None for "rank" (the unchanged default path)."""
    if module_a_scoring() == "rank":
        return None
    from module_a.scoring import ScoringConfig

    return ScoringConfig(calibration="absolute", combination="max",
                         review_threshold=ABSOLUTE_REVIEW_THRESHOLD, reject_threshold=ABSOLUTE_REJECT_THRESHOLD,
                         display_s0=DISPLAY_S0, mcd_min_parts=MCD_MIN_PARTS_ABSOLUTE)


def display_transform(s: float, s0: float = DISPLAY_S0) -> float:
    """T(s) = 1 - exp(-s / s0), monotone increasing, 0 at s = 0, clamped below 1.0."""
    s = max(float(s), 0.0)
    return min(-math.expm1(-s / s0), _T_CEILING)


def severity_index_phrase(s: float | None) -> str | None:
    """Calibration-agnostic reading of s = -log10 p: the index and the flag threshold, with no probability or 'one in N'
    claim (session I2c: V1's p-values are not calibrated; the thresholds act as tuned severity cutoffs near 77 parts).
    None when there is no s (rank mode)."""
    if s is None:
        return None
    return f"severity index {s:.1f}; flag threshold {ABSOLUTE_REVIEW_THRESHOLD:.2f}"
