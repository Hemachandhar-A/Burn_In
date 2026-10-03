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

# Display transform T(s) = 1 - exp(-s / S0). S0 = 5 maps REJECT (3.419) to 0.495 and REVIEW (2.956) to 0.447, so the
# tiers straddle the middle of a 0-1 scale; s = 15 reads 0.95. Cosmetic: tiers and ranks are decided on s.
DISPLAY_S0: float = 5.0
_T_CEILING: float = 1.0 - 1e-12  # keep combined_severity strictly below 1.0

RARITY_DISPLAY_CAP: int = 15  # "1 in 10^15 or rarer"

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
                         display_s0=DISPLAY_S0)


def display_transform(s: float, s0: float = DISPLAY_S0) -> float:
    """T(s) = 1 - exp(-s / s0), monotone increasing, 0 at s = 0, clamped below 1.0."""
    s = max(float(s), 0.0)
    return min(-math.expm1(-s / s0), _T_CEILING)


def rarity_phrase(s: float | None) -> str | None:
    """Plain-language reading of s = -log10 p, with a display cap. None when there is no s (rank mode)."""
    if s is None:
        return None
    if s < 1.0:
        return "within the range of healthy parts"
    if s >= RARITY_DISPLAY_CAP:
        return f"more extreme than 1 in 10^{RARITY_DISPLAY_CAP} healthy parts or rarer, assuming a near-Gaussian healthy spread"
    return f"more extreme than about 1 in 10^{int(round(s))} healthy parts, assuming a near-Gaussian healthy spread"
