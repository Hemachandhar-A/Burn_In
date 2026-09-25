"""E1 steps 4-6: healthy power-law drift, Arrhenius-scaled defect trajectories, and the shared
defect-severity correlation factor.

Healthy parts (step 4, context.md 1.4 / 3.3 - NBTI power-law):
    value_p(t) = baseline_p + A_p * t**n_p
with n_p ~ U(config.power_law_exponent_range) and A_p set so the 168h drift is a lognormally
randomized fraction of baseline. n and A are drawn independently per parameter, so healthy
drift stays near-independent across parameters (step 6).

Defective parts (step 5) add a defect term on top of that same healthy drift:
    defect_p(t) = severity_p * defect_scale_p * baseline_p * g(AF * max(0, t - onset))
where g is the archetype's growth shape and AF is the Arrhenius acceleration factor of the part's
junction temperature relative to the nominal burn-in temperature, with Ea drawn per defect
instance from config.activation_energy_range_eV (context.md 3.3). AF scales the defect's
effective time: a defect with a larger Ea is more sensitive to the chamber running hot.

Step 6: severity_p shares one latent "defect severity" factor across the three parameters
(correlation TrajectoryParams.severity_correlation); healthy parts have no such shared factor.

Disclosed defaults, not measured values (context.md Part 8): the 125 C nominal burn-in temperature
(the common MIL-STD-883 TM1015 condition), the chamber tolerance, the self-heating range, the
severity distribution and correlation, and the archetype shapes/onset windows below.

Randomness is drawn from per-lot and per-part streams derived from `seed` via SeedSequence
spawn keys, and every part draws the same sequence whether or not it is defective - so the
output is deterministic (AGENTS.md rule 9) and a part's trajectory depends only on its own draws
and t, never on which later checkpoints were requested.
"""
import math
import numbers
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from contracts import ScreeningConfig
from generator.parameters import PARAMETERS
from generator.schema import LotBaseline, LotTrajectories, PartTrajectory

BOLTZMANN_EV_PER_K = 8.617333262e-5
KELVIN_OFFSET = 273.15
DEFAULT_CHECKPOINT_HOURS: tuple[float, ...] = (0.0, 24.0, 96.0, 168.0)
_REFERENCE_DURATION_HOURS = 168.0  # full campaign length that drift/defect magnitudes are expressed at

# SeedSequence spawn-key namespaces. Baselines use default_rng(seed) directly, so these are
# distinct streams from it and from each other.
_LOT_STREAM = 1
_PART_STREAM = 2


@dataclass(frozen=True)
class DefectArchetype:
    name: str
    onset_range_hours: tuple[float, float]  # (0, 0) = active from the start of burn-in
    shape: str  # "power": g = (t_eff/168)**m ; "saturating": g = 1 - exp(-t_eff/tau)
    shape_param_range: tuple[float, float]  # m for "power", tau (hours) for "saturating"


# All archetypes share one per-parameter fingerprint (defect_scale) and differ in timing/shape only -
# the "one generic defect severity mechanism" simplification disclosed in context.md 8.1.
DEFECT_ARCHETYPES: dict[str, DefectArchetype] = {
    # Steadily worsening defect, faster-than-healthy (super-linear) growth, visible by 24h.
    "progressive": DefectArchetype("progressive", (0.0, 0.0), "power", (1.0, 1.5)),
    # Infant-mortality-like: fast early rise that plateaus - strongest signal at 24h.
    "early_saturating": DefectArchetype("early_saturating", (0.0, 0.0), "saturating", (8.0, 48.0)),
    # Latent defect that activates only after the 24h checkpoint (E1 step 5) - invisible to a
    # 0h/24h-only view, onset before the 96h read so it is at least measurable later in the run.
    "latent_post_24h": DefectArchetype("latent_post_24h", (24.0, 96.0), "power", (1.0, 1.5)),
}
_ARCHETYPE_NAMES = tuple(DEFECT_ARCHETYPES)


def _check_finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


@dataclass(frozen=True)
class TrajectoryParams:
    """Generator-internal knobs for steps 4-6 not carried by ScreeningConfig. P1.3's held-out
    families (e.g. the altered-correlation family) vary these."""

    reference_temp_c: float = 125.0  # nominal burn-in temperature the defect rates are defined at
    lot_temp_tolerance_c: float = 3.0  # chamber temperature ~ U(ref - tol, ref + tol) per lot
    self_heating_range_c: tuple[float, float] = (0.0, 8.0)  # per-part junction rise above chamber
    severity_median: float = 1.0
    severity_log_sigma: float = 0.6
    severity_correlation: float = 0.8  # correlation of the log-severity across parameters, in [0, 1]

    def __post_init__(self) -> None:
        for name in ("reference_temp_c", "lot_temp_tolerance_c", "severity_median",
                     "severity_log_sigma", "severity_correlation"):
            _check_finite(name, getattr(self, name))
        lo, hi = self.self_heating_range_c
        _check_finite("self_heating_range_c[0]", lo)
        _check_finite("self_heating_range_c[1]", hi)
        if self.reference_temp_c - self.lot_temp_tolerance_c + KELVIN_OFFSET <= 0:
            raise ValueError("reference_temp_c - lot_temp_tolerance_c must be above absolute zero")
        if self.lot_temp_tolerance_c < 0:
            raise ValueError(f"lot_temp_tolerance_c must be >= 0, got {self.lot_temp_tolerance_c}")
        if not 0.0 <= lo <= hi:
            raise ValueError(f"self_heating_range_c must satisfy 0 <= lo <= hi, got ({lo}, {hi})")
        if self.severity_median <= 0:
            raise ValueError(f"severity_median must be > 0, got {self.severity_median}")
        if self.severity_log_sigma < 0:
            raise ValueError(f"severity_log_sigma must be >= 0, got {self.severity_log_sigma}")
        if not 0.0 <= self.severity_correlation <= 1.0:
            raise ValueError(f"severity_correlation must be in [0, 1], got {self.severity_correlation}")


def arrhenius_acceleration_factor(activation_energy_eV: float, junction_temp_c: float, reference_temp_c: float) -> float:
    """AF = exp(Ea/k * (1/T_ref - 1/T_j)) - JEDEC JEP122 Arrhenius acceleration (context.md 1.4)."""
    if not activation_energy_eV > 0:
        raise ValueError(f"activation_energy_eV must be > 0, got {activation_energy_eV}")
    t_j = junction_temp_c + KELVIN_OFFSET
    t_ref = reference_temp_c + KELVIN_OFFSET
    if not (t_j > 0 and t_ref > 0):
        raise ValueError("temperatures must be above absolute zero")
    return float(math.exp(activation_energy_eV / BOLTZMANN_EV_PER_K * (1.0 / t_ref - 1.0 / t_j)))


def _validate_range(name: str, rng: tuple[float, float], lo_bound: float, hi_bound: float | None) -> None:
    lo, hi = rng
    _check_finite(f"{name}[0]", lo)
    _check_finite(f"{name}[1]", hi)
    upper_ok = hi_bound is None or hi < hi_bound
    if not (lo_bound < lo <= hi and upper_ok):
        bound = f"< {hi_bound}" if hi_bound is not None else "finite"
        raise ValueError(f"{name} must satisfy {lo_bound} < lo <= hi ({bound}), got ({lo}, {hi})")


def _validate_checkpoints(checkpoint_hours) -> tuple[float, ...]:
    hours = tuple(checkpoint_hours)
    if not hours:
        raise ValueError("checkpoint_hours must be non-empty")
    for h in hours:
        if isinstance(h, bool) or not isinstance(h, numbers.Real):
            raise TypeError(f"checkpoint_hours entries must be numbers, got {h!r}")
        if not math.isfinite(h) or h < 0:
            raise ValueError(f"checkpoint_hours entries must be finite and >= 0, got {h!r}")
    hours = tuple(float(h) for h in hours)
    if any(b <= a for a, b in pairwise(hours)):
        raise ValueError(f"checkpoint_hours must be strictly increasing, got {hours}")
    return hours


def _validate_inputs(lot, seed, config, params) -> None:
    if not isinstance(lot, LotBaseline):
        raise TypeError(f"lot must be a LotBaseline, got {type(lot).__name__}")
    if isinstance(seed, bool) or not isinstance(seed, numbers.Integral):
        raise TypeError(f"seed must be an int, got {type(seed).__name__}")
    if seed < 0:
        raise ValueError(f"seed must be >= 0, got {seed}")
    if not isinstance(config, ScreeningConfig):
        raise TypeError(f"config must be a ScreeningConfig, got {type(config).__name__}")
    if not isinstance(params, TrajectoryParams):
        raise TypeError(f"params must be a TrajectoryParams, got {type(params).__name__}")
    # n in (0, 1): n <= 0 is no drift or decay, n >= 1 stops being sub-linear NBTI drift.
    _validate_range("config.power_law_exponent_range", config.power_law_exponent_range, 0.0, 1.0)
    _validate_range("config.activation_energy_range_eV", config.activation_energy_range_eV, 0.0, None)


def _growth(archetype: DefectArchetype, shape_param: float, t_eff: float) -> float:
    if archetype.shape == "power":
        return (t_eff / _REFERENCE_DURATION_HOURS) ** shape_param
    return 1.0 - math.exp(-t_eff / shape_param)


def _generate_part(part, index, seed, chamber_temp_c, hours, config, params) -> PartTrajectory:
    rng = np.random.default_rng(np.random.SeedSequence(entropy=seed, spawn_key=(_PART_STREAM, index)))
    n_lo, n_hi = config.power_law_exponent_range
    ea_lo, ea_hi = config.activation_energy_range_eV

    # Fixed draw order, identical for healthy and defective parts.
    drift_exponent, drift_amplitude = {}, {}
    for name, spec in PARAMETERS.items():
        n = float(rng.uniform(n_lo, n_hi))  # lo == hi returns lo exactly
        drift_frac = float(rng.lognormal(np.log(spec.healthy_drift_frac_median), spec.healthy_drift_frac_sigma))
        drift_exponent[name] = n
        drift_amplitude[name] = drift_frac * part.baseline[name] / _REFERENCE_DURATION_HOURS ** n
    heat_lo, heat_hi = params.self_heating_range_c
    junction_temp_c = chamber_temp_c + float(rng.uniform(heat_lo, heat_hi))

    archetype = DEFECT_ARCHETYPES[_ARCHETYPE_NAMES[int(rng.integers(len(_ARCHETYPE_NAMES)))]]
    ea = float(rng.uniform(ea_lo, ea_hi))
    onset_lo, onset_hi = archetype.onset_range_hours
    onset_u = float(rng.random())
    # Strictly after onset_lo when the window is non-degenerate (e.g. "only after the 24h checkpoint").
    onset = onset_lo if onset_hi == onset_lo else onset_hi - onset_u * (onset_hi - onset_lo)
    shape_lo, shape_hi = archetype.shape_param_range
    shape_param = float(rng.uniform(shape_lo, shape_hi))
    z_shared = float(rng.standard_normal())
    z_own = rng.standard_normal(len(PARAMETERS))

    rho = params.severity_correlation
    severity = {
        name: float(params.severity_median
                    * np.exp(params.severity_log_sigma * (math.sqrt(rho) * z_shared + math.sqrt(1 - rho) * z_own[k])))
        for k, name in enumerate(PARAMETERS)
    }
    af = arrhenius_acceleration_factor(ea, junction_temp_c, params.reference_temp_c)

    values = {}
    for name, spec in PARAMETERS.items():
        b = part.baseline[name]
        series = []
        for t in hours:
            v = b + drift_amplitude[name] * t ** drift_exponent[name]
            if part.is_defective:
                t_eff = af * max(0.0, t - onset)
                v += severity[name] * spec.defect_scale * b * _growth(archetype, shape_param, t_eff)
            series.append(float(v))
        values[name] = tuple(series)

    defective = part.is_defective
    return PartTrajectory(
        component_id=part.component_id,
        lot_id=part.lot_id,
        part_number=part.part_number,
        baseline=dict(part.baseline),
        values=values,
        is_defective=defective,
        drift_exponent=drift_exponent,
        drift_amplitude=drift_amplitude,
        junction_temp_c=junction_temp_c,
        defect_type=archetype.name if defective else None,
        activation_energy_eV=ea if defective else None,
        acceleration_factor=af if defective else None,
        defect_onset_hours=onset if defective else None,
        defect_severity=severity if defective else None,
    )


def generate_lot_trajectories(
    lot: LotBaseline,
    seed: int,
    config: ScreeningConfig | None = None,
    params: TrajectoryParams | None = None,
    checkpoint_hours=DEFAULT_CHECKPOINT_HOURS,
) -> LotTrajectories:
    config = config or ScreeningConfig()
    params = params or TrajectoryParams()
    _validate_inputs(lot, seed, config, params)
    hours = _validate_checkpoints(checkpoint_hours)
    seed = int(seed)

    lot_rng = np.random.default_rng(np.random.SeedSequence(entropy=seed, spawn_key=(_LOT_STREAM,)))
    tol = params.lot_temp_tolerance_c
    chamber_temp_c = params.reference_temp_c + float(lot_rng.uniform(-tol, tol))

    parts = tuple(
        _generate_part(part, i, seed, chamber_temp_c, hours, config, params) for i, part in enumerate(lot.parts)
    )
    return LotTrajectories(
        lot_id=lot.lot_id,
        part_number=lot.part_number,
        checkpoint_hours=hours,
        chamber_temp_c=chamber_temp_c,
        parts=parts,
    )
