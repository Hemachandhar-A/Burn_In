"""E7 step 9: scope enforcement - any downstream cross-lot pooling (E2's Isolation Forest,
E3's global-per-part-number model, E8 step 3's small-lot fallback) must stay within the same
part number. A single guard here, called by every future pooling site, instead of each one
re-deriving the same check (context.md 7.3: "the system is scoped per part number, with
cross-lot history never pooling across different device types").
"""
from contracts import LotDataset


class CrossPartNumberScopeError(ValueError):
    """Raised when a caller tries to pool `LotDataset`s spanning more than one part number."""


def assert_same_part_number(datasets: list[LotDataset]) -> str:
    """Returns the shared `part_number` if every dataset agrees; raises otherwise. An empty
    list has no part number to assert, which is a caller bug, not a scope violation."""
    if not datasets:
        raise ValueError("assert_same_part_number called with no datasets")
    part_numbers = {dataset.part_number for dataset in datasets}
    if len(part_numbers) > 1:
        raise CrossPartNumberScopeError(
            f"cross-lot pooling must stay within one part number, got {sorted(part_numbers)}"
        )
    return next(iter(part_numbers))


def filter_by_part_number(datasets: list[LotDataset], part_number: str) -> list[LotDataset]:
    """The scoped subset of `datasets` matching `part_number` - the actual enforcement point
    for a pooled cross-lot reference (E8 step 3's small-lot fallback, Isolation Forest's
    training set): callers pool over this function's output, never the unfiltered list."""
    return [dataset for dataset in datasets if dataset.part_number == part_number]
