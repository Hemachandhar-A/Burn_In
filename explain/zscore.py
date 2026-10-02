"""P5.7 explain/zscore.py: per-parameter robust z-score table for one part, at one checkpoint.

Reads value/lot_median/z directly off FeatureFrame - no formula is re-derived here (AGENTS.md rule 1),
this is a read-only reshape of fields features.compute() already populated. Only "0h" and "24h" are
supported: FeatureFrame carries a named lot_median only for those two checkpoints (lot_median_0h/24h) -
"96h"/"168h" have a per-checkpoint robust_z entry but no corresponding named median field to pair it
with, so a table row for either would have nothing principled to put in the lot_median column.
"""
from contracts import FeatureFrame
from explain.models import ZScoreRow, ZScoreTable

_VALUE_FIELD = {"0h": "value_0h", "24h": "value_24h"}
_MEDIAN_FIELD = {"0h": "lot_median_0h", "24h": "lot_median_24h"}


def build_zscore_table(frames: list[FeatureFrame], checkpoint: str) -> ZScoreTable:
    """`frames`: every FeatureFrame (one per parameter) for a single part. Raises ValueError if
    `frames` is empty, spans more than one component_id, or `checkpoint` isn't "0h"/"24h"."""
    if checkpoint not in _VALUE_FIELD:
        raise ValueError(f"checkpoint must be one of {sorted(_VALUE_FIELD)}, got {checkpoint!r}")
    if not frames:
        raise ValueError("frames must not be empty")
    component_ids = {f.component_id for f in frames}
    if len(component_ids) > 1:
        raise ValueError(f"frames must be a single component's frames, got {sorted(component_ids)}")

    value_field = _VALUE_FIELD[checkpoint]
    median_field = _MEDIAN_FIELD[checkpoint]
    rows = [
        ZScoreRow(
            parameter=f.parameter,
            value=getattr(f, value_field),
            lot_median=getattr(f, median_field),
            z=f.robust_z.get(checkpoint, 0.0),
        )
        for f in sorted(frames, key=lambda f: f.parameter)
    ]
    return ZScoreTable(component_id=frames[0].component_id, checkpoint=checkpoint, rows=rows)
