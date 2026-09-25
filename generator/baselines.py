"""E1 steps 1-3: lot/die baseline sampling and defect status assignment.

Sampling order is fixed (lot centers for every parameter, then defect prevalence, then
each part's defect status and per-parameter baseline) so that a fixed seed reproduces
an identical LotBaseline every time (AGENTS.md rule 9, 7.3's determinism check).
"""
import numbers

import numpy as np

from contracts import ScreeningConfig
from generator.parameters import PARAMETERS
from generator.schema import LotBaseline, PartBaseline


def _validate_inputs(lot_id: str, part_number: str, n_parts: int, seed: int, config: ScreeningConfig) -> None:
    if not isinstance(lot_id, str):
        raise TypeError(f"lot_id must be a str, got {type(lot_id).__name__}")
    if not lot_id.strip():
        raise ValueError(f"lot_id must be a non-empty string, got {lot_id!r}")
    if not isinstance(part_number, str):
        raise TypeError(f"part_number must be a str, got {type(part_number).__name__}")
    if not part_number.strip():
        raise ValueError(f"part_number must be a non-empty string, got {part_number!r}")
    # numbers.Integral (not `int`) so numpy integer scalars (e.g. np.int64) are accepted -
    # a plausible caller shape if n_parts/seed are derived from an array's .size - while
    # bool is excluded explicitly since it's a subtype of int in Python but not a valid count/seed.
    if isinstance(n_parts, bool) or not isinstance(n_parts, numbers.Integral):
        raise TypeError(f"n_parts must be an int, got {type(n_parts).__name__}")
    if n_parts < 1:
        raise ValueError(f"n_parts must be >= 1, got {n_parts}")
    if isinstance(seed, bool) or not isinstance(seed, numbers.Integral):
        raise TypeError(f"seed must be an int, got {type(seed).__name__}")
    if seed < 0:
        raise ValueError(f"seed must be >= 0, got {seed}")
    if not isinstance(config, ScreeningConfig):
        raise TypeError(f"config must be a ScreeningConfig, got {type(config).__name__}")

    prevalence_lo, prevalence_hi = config.defect_prevalence_range
    if not (0.0 <= prevalence_lo <= prevalence_hi <= 1.0):
        raise ValueError(
            "config.defect_prevalence_range must satisfy 0.0 <= lo <= hi <= 1.0, "
            f"got ({prevalence_lo}, {prevalence_hi})"
        )


def generate_lot_baselines(
    lot_id: str,
    part_number: str,
    n_parts: int,
    seed: int,
    config: ScreeningConfig | None = None,
) -> LotBaseline:
    # `is None`, not `or`: a falsy wrong-type config ({}, 0, "") must reach validation and fail,
    # never be silently replaced by the defaults.
    config = ScreeningConfig() if config is None else config
    _validate_inputs(lot_id, part_number, n_parts, seed, config)
    n_parts = int(n_parts)  # normalize numpy integer scalars to plain int for downstream use
    seed = int(seed)
    rng = np.random.default_rng(seed)

    lot_center = {
        name: float(rng.lognormal(mean=spec.lot_center_mu, sigma=spec.lot_center_sigma))
        for name, spec in PARAMETERS.items()
    }
    # E1 step 1: spread is sampled per lot too, not just the center - a jittered multiplier
    # around each parameter's typical die-to-die sigma.
    lot_die_sigma = {
        name: float(spec.die_sigma_base * rng.lognormal(mean=0.0, sigma=spec.die_sigma_jitter))
        for name, spec in PARAMETERS.items()
    }

    prevalence_lo, prevalence_hi = config.defect_prevalence_range
    defect_prevalence = float(rng.uniform(prevalence_lo, prevalence_hi))
    defect_flags = rng.random(n_parts) < defect_prevalence

    parts = []
    for i in range(n_parts):
        baseline = {
            name: float(rng.lognormal(mean=np.log(lot_center[name]), sigma=lot_die_sigma[name]))
            for name in PARAMETERS
        }
        parts.append(
            PartBaseline(
                component_id=f"{lot_id}-{i:04d}",
                lot_id=lot_id,
                part_number=part_number,
                baseline=baseline,
                is_defective=bool(defect_flags[i]),
            )
        )

    return LotBaseline(
        lot_id=lot_id,
        part_number=part_number,
        lot_center=lot_center,
        lot_die_sigma=lot_die_sigma,
        defect_prevalence=defect_prevalence,
        parts=parts,
    )
