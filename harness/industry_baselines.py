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
"Outside" is decided against the limit as a reviewer computes it by hand (center + 6 sigma, initial +
allowance), and the score is reconciled to that decision, so float rounding in the ratio can never flag a
value sitting exactly on its published limit, or pass one a single ulp beyond it.
`evaluable` is False where a baseline cannot judge the part at all (no limit for that parameter, no
pre-burn-in read for a delta, no finite reading, a population below the PAT minimum with no pooled fallback):
such a part is neither flagged nor passed, and is never silently dropped or scored from an imputed value
(AGENTS.md rule 7, context.md 5.9). A non-finite reading is treated as no measurement, not as a flag.

PAT and DPAT are grouped by (parameter, checkpoint); each actual readout hour is aligned to its nominal
checkpoint first, so a jittered 23.6h read is pooled with the other lots' 24h reads (E1 step 8).
`horizon_hours` drops every checkpoint after the horizon before anything is computed - DPAT statistics
included - so a baseline compared against an early 0h/24h decision never sees later reads (AGENTS.md rule 6).
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
_FRAME_COLUMNS = ["component_id", "parameter", "checkpoint", "checkpoint_hour", "value", "unit"]
_JUST_OVER_ONE = math.nextafter(1.0, math.inf)

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


# --- argument validation -------------------------------------------------------------

def _real(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a real number, got {value!r}")
    try:
        return float(value)
    except OverflowError:  # an int too large for a float (e.g. 10**400)
        raise ValueError(f"{name} is too large to represent as a float") from None


def _positive_finite(name: str, value) -> float:
    value = _real(name, value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number, got {value!r}")
    return value


def _optional_unit(name: str, unit) -> str | None:
    if unit is None:
        return None
    if not isinstance(unit, str):
        raise TypeError(f"{name} must be a str or None, got {type(unit).__name__}")
    if not unit.strip():
        raise ValueError(f"{name} must be a non-empty string, got {unit!r}")
    return unit


def _nominal_schedule(nominal_hours) -> tuple[float, ...]:
    if isinstance(nominal_hours, (str, bytes)) or not isinstance(nominal_hours, Iterable):
        raise TypeError(f"nominal_hours must be a sequence of hours, got {nominal_hours!r}")
    hours = [_real("nominal_hours entry", h) for h in nominal_hours]
    if not hours:
        raise ValueError("nominal_hours must not be empty")
    if not all(math.isfinite(h) and h >= 0 for h in hours):
        raise ValueError(f"nominal_hours must be finite and >= 0, got {hours}")
    if len(set(hours)) != len(hours):
        raise ValueError(f"nominal_hours must not repeat a checkpoint, got {hours}")
    return tuple(sorted(hours))


def _horizon(horizon_hours) -> float | None:
    if horizon_hours is None:
        return None
    horizon = _real("horizon_hours", horizon_hours)
    if not (math.isfinite(horizon) and horizon >= 0):
        raise ValueError(f"horizon_hours must be finite and >= 0, got {horizon_hours!r}")
    return horizon


def _require_dataset(dataset) -> LotDataset:
    if not isinstance(dataset, LotDataset):
        raise TypeError(f"expected a LotDataset, got {type(dataset).__name__}")
    return dataset


def _require_mapping(name: str, value, item_type: type) -> Mapping:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping of parameter -> {item_type.__name__}, got {type(value).__name__}")
    for key, item in value.items():
        if not isinstance(item, item_type):
            raise TypeError(f"{name}[{key!r}] must be a {item_type.__name__}, got {type(item).__name__}")
    return value


def _min_population(config: ScreeningConfig | None) -> int:
    config = ScreeningConfig() if config is None else config
    if not isinstance(config, ScreeningConfig):
        raise TypeError(f"config must be a ScreeningConfig, got {type(config).__name__}")
    if config.small_lot_fallback_threshold < 1:
        raise ValueError(f"config.small_lot_fallback_threshold must be >= 1, got {config.small_lot_fallback_threshold}")
    return config.small_lot_fallback_threshold


# --- limit types -----------------------------------------------------------------------

@dataclass(frozen=True)
class Limit:
    """A static datasheet limit. Positive values only: the limit is scored as a ratio (reading / max,
    min / reading), which is what a positive physical quantity (current, delay) makes meaningful.
    `unit`, if given, must match the readings' unit - a uA limit never judges nA readings."""

    lower: float | None = None
    upper: float | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        if self.lower is None and self.upper is None:
            raise ValueError("Limit needs a lower or an upper bound")
        for name in ("lower", "upper"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _positive_finite(f"Limit.{name}", getattr(self, name)))
        if self.lower is not None and self.upper is not None and not self.lower < self.upper:
            raise ValueError(f"Limit.lower must be < Limit.upper, got {self.lower} >= {self.upper}")
        object.__setattr__(self, "unit", _optional_unit("Limit.unit", self.unit))


@dataclass(frozen=True)
class DeltaLimit:
    """Allowed |reading - pre-burn-in reading|: max(absolute, relative * |pre-burn-in reading|).
    `unit` is only meaningful for an absolute allowance; a relative one is unit-free."""

    absolute: float | None = None
    relative: float | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        if self.absolute is None and self.relative is None:
            raise ValueError("DeltaLimit needs an absolute or a relative allowance")
        for name in ("absolute", "relative"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _positive_finite(f"DeltaLimit.{name}", getattr(self, name)))
        object.__setattr__(self, "unit", _optional_unit("DeltaLimit.unit", self.unit))

    def allowed(self, initial: np.ndarray) -> np.ndarray:
        initial = np.asarray(initial, dtype=float)
        return np.maximum(np.full_like(initial, self.absolute or 0.0), (self.relative or 0.0) * np.abs(initial))


def default_datasheet_limits() -> dict[str, Limit]:
    """A max limit per trained parameter, in the generator's unit, placed where the generator's healthy
    population almost never reaches - the way a datasheet guard-bands. See _DATASHEET_GUARD_SIGMAS.
    A fresh dict on every call."""
    limits = {}
    for name, spec in PARAMETERS.items():
        total_log_sigma = math.hypot(spec.lot_center_sigma, spec.die_sigma_base)
        limits[name] = Limit(upper=math.exp(spec.lot_center_mu + _DATASHEET_GUARD_SIGMAS * total_log_sigma),
                             unit=spec.unit)
    return limits


def default_delta_limits() -> dict[str, DeltaLimit]:
    """Relative-only, so unit-free. A fresh dict on every call."""
    return {name: DeltaLimit(relative=_DEFAULT_DELTA_RELATIVE[name]) for name in PARAMETERS}


# --- shared plumbing -----------------------------------------------------------------

def checkpoint_frame(dataset: LotDataset, nominal_hours: Iterable[float] = DEFAULT_CHECKPOINT_HOURS,
                     horizon_hours: float | None = None) -> pd.DataFrame:
    """Long frame of the lot's readings with each actual readout hour aligned to its nominal checkpoint.
    Columns: component_id, parameter, checkpoint (nominal), checkpoint_hour (actual), value, unit.

    Rejects a malformed lot rather than guessing: a reading from another lot or part number, a negative or
    non-finite readout hour, an hour not strictly within half the tightest nominal gap of one checkpoint (the
    bound the generator's jitter obeys), two readings of one (component, parameter, checkpoint), or one
    parameter recorded in two units. Non-finite values become NaN (no measurement). Checkpoints after
    `horizon_hours` are dropped."""
    _require_dataset(dataset)
    nominal = np.asarray(_nominal_schedule(nominal_hours))
    horizon = _horizon(horizon_hours)
    for reading in dataset.readings:
        if reading.lot_id != dataset.lot_id:
            raise ValueError(f"reading for {reading.component_id!r} belongs to lot {reading.lot_id!r}, "
                             f"not the dataset's lot {dataset.lot_id!r}")
        if reading.part_number != dataset.part_number:
            raise ValueError(f"reading for {reading.component_id!r} has part number {reading.part_number!r}, "
                             f"not the dataset's part number {dataset.part_number!r}")
    frame = pd.DataFrame(
        [(r.component_id, r.parameter, math.nan, r.checkpoint_hour, r.value, r.unit) for r in dataset.readings],
        columns=_FRAME_COLUMNS,
    ).astype({"checkpoint": float, "checkpoint_hour": float, "value": float})
    if frame.empty:
        return frame
    hours = frame.checkpoint_hour.to_numpy()
    if not np.isfinite(hours).all():
        raise ValueError(f"readout hours must be finite, got {sorted(set(hours[~np.isfinite(hours)].tolist()))}")
    if (hours < 0).any():
        raise ValueError(f"readout hours must not be negative, got {sorted(set(hours[hours < 0].tolist()))}")
    tolerance = min((b - a for a, b in pairwise(nominal)), default=math.inf) / 2
    nearest = nominal[np.abs(hours[:, None] - nominal[None, :]).argmin(axis=1)]
    off = ~(np.abs(hours - nearest) < tolerance)
    if off.any():
        bad = sorted(set(hours[off].tolist()))
        raise ValueError(f"readout hours {bad} are not within {tolerance}h of any nominal checkpoint {nominal.tolist()}")
    frame["checkpoint"] = nearest
    duplicated = frame.duplicated(["component_id", "parameter", "checkpoint"], keep=False)
    if duplicated.any():
        first = frame[duplicated].iloc[0]
        raise ValueError(f"duplicate readings for {first.component_id!r} {first.parameter!r} at checkpoint "
                         f"{first.checkpoint}h - ambiguous which one the baseline should judge")
    units = frame.groupby("parameter").unit.unique()
    mixed = {p: sorted(u) for p, u in units.items() if len(u) > 1}
    if mixed:
        raise ValueError(f"parameters recorded in more than one unit within lot {dataset.lot_id!r}: {mixed}")
    frame.loc[~np.isfinite(frame.value), "value"] = math.nan
    return _within_horizon(frame, horizon)


def _within_horizon(frame: pd.DataFrame, horizon: float | None) -> pd.DataFrame:
    if horizon is not None:
        frame = frame[frame.checkpoint <= horizon]
    return frame.sort_values(["component_id", "parameter", "checkpoint"], kind="stable").reset_index(drop=True)


def _prepare(dataset: LotDataset, nominal_hours, horizon_hours) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(every measured (component, parameter) pair, the readings within the horizon). The pair set is taken
    before the horizon cut, so a part read only after the horizon stays in the output as unevaluable - the
    row set never depends on the horizon."""
    horizon = _horizon(horizon_hours)
    full = checkpoint_frame(dataset, nominal_hours)
    return _all_pairs(full), _within_horizon(full, horizon)


def _frame_units(frame: pd.DataFrame) -> dict[str, str]:
    return dict(zip(frame.parameter, frame.unit))


def _check_limit_units(frame: pd.DataFrame, limits: Mapping, what: str) -> None:
    units = _frame_units(frame)
    for parameter, limit in limits.items():
        if limit.unit is not None and parameter in units and units[parameter] != limit.unit:
            raise ValueError(f"{what} for {parameter!r} is in unit {limit.unit!r} but the readings are in "
                             f"{units[parameter]!r}")


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


def _reconcile(ratio: np.ndarray, outside: np.ndarray) -> np.ndarray:
    """Make `ratio > 1` agree exactly with the limit comparison, which is the authority."""
    ratio = np.array(ratio, dtype=float)
    measured = ~np.isnan(ratio)
    ratio[measured & outside & ~(ratio > 1.0)] = _JUST_OVER_ONE
    ratio[measured & ~outside & (ratio > 1.0)] = 1.0
    return ratio


def _all_pairs(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[["component_id", "parameter"]].drop_duplicates().reset_index(drop=True)


def _summarize(pairs: pd.DataFrame, scored: pd.DataFrame) -> pd.DataFrame:
    """Reduce per-checkpoint `ratio` rows to one row per (component, parameter): the worst finite ratio and
    the checkpoint it came from. Pairs with no finite ratio are kept as unevaluable."""
    finite = scored[scored.ratio.notna()]
    if finite.empty:
        worst = pd.DataFrame({"component_id": pd.Series(dtype=object), "parameter": pd.Series(dtype=object),
                              "score": pd.Series(dtype=float), "worst_checkpoint": pd.Series(dtype=float)})
    else:
        # First checkpoint wins a tie, so the result doesn't depend on row order.
        idx = finite.sort_values(["component_id", "parameter", "checkpoint"], kind="stable").groupby(
            ["component_id", "parameter"], sort=False).ratio.idxmax()
        worst = finite.loc[idx, ["component_id", "parameter", "ratio", "checkpoint"]].rename(
            columns={"ratio": "score", "checkpoint": "worst_checkpoint"})
    out = pairs.merge(worst, on=["component_id", "parameter"], how="left")
    out["score"] = out.score.astype(float)
    out["worst_checkpoint"] = out.worst_checkpoint.astype(float)
    out["evaluable"] = out.score.notna()
    out["flagged"] = (out.score > 1.0).astype(bool)
    return out[SCORE_COLUMNS].sort_values(["component_id", "parameter"], kind="stable").reset_index(drop=True)


def _band_ratio(values: np.ndarray, center, half_width) -> np.ndarray:
    """|value - center| / half_width, reconciled to the published band [center - half_width, center + half_width]."""
    values = np.asarray(values, dtype=float)
    center = np.asarray(center, dtype=float)
    half_width = np.asarray(half_width, dtype=float)
    with np.errstate(invalid="ignore"):
        outside = (values > center + half_width) | (values < center - half_width)
    return _reconcile(_ratio(np.abs(values - center), half_width), outside)


# --- static absolute limits ----------------------------------------------------------

def static_limit_scores(dataset: LotDataset, limits: Mapping[str, Limit],
                        nominal_hours: Iterable[float] = DEFAULT_CHECKPOINT_HOURS,
                        horizon_hours: float | None = None) -> pd.DataFrame:
    """Datasheet min/max at every checkpoint. Score = max(reading / upper, lower / reading)."""
    _require_mapping("limits", limits, Limit)
    pairs, frame = _prepare(dataset, nominal_hours, horizon_hours)
    _check_limit_units(frame, limits, "datasheet limit")
    ratio = np.full(len(frame), np.nan)
    for name, limit in limits.items():
        rows = (frame.parameter == name).to_numpy()
        values = frame.value.to_numpy()[rows]
        sides, outside = [], np.zeros(values.shape, dtype=bool)
        if limit.upper is not None:
            sides.append(values / limit.upper)
            outside |= values > limit.upper
        if limit.lower is not None:
            with np.errstate(divide="ignore", invalid="ignore"):
                sides.append(np.where(values > 0, limit.lower / values, np.inf))
            outside |= values < limit.lower
        side_max = np.max(np.vstack(sides), axis=0)
        side_max[np.isnan(values)] = np.nan
        ratio[rows] = _reconcile(side_max, outside)
    return _summarize(pairs, frame.assign(ratio=ratio))


# --- fixed delta limits --------------------------------------------------------------

def fixed_delta_scores(dataset: LotDataset, limits: Mapping[str, DeltaLimit],
                       nominal_hours: Iterable[float] = DEFAULT_CHECKPOINT_HOURS,
                       horizon_hours: float | None = None) -> pd.DataFrame:
    """|reading - pre-burn-in (0h) reading| against a fixed allowance, at every post-burn-in checkpoint.
    Always measured from the 0h read, not the previous checkpoint - a slow cumulative drift must still fail.
    A part with no finite 0h read is unevaluable: its delta is never taken from a guessed initial value."""
    _require_mapping("limits", limits, DeltaLimit)
    schedule = _nominal_schedule(nominal_hours)
    if PRE_BURN_IN_CHECKPOINT not in schedule:
        raise ValueError("fixed delta limits are measured from the pre-burn-in (0h) read, but the nominal schedule "
                         f"{list(schedule)} has no 0h checkpoint")
    pairs, frame = _prepare(dataset, schedule, horizon_hours)
    _check_limit_units(frame, {p: lim for p, lim in limits.items() if lim.absolute is not None}, "delta limit")
    initial = frame[frame.checkpoint == PRE_BURN_IN_CHECKPOINT][["component_id", "parameter", "value"]]
    later = frame[frame.checkpoint != PRE_BURN_IN_CHECKPOINT].merge(
        initial.rename(columns={"value": "initial"}), on=["component_id", "parameter"], how="left")
    ratio = np.full(len(later), np.nan)
    for name, limit in limits.items():
        rows = (later.parameter == name).to_numpy()
        init = later.initial.to_numpy()[rows]
        ratio[rows] = _band_ratio(later.value.to_numpy()[rows], init, limit.allowed(init))
    return _summarize(pairs, later.assign(ratio=ratio))


# --- AEC-Q001 PAT --------------------------------------------------------------------

def robust_center_sigma(values: Iterable[float]) -> tuple[float, float]:
    """(median, IQR / 1.35) over the finite values - AEC-Q001's robust mean and robust sigma. Quartiles use
    linear interpolation between order statistics (numpy/scipy's default)."""
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise TypeError(f"values must be an iterable of numbers, got {type(values).__name__}")
    array = np.asarray(list(values))
    if array.size and array.dtype.kind not in "fiu":  # rejects numeric strings, bools, None, mixed types
        raise TypeError(f"values must be numbers, got elements of dtype {array.dtype}")
    array = array.astype(float)
    array = array[np.isfinite(array)]
    if array.size == 0:
        raise ValueError("robust statistics need at least one finite value")
    return float(np.median(array)), float(iqr(array) / ROBUST_SIGMA_DIVISOR)


def _group_key(key, schedule: tuple[float, ...]) -> tuple[str, float]:
    if not isinstance(key, tuple) or len(key) != 2:
        raise TypeError(f"PAT group keys must be (parameter, checkpoint) pairs, got {key!r}")
    parameter, checkpoint = key
    if not isinstance(parameter, str):
        raise TypeError(f"PAT group parameter must be a str, got {parameter!r}")
    checkpoint = _real("checkpoint", checkpoint)
    if checkpoint not in schedule:
        raise ValueError(f"PAT group checkpoint {checkpoint}h is not on the limits' schedule {list(schedule)}")
    return parameter, checkpoint


@dataclass(frozen=True)
class PatLimits:
    """Static PAT limits fitted on a pooled reference population of one part number, keyed by
    (parameter, nominal checkpoint). Remembers its reference lots (so it can refuse to score one of them),
    the unit of every parameter, the checkpoint schedule it was fitted on, and the groups that were too small
    to fit (`insufficient`) - those are unevaluable when scored, not passed."""

    part_number: str
    reference_lot_ids: frozenset[str]
    center: Mapping[tuple[str, float], float] = field(repr=False)
    sigma: Mapping[tuple[str, float], float] = field(repr=False)
    units: Mapping[str, str] = field(repr=False)
    nominal_hours: tuple[float, ...]
    insufficient: frozenset[tuple[str, float]] = frozenset()
    multiplier: float = PAT_SIGMA_MULTIPLIER

    def __post_init__(self) -> None:
        if not isinstance(self.part_number, str) or not self.part_number.strip():
            raise ValueError(f"PatLimits.part_number must be a non-empty str, got {self.part_number!r}")
        if isinstance(self.reference_lot_ids, (str, bytes)):
            raise TypeError("PatLimits.reference_lot_ids must be a collection of lot ids, not one string")
        ids = frozenset(self.reference_lot_ids)
        if not all(isinstance(i, str) for i in ids):
            raise TypeError("PatLimits.reference_lot_ids must be lot id strings")
        schedule = _nominal_schedule(self.nominal_hours)
        center = {_group_key(k, schedule): _real("center", v) for k, v in dict(self.center).items()}
        sigma = {_group_key(k, schedule): _real("sigma", v) for k, v in dict(self.sigma).items()}
        insufficient = frozenset(_group_key(k, schedule) for k in self.insufficient)
        if set(center) != set(sigma):
            raise ValueError("PatLimits.center and PatLimits.sigma must have the same (parameter, checkpoint) keys")
        if not all(math.isfinite(v) for v in center.values()):
            raise ValueError("PatLimits.center values must be finite")
        if not all(math.isfinite(v) and v >= 0 for v in sigma.values()):
            raise ValueError("PatLimits.sigma values must be finite and >= 0")
        units = dict(self.units)
        missing = {p for p, _ in center} - set(units)
        if missing:
            raise ValueError(f"PatLimits.units is missing a unit for fitted parameters {sorted(missing)}")
        for p, u in units.items():
            _optional_unit(f"PatLimits.units[{p!r}]", u)
        object.__setattr__(self, "reference_lot_ids", ids)
        object.__setattr__(self, "center", MappingProxyType(center))
        object.__setattr__(self, "sigma", MappingProxyType(sigma))
        object.__setattr__(self, "units", MappingProxyType(units))
        object.__setattr__(self, "nominal_hours", schedule)
        object.__setattr__(self, "insufficient", insufficient)
        object.__setattr__(self, "multiplier", _positive_finite("PatLimits.multiplier", self.multiplier))

    def center_sigma(self, parameter: str, checkpoint: float) -> tuple[float, float]:
        key = (parameter, float(checkpoint))
        return self.center[key], self.sigma[key]

    def limits(self, parameter: str, checkpoint: float) -> tuple[float, float]:
        """The published (lower, upper) limits: center -/+ multiplier * sigma."""
        center, sigma = self.center_sigma(parameter, checkpoint)
        return center - self.multiplier * sigma, center + self.multiplier * sigma


def fit_static_pat(reference_lots: Iterable[LotDataset], config: ScreeningConfig | None = None,
                   nominal_hours: Iterable[float] = DEFAULT_CHECKPOINT_HOURS) -> PatLimits:
    """Pool the reference lots (one part number - E7 step 9's pooling scope, one unit per parameter) and fit
    median / IQR-1.35 per (parameter, checkpoint). A group below the AEC-Q001 minimum population is skipped
    and recorded in `insufficient`; raises if no group reaches it."""
    minimum = _min_population(config)
    if isinstance(reference_lots, (LotDataset, str, bytes)) or not isinstance(reference_lots, Iterable):
        raise TypeError("reference_lots must be a collection of LotDataset objects, "
                        f"got {type(reference_lots).__name__}")
    nominal_hours = _nominal_schedule(nominal_hours)
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
    units = pooled.groupby("parameter").unit.unique()
    mixed = {p: sorted(u) for p, u in units.items() if len(u) > 1}
    if mixed:
        raise ValueError(f"reference lots record parameters in different units: {mixed}")
    center, sigma, insufficient = {}, {}, set()
    for (parameter, checkpoint), group in pooled.groupby(["parameter", "checkpoint"], sort=True):
        key = (parameter, float(checkpoint))
        finite = group.value[np.isfinite(group.value)]
        if len(finite) < minimum:
            insufficient.add(key)
            continue
        center[key], sigma[key] = robust_center_sigma(finite)
    if not center:
        raise ValueError(f"no (parameter, checkpoint) group in the static PAT reference reaches the {minimum}-part "
                         f"AEC-Q001 minimum of finite readings")
    return PatLimits(part_number=part_numbers.pop(), reference_lot_ids=frozenset(lot_ids), center=center,
                     sigma=sigma, units={p: u[0] for p, u in units.items()}, nominal_hours=nominal_hours,
                     insufficient=frozenset(insufficient))


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


def _check_pat_units(frame: pd.DataFrame, limits: PatLimits) -> None:
    for parameter, unit in _frame_units(frame).items():
        if parameter in limits.units and limits.units[parameter] != unit:
            raise ValueError(f"static PAT limits for {parameter!r} are in unit {limits.units[parameter]!r} but the "
                             f"readings are in {unit!r}")


def _pat_schedule(nominal_hours, limits: PatLimits | None) -> tuple[float, ...]:
    if nominal_hours is None:
        return limits.nominal_hours if limits is not None else tuple(DEFAULT_CHECKPOINT_HOURS)
    schedule = _nominal_schedule(nominal_hours)
    if limits is not None and schedule != limits.nominal_hours:
        raise ValueError(f"nominal schedule {list(schedule)} differs from the schedule the static PAT limits were "
                         f"fitted on {list(limits.nominal_hours)}")
    return schedule


def _score_with_pooled(frame: pd.DataFrame, limits: PatLimits) -> np.ndarray:
    ratio = np.full(len(frame), np.nan)
    for (parameter, checkpoint), group in frame.groupby(["parameter", "checkpoint"], sort=False):
        key = (parameter, float(checkpoint))
        if key in limits.center:  # no reference for this group -> unevaluable, not passed
            center, sigma = limits.center[key], limits.sigma[key]
            ratio[frame.index.get_indexer(group.index)] = _band_ratio(group.value.to_numpy(), center,
                                                                      limits.multiplier * sigma)
    return ratio


def static_pat_scores(dataset: LotDataset, limits: PatLimits, nominal_hours: Iterable[float] | None = None,
                      horizon_hours: float | None = None) -> pd.DataFrame:
    """|reading - pooled median| / (6 * pooled robust sigma), per (parameter, checkpoint), on the schedule the
    limits were fitted on."""
    _require_dataset(dataset)
    _check_pat_scope(dataset, limits)
    pairs, frame = _prepare(dataset, _pat_schedule(nominal_hours, limits), horizon_hours)
    _check_pat_units(frame, limits)
    return _summarize(pairs, frame.assign(ratio=_score_with_pooled(frame, limits)))


def dynamic_pat_scores(dataset: LotDataset, config: ScreeningConfig | None = None,
                       fallback: PatLimits | None = None, nominal_hours: Iterable[float] | None = None,
                       horizon_hours: float | None = None) -> pd.DataFrame:
    """DPAT: the PAT formula with limits recomputed from this lot alone, per (parameter, checkpoint).

    A group with fewer finite readings than ScreeningConfig.small_lot_fallback_threshold (the AEC-Q001
    30-part minimum, context.md 5.16) is judged against the pooled `fallback` static PAT limits instead, or
    left unevaluable when there is no fallback (or it has no limits for that group) - never judged on robust
    statistics too small to hold, and never taking the rest of the lot down with it. Adds a `limit_source`
    column: "pooled" if any of the row's checkpoints used the fallback, else "lot" if any used the lot's own
    limits, else "none"."""
    minimum = _min_population(config)
    _require_dataset(dataset)
    if fallback is not None:
        _check_pat_scope(dataset, fallback)
    pairs, frame = _prepare(dataset, _pat_schedule(nominal_hours, fallback), horizon_hours)
    if fallback is not None:
        _check_pat_units(frame, fallback)
    ratio = np.full(len(frame), np.nan)
    source = np.full(len(frame), "none", dtype=object)
    for (parameter, checkpoint), group in frame.groupby(["parameter", "checkpoint"], sort=False):
        rows = frame.index.get_indexer(group.index)
        n_finite = int(np.isfinite(group.value).sum())
        if n_finite >= minimum:
            center, sigma = robust_center_sigma(group.value)
            ratio[rows] = _band_ratio(group.value.to_numpy(), center, PAT_SIGMA_MULTIPLIER * sigma)
            source[rows] = "lot"
        elif fallback is not None and (parameter, float(checkpoint)) in fallback.center:
            ratio[rows] = _score_with_pooled(group, fallback)
            source[rows] = "pooled"
    scored = frame.assign(ratio=ratio, source=source)
    out = _summarize(pairs, scored)
    sources = scored.groupby(["component_id", "parameter"]).source.agg(set).to_dict()
    out["limit_source"] = [
        "pooled" if "pooled" in s else "lot" if "lot" in s else "none"
        for s in (sources.get((c, p), set()) for c, p in zip(out.component_id, out.parameter))
    ]
    return out


# --- part-level rollup ---------------------------------------------------------------

def part_level(scores: pd.DataFrame) -> pd.DataFrame:
    """One row per component: flagged if any parameter is flagged, score = its worst evaluable parameter's
    score, worst_parameter = that parameter (alphabetically first on a tie; None if nothing about the part
    was evaluable)."""
    if not isinstance(scores, pd.DataFrame):
        raise TypeError(f"scores must be a baseline score DataFrame, got {type(scores).__name__}")
    missing = [c for c in ("component_id", "parameter", "score", "flagged", "evaluable") if c not in scores.columns]
    if missing:
        raise ValueError(f"scores is missing columns {missing}")
    rows = []
    for component_id, group in scores.groupby("component_id", sort=True):
        evaluable = group[group.evaluable].sort_values("parameter", kind="stable")
        if evaluable.empty:
            rows.append((component_id, math.nan, False, None, False))
            continue
        worst = evaluable.loc[evaluable.score.idxmax()]
        rows.append((component_id, float(worst.score), bool(group.flagged.any()), worst.parameter, True))
    return pd.DataFrame(rows, columns=["component_id", "score", "flagged", "worst_parameter", "evaluable"])
