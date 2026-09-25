"""E7 steps 3-4: incremental merge-by-part-ID, and the Complete/In-Progress trigger.

`_FULL_CAMPAIGN_HOURS` mirrors generator/lot.py's own constant deliberately - real burn-in
data has no separate "nominal schedule" the way the generator does (which tolerates a
jittered 167.5h final read as still meeting a *planned* 168h checkpoint); for ingested data,
a reading's `checkpoint_hour` must land exactly on 168.0 to count as the 168h read. No
tolerance window is defined for real-world timing slop yet - not needed to close out this
session's synthetic-fixture scope, but worth the Lead's attention before P2.3 touches real
data.
"""
from contracts import LotDataset, Reading

_FULL_CAMPAIGN_HOURS = 168.0


def compute_status(readings: list[Reading]) -> str:
    """A lot is Complete only once one of its readings is at the 168h checkpoint - a lot with
    readings past 168h but no 168h read itself stays In-Progress (essential-features.md E7
    step 4)."""
    return "COMPLETE" if any(r.checkpoint_hour == _FULL_CAMPAIGN_HOURS for r in readings) else "IN_PROGRESS"


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
