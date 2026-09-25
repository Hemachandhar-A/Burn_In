"""E7 steps 3-4: incremental merge-by-part-ID, and the Complete/In-Progress trigger.

P2.3: `compute_status` now uses `checkpoints.label_for_hour`'s tolerance window instead of an
exact `checkpoint_hour == 168.0` match - real burn-in readouts don't land on the nominal hour
exactly (context.md 5.9, 7.2), so a jittered 167.6h final read still counts as the 168h read,
mirroring the tolerance the generator (E1) already applies to its own nominal schedule.
"""
from contracts import LotDataset, Reading
from ingestion.checkpoints import label_for_hour


def compute_status(readings: list[Reading]) -> str:
    """A lot is Complete only once one of its readings falls in the 168h checkpoint's tolerance
    window - a lot with readings past 168h but no 168h read itself stays In-Progress
    (essential-features.md E7 step 4)."""
    return "COMPLETE" if any(label_for_hour(r.checkpoint_hour) == "168h" for r in readings) else "IN_PROGRESS"


def merge_checkpoint(existing: LotDataset, new_readings: list[Reading]) -> LotDataset:
    """Merges a new checkpoint file's readings into a lot's growing history, matched by
    component_id (E7 step 3) - real burn-in data arrives as separate readout events over the
    campaign, not one pre-assembled file (context.md 5.4).

    Deduplicates on the natural key (component_id, parameter, checkpoint_hour): re-uploading
    the same checkpoint for the same part is a no-op, not a duplicate row.
    """
    existing_keys = {(r.component_id, r.parameter, r.checkpoint_hour) for r in existing.readings}
    merged_readings = list(existing.readings) + [
        r for r in new_readings if (r.component_id, r.parameter, r.checkpoint_hour) not in existing_keys
    ]
    return LotDataset(
        lot_id=existing.lot_id,
        part_number=existing.part_number,
        status=compute_status(merged_readings),
        readings=merged_readings,
        account_id=existing.account_id,
    )
