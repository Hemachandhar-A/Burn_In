"""E5 step 2: held-out test sets, one per generator family (E1 step 9), each with a guaranteed minimum count of
every defect archetype (context.md 7.12).

The minimum is met by generating more lots - never by forcing defects into a lot or editing the generator -
so each lot keeps its family's natural prevalence and archetype mix, and the set is simply as many lots as it
takes for the rarest archetype to reach the minimum. That makes the set's size a function of the minimum
alone, decoupled from lot size and from however many lots the live demo dataset contains.

Every lot comes from generator.lot.generate_lot; the ground truth used for counting is the generator's own
sidecar (LotGroundTruth), which never enters the LotDataset a model sees.

Lot ids are "<prefix>-<family>-<index>": the family is part of the id so each family's lots are independent
draws. (The generator deliberately does *not* mix the family into the seed, so the same lot id under two
families would be common-random-numbers twins - right for a paired family comparison, wrong for a held-out
set, where a model tuned on one family's lots must not meet their twins in another's.)
"""
import numbers
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import pandas as pd

from generator.families import HELD_OUT_FAMILY_NAMES, GeneratorFamily, resolve_family
from generator.lot import GeneratedLot, generate_lot
from generator.trajectories import DEFECT_ARCHETYPES

# Disclosed harness default (context.md Part 8), not evidence-derived: at 30 true positives per archetype a
# single miss moves per-archetype recall by ~3 points rather than 25 (the "3 of 4 vs 4 of 4" case in 7.12).
DEFAULT_MIN_PER_ARCHETYPE = 30
DEFAULT_MIN_LOTS = 5  # enough lots that lot-level statistics (DPAT, lot medians) are not one lot's quirks
DEFAULT_MAX_LOTS = 2000  # a runaway guard, not a target: the baseline family needs ~30-40 lots at the default
HELD_OUT_ACCOUNT_ID = "harness"
HELD_OUT_PART_NUMBER = "PN-HELDOUT"
HELD_OUT_LOT_PREFIX = "HO"


def _positive_int(name: str, value) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")
    return int(value)


def _require_lot(lot) -> GeneratedLot:
    if not isinstance(lot, GeneratedLot):
        raise TypeError(f"expected a GeneratedLot, got {type(lot).__name__}")
    return lot


def _defect_types(lot: GeneratedLot) -> list[str]:
    _require_lot(lot)
    return [part.defect_type for part in lot.ground_truth.trajectories.parts if part.is_defective]


def archetype_counts(lots: Iterable[GeneratedLot]) -> dict[str, int]:
    """Defective-part count per archetype across the lots, from the ground-truth sidecar; every archetype is
    present, zero-filled."""
    counts = dict.fromkeys(DEFECT_ARCHETYPES, 0)
    for lot in lots:
        for defect_type in _defect_types(lot):
            counts[defect_type] += 1
    return counts


def ground_truth_labels(lot: GeneratedLot) -> pd.DataFrame:
    """One row per part: lot_id, component_id, family, is_defective, defect_type (None if healthy)."""
    truth = _require_lot(lot).ground_truth
    return pd.DataFrame(
        [(part.lot_id, part.component_id, truth.family, bool(part.is_defective), part.defect_type)
         for part in truth.trajectories.parts],
        columns=["lot_id", "component_id", "family", "is_defective", "defect_type"],
    )


@dataclass(frozen=True)
class HeldOutTestSet:
    """Self-certifying: an instance can only exist if it actually meets its guarantee - every lot from
    `family`, unique lot ids, at least `min_lots` lots and `min_per_archetype` defects of every archetype."""

    family: str
    seed: int
    min_per_archetype: int
    min_lots: int
    lots: tuple[GeneratedLot, ...]
    archetype_counts: Mapping[str, int] = field(init=False)

    def __post_init__(self) -> None:
        lots = tuple(_require_lot(lot) for lot in self.lots)
        object.__setattr__(self, "lots", lots)
        object.__setattr__(self, "min_per_archetype", _positive_int("min_per_archetype", self.min_per_archetype))
        object.__setattr__(self, "min_lots", _positive_int("min_lots", self.min_lots))
        object.__setattr__(self, "seed", _seed(self.seed))
        if not isinstance(self.family, str) or not self.family.strip():
            raise ValueError(f"family must be a non-empty str, got {self.family!r}")
        strays = sorted({lot.ground_truth.family for lot in lots} - {self.family})
        if strays:
            raise ValueError(f"held-out set for family {self.family!r} contains lots from family {strays}")
        seeds = sorted({lot.ground_truth.seed for lot in lots} - {self.seed})
        if seeds:
            raise ValueError(f"held-out set claims seed {self.seed} but contains lots generated with seed {seeds}")
        part_numbers = sorted({lot.dataset.part_number for lot in lots})
        if len(part_numbers) > 1:
            # One part number per set: pooling (static PAT, cross-lot models) is scoped to a part number.
            raise ValueError(f"held-out set mixes part numbers {part_numbers}")
        ids = [lot.dataset.lot_id for lot in lots]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate lot ids in held-out set: {sorted({i for i in ids if ids.count(i) > 1})}")
        if len(lots) < self.min_lots:
            raise ValueError(f"held-out set has {len(lots)} lots, below min_lots={self.min_lots}")
        counts = archetype_counts(lots)
        short = {name: n for name, n in counts.items() if n < self.min_per_archetype}
        if short:
            raise ValueError(f"held-out set is below the {self.min_per_archetype}-per-archetype minimum: {short}")
        object.__setattr__(self, "archetype_counts", MappingProxyType(counts))

    @property
    def lot_ids(self) -> tuple[str, ...]:
        return tuple(lot.dataset.lot_id for lot in self.lots)

    @property
    def n_parts(self) -> int:
        return sum(len(lot.ground_truth.trajectories.parts) for lot in self.lots)

    @property
    def n_defective(self) -> int:
        return sum(self.archetype_counts.values())

    def labels(self) -> pd.DataFrame:
        return pd.concat([ground_truth_labels(lot) for lot in self.lots], ignore_index=True)


def _seed(seed) -> int:
    if isinstance(seed, bool) or not isinstance(seed, numbers.Integral):
        raise TypeError(f"seed must be an int, got {type(seed).__name__}")
    if seed < 0:
        raise ValueError(f"seed must be >= 0, got {seed}")
    return int(seed)


def _prefix(prefix) -> str:
    if not isinstance(prefix, str):
        raise TypeError(f"lot_id_prefix must be a str, got {type(prefix).__name__}")
    if not prefix.strip():
        raise ValueError(f"lot_id_prefix must be a non-empty string, got {prefix!r}")
    return prefix


def generate_held_out_set(
    family: str | GeneratorFamily,
    *,
    seed: int,
    min_per_archetype: int = DEFAULT_MIN_PER_ARCHETYPE,
    min_lots: int = DEFAULT_MIN_LOTS,
    max_lots: int = DEFAULT_MAX_LOTS,
    n_parts: int | None = None,
    part_number: str = HELD_OUT_PART_NUMBER,
    lot_id_prefix: str = HELD_OUT_LOT_PREFIX,
    account_id: str = HELD_OUT_ACCOUNT_ID,
    checkpoint_jitter_hours: float = 0.0,
) -> HeldOutTestSet:
    """Generate lots of one family, in index order, until every archetype has at least `min_per_archetype`
    defective parts and at least `min_lots` lots exist - then stop. Deterministic in all arguments.
    Raises RuntimeError if `max_lots` lots don't reach the minimum. `checkpoint_jitter_hours` is passed to the
    generator (E1 step 8) to test robustness to irregular readout times; the schedule itself stays the full
    0/24/96/168h campaign, so every counted defect - latent ones included - is active before the last read."""
    family = resolve_family(family)
    min_per_archetype = _positive_int("min_per_archetype", min_per_archetype)
    min_lots = _positive_int("min_lots", min_lots)
    max_lots = _positive_int("max_lots", max_lots)
    if max_lots < min_lots:
        raise ValueError(f"max_lots ({max_lots}) must be >= min_lots ({min_lots})")
    seed = _seed(seed)
    lot_id_prefix = _prefix(lot_id_prefix)
    if family.config.defect_prevalence_range[1] <= 0:
        raise ValueError(f"family {family.name!r} has defect prevalence range {family.config.defect_prevalence_range}"
                         " - it can never produce a defective part, so no archetype minimum is reachable")

    lots: list[GeneratedLot] = []
    counts = archetype_counts(())
    while len(lots) < min_lots or min(counts.values()) < min_per_archetype:
        if len(lots) == max_lots:
            raise RuntimeError(f"family {family.name!r}: {max_lots} lots (max_lots) gave archetype counts {counts}, "
                               f"short of the {min_per_archetype}-per-archetype minimum")
        lot = generate_lot(f"{lot_id_prefix}-{family.name}-{len(lots):04d}", part_number, seed,
                           account_id=account_id, family=family, n_parts=n_parts,
                           checkpoint_jitter_hours=checkpoint_jitter_hours)
        lots.append(lot)
        for defect_type in _defect_types(lot):
            counts[defect_type] += 1
    return HeldOutTestSet(family=family.name, seed=seed, min_per_archetype=min_per_archetype,
                          min_lots=min_lots, lots=tuple(lots))


def generate_held_out_sets(
    *,
    seed: int,
    families: Iterable[str | GeneratorFamily] = HELD_OUT_FAMILY_NAMES,
    **kwargs,
) -> Mapping[str, HeldOutTestSet]:
    """One held-out set per family (all five by default), keyed by family name in the order given."""
    if isinstance(families, (str, bytes, GeneratorFamily)) or not isinstance(families, Iterable):
        raise TypeError(f"families must be a collection of family names or GeneratorFamily objects, got {families!r}")
    resolved = [resolve_family(f) for f in families]
    if not resolved:
        raise ValueError("families must name at least one generator family")
    names = [f.name for f in resolved]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate families requested: {names}")
    return MappingProxyType({f.name: generate_held_out_set(f, seed=seed, **kwargs) for f in resolved})
