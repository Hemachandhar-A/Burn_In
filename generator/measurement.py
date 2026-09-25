"""E1 step 7: what a real tester does to the physical trajectory before it becomes a reading -
an additive tester offset (corrected via simulated reference parts), proportional measurement noise,
and quantization to the tester's resolution.

Per checkpoint (each checkpoint is its own tester session, so the offset is redrawn per checkpoint):
    raw        = true * (1 + noise_frac * z) + offset          z ~ N(0, 1), or unit-variance Student-t
    offset_hat = mean(raw_ref - true_ref)                      over the lot's reference parts
    reading    = max(resolution, round((raw - offset_hat) / resolution) * resolution)

Reference parts are characterized golden units kept outside the burn-in chamber: their true values are
known and do not drift, so any systematic shift in their readings is the tester's offset. They are
tester-side ground truth only - never emitted as production readings (see MeasurementTruth).

Disclosed defaults, not measured values (context.md 8.3: "no source gave an exact ATE noise percentage;
set as an adjustable default"): the noise fractions, resolutions, offset scales and reference-part count.
The resolution floor is a stated simplification: a reading never goes to zero or negative, which a real
tester can report for a sub-resolution signal, but every downstream ratio assumes a positive reading.

Randomness comes from SeedSequence streams separate from the baseline/trajectory streams, drawn in
checkpoint order, so a checkpoint's readings never depend on which later checkpoints exist (rule 6).
"""
import math
import numbers
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

import numpy as np

from generator.parameters import PARAMETERS
from generator.schema import LotTrajectories, MeasuredLot, MeasurementTruth, PartTrajectory
from generator.trajectories import _check_finite, _validate_checkpoints

# Spawn-key namespaces - distinct from trajectories.py's _LOT_STREAM (1) and _PART_STREAM (2).
_MEASUREMENT_LOT_STREAM = 3
_MEASUREMENT_PART_STREAM = 4
# At 0.5, Gaussian noise already pushes ~2% of raw readings to <= 0 (z < -2), which the resolution floor
# then absorbs; any larger and the floor would dominate the tails instead of being a rare edge.
_MAX_NOISE_FRAC = 0.5
# Relative float rounding error on a raw reading after the add/subtract steps (a few machine epsilons).
_PRECISION_GUARD = 4 * np.finfo(float).eps


def _frozen_per_parameter(name: str, value, lo: float, lo_inclusive: bool, hi: float | None = None):
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping of parameter -> value, got {type(value).__name__}")
    if set(value) != set(PARAMETERS):
        raise ValueError(f"{name} must cover exactly {sorted(PARAMETERS)}, got {sorted(value)}")
    out = {}
    for param in PARAMETERS:
        v = _check_finite(f"{name}[{param}]", value[param])
        if (v < lo) if lo_inclusive else (v <= lo):
            raise ValueError(f"{name}[{param}] must be {'>=' if lo_inclusive else '>'} {lo}, got {v}")
        if hi is not None and v > hi:
            raise ValueError(f"{name}[{param}] must be <= {hi}, got {v}")
        out[param] = v
    # A private read-only copy: neither the caller's dict nor a shared family registry can be mutated.
    return MappingProxyType(out)


@dataclass(frozen=True, eq=False)
class MeasurementParams:
    noise_frac: Mapping[str, float] = field(
        default_factory=lambda: {"iddq": 0.02, "leakage": 0.02, "prop_delay": 0.005}
    )  # 1-sigma proportional noise; timing measurements are tighter than current measurements
    resolution: Mapping[str, float] = field(
        default_factory=lambda: {"iddq": 0.01, "leakage": 0.01, "prop_delay": 0.001}
    )  # tester quantization step, in the parameter's unit (uA, nA, ns)
    tester_offset_sigma: Mapping[str, float] = field(
        default_factory=lambda: {"iddq": 0.5, "leakage": 0.2, "prop_delay": 0.05}
    )  # 1-sigma additive offset per tester session, in the parameter's unit (a few % of a typical lot center)
    n_reference_parts: int = 5
    noise_tail_df: float | None = None  # None = Gaussian; a finite df = Student-t rescaled to unit variance

    def __post_init__(self) -> None:
        object.__setattr__(self, "noise_frac",
                           _frozen_per_parameter("noise_frac", self.noise_frac, 0.0, True, _MAX_NOISE_FRAC))
        object.__setattr__(self, "resolution", _frozen_per_parameter("resolution", self.resolution, 0.0, False))
        object.__setattr__(self, "tester_offset_sigma",
                           _frozen_per_parameter("tester_offset_sigma", self.tester_offset_sigma, 0.0, True))
        n_ref = self.n_reference_parts
        if isinstance(n_ref, bool) or not isinstance(n_ref, numbers.Integral):
            raise TypeError(f"n_reference_parts must be an int, got {n_ref!r}")
        if n_ref < 1:
            raise ValueError(f"n_reference_parts must be >= 1 - the offset correction needs a reference, got {n_ref}")
        object.__setattr__(self, "n_reference_parts", int(n_ref))
        if self.noise_tail_df is not None:
            df = _check_finite("noise_tail_df", self.noise_tail_df)
            if df <= 2:
                raise ValueError(f"noise_tail_df must be > 2 so the noise has a finite variance, got {df}")
            object.__setattr__(self, "noise_tail_df", df)

    def _key(self):
        return (tuple(self.noise_frac.items()), tuple(self.resolution.items()),
                tuple(self.tester_offset_sigma.items()), self.n_reference_parts, self.noise_tail_df)

    def __eq__(self, other):
        return isinstance(other, MeasurementParams) and self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __reduce__(self):
        # MappingProxyType can't be pickled; rebuild through __init__ (re-validated, re-frozen) instead, so
        # params and the families holding them can cross process boundaries (a parallel harness) and deepcopy.
        return (type(self), (dict(self.noise_frac), dict(self.resolution), dict(self.tester_offset_sigma),
                                    self.n_reference_parts, self.noise_tail_df))


def _unit_noise(rng: np.random.Generator, size, df: float | None) -> np.ndarray:
    if df is None:
        return rng.standard_normal(size)
    return rng.standard_t(df, size) * math.sqrt((df - 2.0) / df)


def _step_decimals(step: float) -> int:
    # Decimal places of the step as written (0.01 -> 2, 0.003 -> 3, 1e-06 -> 6, 0.5 -> 1, 1000.0 -> 0).
    return max(0, -Decimal(repr(step)).normalize().as_tuple().exponent)


def _quantize(value: float, step: float, name: str) -> float:
    n = value / step
    if not math.isfinite(n):
        raise ValueError(f"resolution[{name}]={step} is too fine to quantize a reading of {value}")
    q = max(1, round(n)) * step
    # Rounded again to the step's own decimal places, so the reported float is the clean grid value at any
    # magnitude (123456789 * 0.01 -> 1234567.89, not 1234567.8900000001).
    return float(round(q, _step_decimals(step)))


def _validate_trajectories(trajectories) -> tuple[float, ...]:
    """measure_lot also accepts hand-built trajectories (tests, the harness); generate_lot_trajectories
    always produces valid ones. Anything malformed is rejected rather than silently truncated or dropped."""
    if not isinstance(trajectories, LotTrajectories):
        raise TypeError(f"trajectories must be a LotTrajectories, got {type(trajectories).__name__}")
    hours = _validate_checkpoints(trajectories.checkpoint_hours)
    if not isinstance(trajectories.parts, (list, tuple)):  # a one-shot iterable would be consumed silently
        raise TypeError(f"trajectories.parts must be a list or tuple, got {type(trajectories.parts).__name__}")
    seen = set()
    for part in trajectories.parts:
        if not isinstance(part, PartTrajectory):
            raise TypeError(f"trajectories.parts entries must be PartTrajectory, got {type(part).__name__}")
        cid = part.component_id
        if not isinstance(cid, str) or not cid.strip():
            raise TypeError(f"component_id must be a non-empty str, got {cid!r}")
        if cid in seen:  # values are keyed by component_id - a duplicate would silently drop a part
            raise ValueError(f"duplicate component_id {cid!r}")
        seen.add(cid)
        if not isinstance(part.values, Mapping) or set(part.values) != set(PARAMETERS):
            raise ValueError(f"part {cid!r} values must cover exactly {sorted(PARAMETERS)}")
        for name, series in part.values.items():
            if not isinstance(series, (list, tuple)) or len(series) != len(hours):
                raise ValueError(
                    f"part {cid!r} {name} series must have one value per checkpoint ({len(hours)})"
                )
            for v in series:
                if _check_finite(f"{cid} {name} value", v) <= 0:
                    raise ValueError(f"part {cid!r} {name} true value must be > 0, got {v}")
    return hours


def _require_finite(what: str, value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(
            f"{what} is not finite ({value}) - the measurement params are outside a physically meaningful range"
        )
    return value


def measure_lot(trajectories: LotTrajectories, seed: int, params: MeasurementParams | None = None) -> MeasuredLot:
    params = MeasurementParams() if params is None else params
    hours = _validate_trajectories(trajectories)  # normalized float tuple, never the raw caller input
    if isinstance(seed, bool) or not isinstance(seed, numbers.Integral):
        raise TypeError(f"seed must be an int, got {type(seed).__name__}")
    if seed < 0:
        raise ValueError(f"seed must be >= 0, got {seed}")
    if not isinstance(params, MeasurementParams):
        raise TypeError(f"params must be a MeasurementParams, got {type(params).__name__}")
    seed = int(seed)
    names = tuple(PARAMETERS)
    n_ckpt = len(hours)
    df = params.noise_tail_df

    lot_rng = np.random.default_rng(np.random.SeedSequence(entropy=seed, spawn_key=(_MEASUREMENT_LOT_STREAM,)))
    # Reference parts' true values: drawn from each parameter's population of lot centers, so they sit at
    # a realistic level for that parameter; fixed across checkpoints (they are not in the chamber).
    reference_values = {
        name: tuple(float(v) for v in lot_rng.lognormal(PARAMETERS[name].lot_center_mu,
                                                        PARAMETERS[name].lot_center_sigma,
                                                        params.n_reference_parts))
        for name in names
    }
    tester_offset, offset_estimate = [], []
    for _ in range(n_ckpt):
        offset = {
            name: _require_finite(f"tester offset for {name}",
                                  float(lot_rng.normal(0.0, 1.0)) * params.tester_offset_sigma[name])
            for name in names
        }
        estimate = {}
        for name in names:
            refs = np.asarray(reference_values[name])
            z = _unit_noise(lot_rng, len(refs), df)
            # Overflow is detected explicitly below and raised as one clean ValueError, not a numpy warning.
            with np.errstate(over="ignore", invalid="ignore"):
                raw_refs = refs * (1.0 + params.noise_frac[name] * z) + offset[name]
                estimate[name] = _require_finite(f"tester offset estimate for {name}",
                                                 float(np.mean(raw_refs - refs)))
        tester_offset.append(offset)
        offset_estimate.append(estimate)

    values = {}
    for index, part in enumerate(trajectories.parts):
        rng = np.random.default_rng(
            np.random.SeedSequence(entropy=seed, spawn_key=(_MEASUREMENT_PART_STREAM, index))
        )
        series = {name: [] for name in names}
        for k in range(n_ckpt):
            z = _unit_noise(rng, len(names), df)
            for j, name in enumerate(names):
                true = part.values[name][k]
                raw = true * (1.0 + params.noise_frac[name] * float(z[j])) + tester_offset[k][name]
                corrected = _require_finite(f"{part.component_id} {name} reading", raw - offset_estimate[k][name])
                step = params.resolution[name]
                # A finite but enormous offset/noise term can still swamp the true value: 12 + 1e308 - 1e308
                # is 0 or garbage, not 12. Refuse when float rounding on the raw value exceeds half a step.
                if abs(raw) * _PRECISION_GUARD > step / 2:
                    raise ValueError(
                        f"{part.component_id} {name}: raw reading {raw} can't be resolved at resolution {step} "
                        "within finite float precision - offset/noise params are outside a physically meaningful range"
                    )
                series[name].append(_quantize(corrected, step, name))
        values[part.component_id] = {name: tuple(s) for name, s in series.items()}

    return MeasuredLot(
        checkpoint_hours=hours,
        values=values,
        truth=MeasurementTruth(
            reference_values=reference_values,
            tester_offset=tuple(tester_offset),
            offset_estimate=tuple(offset_estimate),
        ),
    )
