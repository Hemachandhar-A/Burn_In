"""Internal generator data structures.

Deliberately separate from contracts.py's Reading/LotDataset: `is_defective` is ground
truth that must never leak into the production-facing schema (E1's "What it is";
7.3 checklist). Trajectory generation (P1.2) will consume these baselines to produce
real Reading objects, at which point is_defective moves to a hidden sidecar file.
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
    defect_prevalence: float  # this lot's randomized prevalence, drawn from config.defect_prevalence_range
    parts: list[PartBaseline]
