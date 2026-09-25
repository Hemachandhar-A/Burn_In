"""E1 end-to-end: one call from (lot id, seed, family) to a production-facing LotDataset plus a separate
ground-truth sidecar.

Step 8: every Reading carries its elapsed burn-in time as an explicit numeric `checkpoint_hour` - the
actual hour the lot was read, not a column identity from an assumed 0/24/96/168 schedule. Schedules can be
irregular two ways: an arbitrary `checkpoint_hours` sequence, and/or `checkpoint_jitter_hours`, which
shifts each nominal readout by a lot-wide uniform offset (the whole lot comes out of the chamber together,
so every part shares one set of readout times). The pre-burn-in read at nominal 0h is never shifted: it
defines t = 0.

The ground-truth sidecar (LotGroundTruth) is a separate object from the LotDataset and is never embedded in
it: the dataset holds only contract fields (7.3: "ground-truth sidecar never leaks into the production
schema").

Lot status is derived from the *nominal* schedule: COMPLETE once it includes the 168h read, else
IN_PROGRESS - so a jittered 167.5h final read still counts as the full campaign.
"""
import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from contracts import LotDataset, Reading
from generator.baselines import generate_lot_baselines
from generator.families import GeneratorFamily, get_family
from generator.measurement import measure_lot
from generator.parameters import PARAMETERS
from generator.schema import LotBaseline, LotTrajectories, MeasurementTruth
from generator.trajectories import (
    DEFAULT_CHECKPOINT_HOURS,
    _check_finite,
    _validate_checkpoints,
    generate_lot_trajectories,
)

_FULL_CAMPAIGN_HOURS = 168.0
_JITTER_STREAM = 5  # SeedSequence spawn-key namespace, distinct from trajectories (1, 2) and measurement (3, 4)


@dataclass(frozen=True)
class LotGroundTruth:
    """Everything the harness needs to score a model on this lot - and nothing the model may see."""

    family: str
    seed: int
    nominal_checkpoint_hours: tuple[float, ...]
    baselines: LotBaseline  # lot centers/spreads, prevalence, per-part baseline and is_defective
    trajectories: LotTrajectories  # actual readout hours, noise-free values, defect type/Ea/onset/severity
    measurement: MeasurementTruth  # tester offsets, their reference-part estimates, reference values


@dataclass(frozen=True)
class GeneratedLot:
    dataset: LotDataset  # production-facing: what ingestion, the models and the API see
    ground_truth: LotGroundTruth  # sidecar: harness only


def _require_text(name: str, value) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")
    return value


def _jittered_hours(nominal: tuple[float, ...], jitter, seed: int) -> tuple[float, ...]:
    jitter = _check_finite("checkpoint_jitter_hours", jitter)
    if jitter < 0:
        raise ValueError(f"checkpoint_jitter_hours must be >= 0, got {jitter}")
    if jitter == 0:
        return nominal
    # Strictly under half the tightest gap keeps the actual schedule strictly increasing; a first read after
    # 0h can't be pulled below 0.
    min_gap = min((b - a for a, b in pairwise(nominal)), default=math.inf)
    if not jitter < min_gap / 2:
        raise ValueError(f"checkpoint_jitter_hours must be < half the smallest checkpoint gap ({min_gap / 2}), got {jitter}")
    if nominal[0] > 0 and jitter > nominal[0]:
        raise ValueError(f"checkpoint_jitter_hours must be <= the first checkpoint ({nominal[0]}), got {jitter}")
    rng = np.random.default_rng(np.random.SeedSequence(entropy=seed, spawn_key=(_JITTER_STREAM,)))
    # One draw per checkpoint, in order, including the unshifted 0h - so the k-th readout's shift never
    # depends on how many later checkpoints the schedule has (rule 6).
    shifts = rng.uniform(-jitter, jitter, len(nominal))
    return tuple(h if h == 0.0 else float(h + s) for h, s in zip(nominal, shifts))


def generate_lot(
    lot_id: str,
    part_number: str,
    seed: int,
    *,
    account_id: str,
    family: str | GeneratorFamily = "baseline",
    n_parts: int | None = None,
    checkpoint_hours=DEFAULT_CHECKPOINT_HOURS,
    checkpoint_jitter_hours: float = 0.0,
    manufacturer: str = "SYNTHETIC",
    date_code: str = "2601",
) -> GeneratedLot:
    """`account_id` is required (no placeholder default): every ingested lot is attributed to the account
    that loaded it (context.md 7.3) - the caller knows who that is, the generator doesn't."""
    _require_text("account_id", account_id)
    _require_text("manufacturer", manufacturer)
    _require_text("date_code", date_code)
    if isinstance(family, str):
        family = get_family(family)
    elif not isinstance(family, GeneratorFamily):
        raise TypeError(f"family must be a family name or GeneratorFamily, got {type(family).__name__}")
    n_parts = family.config.lot_size_default if n_parts is None else n_parts

    baselines = generate_lot_baselines(lot_id, part_number, n_parts, seed, family.config,
                                       die_correlation=family.die_correlation)
    seed = int(seed)  # validated by generate_lot_baselines
    nominal = _validate_checkpoints(checkpoint_hours)
    actual = _jittered_hours(nominal, checkpoint_jitter_hours, seed)
    trajectories = generate_lot_trajectories(baselines, seed, family.config, family.trajectory_params, actual)
    measured = measure_lot(trajectories, seed, family.measurement_params)

    readings = [
        Reading(
            component_id=part.component_id,
            lot_id=baselines.lot_id,
            part_number=baselines.part_number,
            manufacturer=manufacturer,
            date_code=date_code,
            parameter=name,
            checkpoint_hour=hour,
            value=measured.values[part.component_id][name][k],
            unit=spec.unit,
        )
        for part in baselines.parts
        for name, spec in PARAMETERS.items()
        for k, hour in enumerate(measured.checkpoint_hours)
    ]
    dataset = LotDataset(
        lot_id=baselines.lot_id,
        part_number=baselines.part_number,
        status="COMPLETE" if nominal[-1] >= _FULL_CAMPAIGN_HOURS else "IN_PROGRESS",
        readings=readings,
        account_id=account_id,
    )
    return GeneratedLot(
        dataset=dataset,
        ground_truth=LotGroundTruth(
            family=family.name,
            seed=seed,
            nominal_checkpoint_hours=nominal,
            baselines=baselines,
            trajectories=trajectories,
            measurement=measured.truth,
        ),
    )
