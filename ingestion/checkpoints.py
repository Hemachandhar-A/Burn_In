"""E7 step 4/9 support: mapping a real reading's exact `checkpoint_hour` to the nearest
nominal milestone (0h/24h/96h/168h), tolerant of real-world timing jitter.

Real burn-in readouts don't land on the nominal hour exactly (context.md 5.9, 7.2 - elapsed
time is an explicit numeric input specifically to support this). `merge.compute_status`
previously required `checkpoint_hour == 168.0` exactly, which a jittered 167.6h final read
would fail - a gap flagged in merge.py for this session's attention. This module gives every
consumer (merge's Complete trigger, quality's missing-checkpoint check, later features.py) one
shared tolerance rule instead of each guessing its own.
"""
NOMINAL_CHECKPOINTS: dict[str, float] = {"0h": 0.0, "24h": 24.0, "96h": 96.0, "168h": 168.0}

# A checkpoint within this fraction of the nominal hour (floor `_MIN_TOLERANCE_HOURS`) counts
# as that milestone. 10% mirrors the kind of readout-scheduling slop a real burn-in campaign
# sees; the floor keeps the 0h checkpoint (0.1 * 0 == 0) from requiring an exact match.
_TOLERANCE_FRAC = 0.10
_MIN_TOLERANCE_HOURS = 1.0


def label_for_hour(checkpoint_hour: float) -> str | None:
    """Returns the nominal checkpoint label (`"0h"`, `"24h"`, `"96h"`, `"168h"`) whose window
    `checkpoint_hour` falls in, or `None` if it matches none - still a valid reading (irregular
    checkpoints are allowed), just not one mapped to a named milestone."""
    best_label: str | None = None
    best_distance = float("inf")
    for label, nominal in NOMINAL_CHECKPOINTS.items():
        tolerance = max(_MIN_TOLERANCE_HOURS, nominal * _TOLERANCE_FRAC)
        distance = abs(checkpoint_hour - nominal)
        if distance <= tolerance and distance < best_distance:
            best_label, best_distance = label, distance
    return best_label
