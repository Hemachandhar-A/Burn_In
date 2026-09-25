"""E5 step 1: the three named industry baselines every model is benchmarked against (context.md 1.6, 3.4 (3)).

    static absolute limits   a datasheet min/max per parameter, applied at every checkpoint
    fixed delta limits       space-spec style: |reading - pre-burn-in reading| against a fixed allowance
                             ("+/-X or +/-Y% of initial, whichever is greater"), computed after each burn-in
    AEC-Q001 PAT             robust mean +/- 6 robust sigma, robust mean = median, robust sigma = IQR / 1.35;
                             static PAT fits the limits once on a pooled reference population, dynamic PAT
                             (DPAT) recomputes them per lot

Every baseline returns the same frame, one row per (component, parameter):
    component_id, parameter, score, flagged, worst_checkpoint, evaluable
`score` is the part's worst exceedance ratio across checkpoints - measured deviation over allowed deviation -
so score > 1 is exactly "outside the limit" and a value on the limit passes. A continuous score (not just a
flag) is what lets the harness compare baselines and models at a fixed flag rate (E5 step 4).
`evaluable` is False where a baseline cannot judge the part at all (no limit for that parameter, no
pre-burn-in read for a delta, no finite reading): such a part is neither flagged nor passed, and is never
silently dropped or scored from an imputed value (AGENTS.md rule 7, context.md 5.9).

PAT and DPAT are grouped by (parameter, checkpoint); each actual readout hour is aligned to its nominal
checkpoint first, so a jittered 23.6h read is pooled with the other lots' 24h reads (E1 step 8).
"""
import math
import numbers
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from types import MappingProxyType

import numpy as np
import pandas as pd
from scipy.stats import iqr

from contracts import LotDataset, ScreeningConfig
from generator.parameters import PARAMETERS
from generator.trajectories import DEFAULT_CHECKPOINT_HOURS

PAT_SIGMA_MULTIPLIER = 6.0  # AEC-Q001: limits at robust mean +/- 6 robust sigma
ROBUST_SIGMA_DIVISOR = 1.35  # robust sigma = IQR / 1.35, as published (context.md 1.6) - not 1.349
PRE_BURN_IN_CHECKPOINT = 0.0

SCORE_COLUMNS = ["component_id", "parameter", "score", "flagged", "worst_checkpoint", "evaluable"]

# Disclosed harness defaults (context.md Part 8), not datasheet values - the generator is synthetic, so no
# real datasheet exists for its parts. Both are set from the generator's own healthy-population spread,
# which if anything favours the baselines: a real datasheet limit is written without knowing the lots.
_DATASHEET_GUARD_SIGMAS = 4.0  # static max limit at lot-center median + 4 total log-sigma (lot + die)
_DEFAULT_DELTA_RELATIVE = MappingProxyType({
    # Near the healthy 168h drift's upper tail: median drift 8% (Iddq, leakage) / 3% (delay), log-sigma 0.4.
    "iddq": 0.20,
    "leakage": 0.20,
    "prop_delay": 0.10,
})


def _positive_finite(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a real number, got {value!r}")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number, got {value!r}")
    return value


@dataclass(frozen=True)
class Limit:
    """A static datasheet limit. Positive values only: the limit is scored as a ratio (reading / max,
    min / reading), which is what a positive physical quantity (current, delay) makes meaningful."""

    lower: float | None = None
    upper: float | None = None

    def __post_init__(self) -> None:
        if self.lower is None and self.upper is None:
            raise ValueError("Limit needs a lower or an upper bound")
        for name in ("lower", "upper"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _positive_finite(f"Limit.{name}", getattr(self, name)))
        if self.lower is not None and self.upper is not None and not self.lower < self.upper:
            raise ValueError(f"Limit.lower must be < Limit.upper, got {self.lower} >= {self.upper}")


@dataclass(frozen=True)
class DeltaLimit:
    """Allowed |reading - pre-burn-in reading|: max(absolute, relative * |pre-burn-in reading|)."""

    absolute: float | None = None
    relative: float | None = None

    def __post_init__(self) -> None:
        if self.absolute is None and self.relative is None:
            raise ValueError("DeltaLimit needs an absolute or a relative allowance")
        for name in ("absolute", "relative"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _positive_finite(f"DeltaLimit.{name}", getattr(self, name)))

    def allowed(self, initial: np.ndarray) -> np.ndarray:
        absolute = np.full_like(initial, self.absolute or 0.0, dtype=float)
        relative = (self.relative or 0.0) * np.abs(initial)
        return np.maximum(absolute, relative)


def default_datasheet_limits() -> dict[str, Limit]:
    """A max limit per trained parameter, placed where the generator's healthy population almost never
    reaches - the way a datasheet guard-bands. See _DATASHEET_GUARD_SIGMAS."""
    limits = {}
    for name, spec in PARAMETERS.items():
        total_log_sigma = math.hypot(spec.lot_center_sigma, spec.die_sigma_base)
        limits[name] = Limit(upper=math.exp(spec.lot_center_mu + _DATASHEET_GUARD_SIGMAS * total_log_sigma))
    return limits


def default_delta_limits() -> dict[str, DeltaLimit]:
    return {name: DeltaLimit(relative=_DEFAULT_DELTA_RELATIVE[name]) for name in PARAMETERS}


# --- shared plumbing -----------------------------------------------------------------

def _require_dataset(dataset) -> LotDataset:
    if not isinstance(dataset, LotDataset):
        raise TypeError(f"expected a LotDataset, got {type(dataset).__name__}")
    return dataset


def checkpoint_frame(dataset: LotDataset, nominal_hours: Iterable[float] = DEFAULT_CHECKPOINT_HOURS) -> pd.DataFrame:
    """Long frame of the lot's readings with each actual readout hour aligned to its nominal checkpoint.
    Columns: component_id, parameter, checkpoint (nominal), checkpoint_hour (actual), value.

    A reading must lie strictly within half the tightest nominal gap of one checkpoint - the same bound the
    generator's jitter obeys - and each (component, parameter, checkpoint) may be read once."""
    _require_dataset(dataset)
    nominal = np.asarray(sorted(float(h) for h in nominal_hours), dtype=float)
    if nominal.size == 0:
        raise ValueError("nominal_hours must not be empty")
    tolerance = min((b - a for a, b in pairwise(nominal)), default=math.inf) / 2
    frame = pd.DataFrame(
        [(r.component_id, r.parameter, r.checkpoint_hour, r.value) for r in dataset.readings],
        columns=["component_id", "parameter", "checkpoint_hour", "value"],
    ).astype({"checkpoint_hour": float, "value": float})
    if frame.empty:
        frame.insert(2, "checkpoint", pd.Series(dtype=float))
        return frame
    hours = frame.checkpoint_hour.to_numpy()
    nearest = nominal[np.abs(hours[:, None] - nominal[None, :]).argmin(axis=1)]
    off = ~(np.abs(hours - nearest) < tolerance)
    if off.any():
        bad = sorted(set(hours[off].tolist()))
        raise ValueError(f"readout hours {bad} are not within {tolerance}h of any nominal checkpoint {nominal.tolist()}")
    frame.insert(2, "checkpoint", nearest)
    duplicated = frame.duplicated(["component_id", "parameter", "checkpoint"], keep=False)
    if duplicated.any():
        first = frame[duplicated].iloc[0]
        raise ValueError(f"duplicate readings for {first.component_id!r} {first.parameter!r} at checkpoint "
                         f"{first.checkpoint}h - ambiguous which one the baseline should judge")
    return frame.sort_values(["component_id", "parameter", "checkpoint"], kind="stable").reset_index(drop=True)


def _ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """numerator / denominator for a zero-width allowance: 0 when nothing deviates, inf when anything does.
    NaN propagates (an unreadable value stays unevaluable)."""
    numerator = np.asarray(numerator, dtype=float)
    denominator = np.broadcast_to(np.asarray(denominator, dtype=float), numerator.shape)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = numerator / denominator
    zero = denominator == 0
    out[zero] = np.where(numerator[zero] == 0, 0.0, np.inf)
    out[np.isnan(numerator) | np.isnan(denominator)] = np.nan
    return out


def _all_pairs(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[["component_id", "parameter"]].drop_duplicates().reset_index(drop=True)


def _summarize(pairs: pd.DataFrame, scored: pd.DataFrame) -> pd.DataFrame:
    """Reduce per-checkpoint `ratio` rows to one row per (component, parameter): the worst finite ratio and
    the checkpoint it came from. Pairs with no finite ratio are kept as unevaluable."""
    finite = scored[scored.ratio.notna()]
    if finite.empty:
        worst = pd.DataFrame(columns=["component_id", "parameter", "score", "worst_checkpoint"])
    else:
        # First checkpoint wins a tie, so the result doesn't depend on row order.
        idx = finite.sort_values("checkpoint", kind="stable").groupby(
            ["component_id", "parameter"], sort=False).ratio.idxmax()
        worst = finite.loc[idx, ["component_id", "parameter", "ratio", "checkpoint"]].rename(
            columns={"ratio": "score", "checkpoint": "worst_checkpoint"})
    out = pairs.merge(worst, on=["component_id", "parameter"], how="left")
    out["score"] = out.score.astype(float)
    out["worst_checkpoint"] = out.worst_checkpoint.astype(float)
    out["evaluable"] = out.score.notna()
    out["flagged"] = (out.score > 1.0).fillna(False).astype(bool)
    return out[SCORE_COLUMNS].sort_values(["component_id", "parameter"], kind="stable").reset_index(drop=True)


# --- static absolute limits ----------------------------------------------------------

def static_limit_scores(dataset: LotDataset, limits: Mapping[str, Limit]) -> pd.DataFrame:
    """Datasheet min/max at every checkpoint. Score = max(reading / upper, lower / reading)."""
    frame = checkpoint_frame(dataset)
    for name, limit in limits.items():
        if not isinstance(limit, Limit):
            raise TypeError(f"limits[{name!r}] must be a Limit, got {type(limit).__name__}")
    ratio = np.full(len(frame), np.nan)
    for name, limit in limits.items():
        rows = (frame.parameter == name).to_numpy()
        values = frame.value.to_numpy()[rows]
        sides = []
        if limit.upper is not None:
            sides.append(values / limit.upper)
        if limit.lower is not None:
            with np.errstate(divide="ignore"):
                sides.append(np.where(values > 0, limit.lower / values, np.inf))
        side_max = np.max(np.vstack(sides), axis=0)
        side_max[np.isnan(values)] = np.nan
        ratio[rows] = side_max
    return _summarize(_all_pairs(frame), frame.assign(ratio=ratio))


# --- fixed delta limits --------------------------------------------------------------

def fixed_delta_scores(dataset: LotDataset, limits: Mapping[str, DeltaLimit]) -> pd.DataFrame:
    """|reading - pre-burn-in (0h) reading| against a fixed allowance, at every post-burn-in checkpoint.
    Always measured from the 0h read, not the previous checkpoint - a slow cumulative drift must still fail."""
    frame = checkpoint_frame(dataset)
    for name, limit in limits.items():
        if not isinstance(limit, DeltaLimit):
            raise TypeError(f"limits[{name!r}] must be a DeltaLimit, got {type(limit).__name__}")
    initial = frame[frame.checkpoint == PRE_BURN_IN_CHECKPOINT][["component_id", "parameter", "value"]]
    later = frame[frame.checkpoint != PRE_BURN_IN_CHECKPOINT].merge(
        initial.rename(columns={"value": "initial"}), on=["component_id", "parameter"], how="left")
    ratio = np.full(len(later), np.nan)
    for name, limit in limits.items():
        rows = (later.parameter == name).to_numpy()
        init = later.initial.to_numpy()[rows]
        ratio[rows] = _ratio(np.abs(later.value.to_numpy()[rows] - init), limit.allowed(init))
    return _summarize(_all_pairs(frame), later.assign(ratio=ratio))


# --- AEC-Q001 PAT --------------------------------------------------------------------

def robust_center_sigma(values: Iterable[float]) -> tuple[float, float]:
    """(median, IQR / 1.35) over the finite values - AEC-Q001's robust mean and robust sigma."""
    array = np.asarray(list(values), dtype=float)
    array = array[np.isfinite(array)]
    if array.size == 0:
        raise ValueError("robust statistics need at least one finite value")
    return float(np.median(array)), float(iqr(array) / ROBUST_SIGMA_DIVISOR)


@dataclass(frozen=True)
class PatLimits:
    """Static PAT limits fitted on a pooled reference population of one part number. Keyed by
    (parameter, nominal checkpoint). Remembers its reference lots so it can refuse to score one of them."""

    part_number: str
    reference_lot_ids: frozenset[str]
    center: Mapping[tuple[str, float], float] = field(repr=False)
    sigma: Mapping[tuple[str, float], float] = field(repr=False)
    multiplier: float = PAT_SIGMA_MULTIPLIER

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", MappingProxyType(dict(self.center)))
        object.__setattr__(self, "sigma", MappingProxyType(dict(self.sigma)))

    def center_sigma(self, parameter: str, checkpoint: float) -> tuple[float, float]:
        key = (parameter, float(checkpoint))
        return self.center[key], self.sigma[key]


def _min_population(config: ScreeningConfig) -> int:
    if not isinstance(config, ScreeningConfig):
        raise TypeError(f"config must be a ScreeningConfig, got {type(config).__name__}")
    return config.small_lot_fallback_threshold


def fit_static_pat(reference_lots: Iterable[LotDataset], config: ScreeningConfig | None = None,
                   nominal_hours: Iterable[float] = DEFAULT_CHECKPOINT_HOURS) -> PatLimits:
    """Pool the reference lots (one part number - E7 step 9's pooling scope) and fit median / IQR-1.35 per
    (parameter, checkpoint). Each group needs at least the AEC-Q001 minimum population."""
    minimum = _min_population(ScreeningConfig() if config is None else config)
    nominal_hours = tuple(nominal_hours)
    lots = [_require_dataset(lot) for lot in reference_lots]
    if not lots:
        raise ValueError("static PAT needs at least one reference lot")
    part_numbers = {lot.part_number for lot in lots}
    if len(part_numbers) != 1:
        raise ValueError(f"static PAT pools one part number only, got part numbers {sorted(part_numbers)}")
    lot_ids = [lot.lot_id for lot in lots]
    if len(set(lot_ids)) != len(lot_ids):
        raise ValueError(f"duplicate reference lot ids {sorted({i for i in lot_ids if lot_ids.count(i) > 1})}")
    pooled = pd.concat([checkpoint_frame(lot, nominal_hours) for lot in lots], ignore_index=True)
    center, sigma = {}, {}
    for (parameter, checkpoint), group in pooled.groupby(["parameter", "checkpoint"], sort=True):
        finite = group.value[np.isfinite(group.value)]
        if len(finite) < minimum:
            raise ValueError(f"static PAT reference for {parameter!r} at {checkpoint}h has {len(finite)} finite "
                             f"readings, below the {minimum}-part AEC-Q001 minimum")
        center[(parameter, float(checkpoint))], sigma[(parameter, float(checkpoint))] = robust_center_sigma(finite)
    return PatLimits(part_number=part_numbers.pop(), reference_lot_ids=frozenset(lot_ids),
                     center=center, sigma=sigma)


def _pat_ratio(values: np.ndarray, center: float, sigma: float, multiplier: float) -> np.ndarray:
    return _ratio(np.abs(values - center), multiplier * sigma)


def _score_with_pooled(frame: pd.DataFrame, limits: PatLimits) -> np.ndarray:
    ratio = np.full(len(frame), np.nan)
    for (parameter, checkpoint), group in frame.groupby(["parameter", "checkpoint"], sort=False):
        key = (parameter, float(checkpoint))
        if key in limits.center:  # no reference for this group -> unevaluable, not passed
            ratio[group.index.to_numpy()] = _pat_ratio(group.value.to_numpy(), limits.center[key],
                                                       limits.sigma[key], limits.multiplier)
    return ratio


def _check_pat_scope(dataset: LotDataset, limits: PatLimits) -> None:
    if not isinstance(limits, PatLimits):
        raise TypeError(f"limits must be PatLimits, got {type(limits).__name__}")
    if dataset.part_number != limits.part_number:
        raise ValueError(f"lot part number {dataset.part_number!r} differs from the static PAT limits' part number "
                         f"{limits.part_number!r}")
    if dataset.lot_id in limits.reference_lot_ids:
        # Split by lot (AGENTS.md rule 8): the lot would be judged by limits it helped fit.
        raise ValueError(f"lot {dataset.lot_id!r} is in the static PAT reference population - score it with "
                         "limits fitted without it")


def static_pat_scores(dataset: LotDataset, limits: PatLimits,
                      nominal_hours: Iterable[float] = DEFAULT_CHECKPOINT_HOURS) -> pd.DataFrame:
    """|reading - pooled median| / (6 * pooled robust sigma), per (parameter, checkpoint)."""
    _require_dataset(dataset)
    _check_pat_scope(dataset, limits)
    frame = checkpoint_frame(dataset, nominal_hours)
    return _summarize(_all_pairs(frame), frame.assign(ratio=_score_with_pooled(frame, limits)))


def dynamic_pat_scores(dataset: LotDataset, config: ScreeningConfig | None = None,
                       fallback: PatLimits | None = None,
                       nominal_hours: Iterable[float] = DEFAULT_CHECKPOINT_HOURS) -> pd.DataFrame:
    """DPAT: the PAT formula with limits recomputed from this lot alone, per (parameter, checkpoint).

    A group with fewer finite readings than ScreeningConfig.small_lot_fallback_threshold (the AEC-Q001
    30-part minimum, context.md 5.16) is scored against the pooled `fallback` static PAT limits instead - or
    raises if none was given, rather than fitting robust statistics to a population too small to hold them.
    Adds a `limit_source` column: "pooled" if any of the row's checkpoints were judged against the pooled
    fallback, else "lot"."""
    minimum = _min_population(ScreeningConfig() if config is None else config)
    _require_dataset(dataset)
    if fallback is not None:
        _check_pat_scope(dataset, fallback)
    frame = checkpoint_frame(dataset, nominal_hours)
    ratio = np.full(len(frame), np.nan)
    source = np.full(len(frame), "lot", dtype=object)
    for (parameter, checkpoint), group in frame.groupby(["parameter", "checkpoint"], sort=False):
        rows = group.index.to_numpy()
        n_finite = int(np.isfinite(group.value).sum())
        if n_finite >= minimum:
            center, sigma = robust_center_sigma(group.value)
            ratio[rows] = _pat_ratio(group.value.to_numpy(), center, sigma, PAT_SIGMA_MULTIPLIER)
        elif fallback is not None:
            ratio[rows] = _score_with_pooled(group.reset_index(drop=True), fallback)
            source[rows] = "pooled"
        else:
            raise ValueError(f"lot {dataset.lot_id!r} has {n_finite} finite {parameter!r} readings at {checkpoint}h, "
                             f"below the {minimum}-part AEC-Q001 minimum - pass pooled static PAT limits as fallback")
    scored = frame.assign(ratio=ratio, pooled=source == "pooled")
    out = _summarize(_all_pairs(frame), scored)
    pooled = scored.groupby(["component_id", "parameter"]).pooled.any()
    out["limit_source"] = ["pooled" if pooled[(c, p)] else "lot" for c, p in zip(out.component_id, out.parameter)]
    return out


# --- part-level rollup ---------------------------------------------------------------

def part_level(scores: pd.DataFrame) -> pd.DataFrame:
    """One row per component: flagged if any parameter is flagged, score = its worst evaluable parameter's
    score, worst_parameter = that parameter (None if nothing about the part was evaluable)."""
    rows = []
    for component_id, group in scores.groupby("component_id", sort=True):
        evaluable = group[group.evaluable]
        if evaluable.empty:
            rows.append((component_id, math.nan, False, None, False))
            continue
        worst = evaluable.loc[evaluable.score.idxmax()]
        rows.append((component_id, float(worst.score), bool(group.flagged.any()), worst.parameter, True))
    return pd.DataFrame(rows, columns=["component_id", "score", "flagged", "worst_parameter", "evaluable"])
