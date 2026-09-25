"""Internal generator data structures.

Deliberately separate from contracts.py's Reading/LotDataset: `is_defective` is ground
truth that must never leak into the production-facing schema (E1's "What it is";
7.3 checklist). Trajectories (P1.2) are noise-free internal objects; generator.lot turns them
into real Reading objects, and everything in this module travels only in the ground-truth sidecar.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PartBaseline:
    component_id: str
    lot_id: str
    part_number: str
    baseline: dict[str, float]  # per parameter name -> baseline value at t=0
    is_defective: bool  # ground truth - kept out of the production Reading/LotDataset schema


@dataclass(frozen=True)
class LotBaseline:
    lot_id: str
    part_number: str
    lot_center: dict[str, float]  # per-parameter sampled lot-level center
    lot_die_sigma: dict[str, float]  # per-parameter sampled lot-level die-to-die spread (log-space)
    defect_prevalence: float  # this lot's randomized prevalence, drawn from config.defect_prevalence_range
    parts: list[PartBaseline]


@dataclass(frozen=True)
class PartTrajectory:
    """Noise-free physical trajectory for one part (E1 steps 4-6), plus the hidden parameters
    that produced it. Everything below `values` is ground truth for the harness sidecar only."""

    component_id: str
    lot_id: str
    part_number: str
    baseline: dict[str, float]  # per parameter -> value at t=0
    values: dict[str, tuple[float, ...]]  # per parameter -> value at each of LotTrajectories.checkpoint_hours
    is_defective: bool
    drift_exponent: dict[str, float]  # healthy power-law n, per parameter
    drift_amplitude: dict[str, float]  # healthy power-law A, per parameter (value units / hour^n)
    junction_temp_c: float  # chamber temperature + this part's self-heating
    defect_type: str | None  # a DEFECT_ARCHETYPES key; None for healthy parts
    activation_energy_eV: float | None
    acceleration_factor: float | None  # Arrhenius factor at junction_temp_c vs the reference temperature
    defect_onset_hours: float | None
    defect_severity: dict[str, float] | None  # per parameter, correlated across parameters (E1 step 6)


@dataclass(frozen=True)
class LotTrajectories:
    lot_id: str
    part_number: str
    checkpoint_hours: tuple[float, ...]  # elapsed burn-in hours each value was evaluated at
    chamber_temp_c: float  # this lot's actual chamber temperature (nominal +/- tolerance)
    parts: tuple[PartTrajectory, ...]


@dataclass(frozen=True)
class MeasurementTruth:
    """Hidden tester-side ground truth for one lot (E1 step 7) - sidecar only. Per-checkpoint entries
    are aligned 1:1 with MeasuredLot.checkpoint_hours: each checkpoint is its own tester session."""

    reference_values: dict[str, tuple[float, ...]]  # per parameter -> known true value of each reference part
    tester_offset: tuple[dict[str, float], ...]  # actual additive offset per checkpoint, per parameter
    offset_estimate: tuple[dict[str, float], ...]  # offset inferred from the reference parts, then subtracted


@dataclass(frozen=True)
class MeasuredLot:
    checkpoint_hours: tuple[float, ...]
    values: dict[str, dict[str, tuple[float, ...]]]  # component_id -> parameter -> reading per checkpoint
    truth: MeasurementTruth
