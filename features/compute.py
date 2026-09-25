"""Session P2.1 stub (IMPLEMENTATION_PLAN.md Part 10): fixed, correctly-shaped `FeatureFrame`
output so P3/P4 can build against the real contract before E8's real statistics land.

Real logic (deltas, robust stats, small-lot fallback, z-scores - E8 steps 1-5) is session P2.4.
"""
from contracts import FeatureFrame, LotDataset


def compute(lot: LotDataset) -> list[FeatureFrame]:
    """One canned `FeatureFrame` per (component_id, parameter) pair actually present in
    `lot.readings` - real identifiers, fixed placeholder feature values."""
    pairs = sorted({(r.component_id, r.parameter) for r in lot.readings})
    lot_size = len({r.component_id for r in lot.readings})
    return [
        FeatureFrame(
            component_id=component_id,
            lot_id=lot.lot_id,
            part_number=lot.part_number,
            parameter=parameter,
            value_0h=0.0,
            value_24h=0.0,
            value_96h=None,
            delta_24h=0.0,
            delta_96h=None,
            lot_median_0h=0.0,
            lot_median_24h=0.0,
            robust_z={"0h": 0.0, "24h": 0.0},
            lot_size=lot_size,
            used_pooled_fallback=lot_size < 30,  # context.md 5.16 - exact AEC-Q001 minimum
            elapsed_hours={"0h": 0.0, "24h": 24.0},
        )
        for component_id, parameter in pairs
    ]
