"""E1 step 9: five named, structurally distinct generator configurations for held-out validation
(context.md 3.4 (2), 7.12) - so the harness evaluates on held-out *families*, not just held-out seeds of
the configuration the models were tuned on.

Each non-baseline family changes one named structural assumption of the baseline:
    wider_drift_exponent      healthy power-law n drawn from a wider range (drift *shape* in time changes;
                              the 168h drift magnitude is still set by healthy_drift_frac, so it is not
                              just a bigger-drift family)
    higher_defect_prevalence  defect prevalence above the baseline's 1-8% prior
    different_noise_regime    heavier-tailed (Student-t) and larger noise, coarser quantization, larger
                              tester offsets, fewer reference parts to correct them with
    altered_correlation       inverts the baseline's correlation assumption (E1 step 6): healthy die-to-die
                              variation shares a factor across parameters, defect severity barely does

Every family value here is a disclosed stress-test choice, not a measured value (context.md Part 8): the
point is to be structurally different from the baseline, not to claim a second "true" configuration.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from contracts import ScreeningConfig
from generator.measurement import MeasurementParams
from generator.trajectories import TrajectoryParams


@dataclass(frozen=True)
class GeneratorFamily:
    name: str
    description: str
    config: ScreeningConfig
    trajectory_params: TrajectoryParams
    measurement_params: MeasurementParams
    die_correlation: float = 0.0  # shared die-to-die factor across parameters (generate_lot_baselines)


_BASE_MEASUREMENT = MeasurementParams()

FAMILIES: Mapping[str, GeneratorFamily] = MappingProxyType({
    "baseline": GeneratorFamily(
        name="baseline",
        description="The locked defaults: every value from ScreeningConfig and the generator's disclosed defaults.",
        config=ScreeningConfig(),
        trajectory_params=TrajectoryParams(),
        measurement_params=_BASE_MEASUREMENT,
    ),
    "wider_drift_exponent": GeneratorFamily(
        name="wider_drift_exponent",
        description="Healthy drift exponent n drawn from [0.08, 0.50] instead of [0.15, 0.30]: flatter and "
                    "steeper drift curves than the cited NBTI cluster, same 168h drift magnitude.",
        config=ScreeningConfig(power_law_exponent_range=(0.08, 0.50)),
        trajectory_params=TrajectoryParams(),
        measurement_params=_BASE_MEASUREMENT,
    ),
    "higher_defect_prevalence": GeneratorFamily(
        name="higher_defect_prevalence",
        description="Defect prevalence 8-20% per lot, above the baseline's 1-8% prior - a lot-level "
                    "contamination regime where the lot median itself starts to be pulled by defects.",
        config=ScreeningConfig(defect_prevalence_range=(0.08, 0.20)),
        trajectory_params=TrajectoryParams(),
        measurement_params=_BASE_MEASUREMENT,
    ),
    "different_noise_regime": GeneratorFamily(
        name="different_noise_regime",
        description="Heavier-tailed Student-t (df=4) noise at 3x the proportional sigma, 10x coarser "
                    "quantization, 3x larger tester offsets corrected with only 2 reference parts.",
        config=ScreeningConfig(),
        trajectory_params=TrajectoryParams(),
        measurement_params=MeasurementParams(
            noise_frac={name: 3 * v for name, v in _BASE_MEASUREMENT.noise_frac.items()},
            resolution={name: 10 * v for name, v in _BASE_MEASUREMENT.resolution.items()},
            tester_offset_sigma={name: 3 * v for name, v in _BASE_MEASUREMENT.tester_offset_sigma.items()},
            n_reference_parts=2,
            noise_tail_df=4.0,
        ),
    ),
    "altered_correlation": GeneratorFamily(
        name="altered_correlation",
        description="Healthy die-to-die variation shares a factor across parameters (correlation 0.6) while "
                    "defect severity is nearly independent across parameters (0.1) - the reverse of the baseline.",
        config=ScreeningConfig(),
        trajectory_params=TrajectoryParams(severity_correlation=0.1),
        measurement_params=_BASE_MEASUREMENT,
        die_correlation=0.6,
    ),
})
HELD_OUT_FAMILY_NAMES: tuple[str, ...] = tuple(FAMILIES)


def get_family(name: str) -> GeneratorFamily:
    if not isinstance(name, str):
        raise TypeError(f"family name must be a str, got {type(name).__name__}")
    if name not in FAMILIES:
        raise ValueError(f"unknown generator family {name!r}; expected one of {list(FAMILIES)}")
    return FAMILIES[name]
