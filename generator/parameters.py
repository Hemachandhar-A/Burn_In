"""Per-parameter distributional grounding for baseline sampling (E1 steps 1-2).

context.md 3.3: healthy-part baseline distribution is lognormal, nested lot -> die;
real Iddq measurements vary several-fold lot-to-lot even among good parts (patent
example: 5-35 uA range). The exact mu/sigma pairs below are the generator's own
calibrated defaults chosen to reproduce that cited magnitude and spread - a disclosed
design choice (context.md Part 8), not a measured value.

Iddq and leakage are related-but-distinct subthreshold-leakage mechanisms (context.md
1.3, 3.3) so they get independent lognormal parameters rather than sharing one. Delay
is a physically separate mechanism (NBTI-driven Vt shift) with its own scale (ns, not uA).

The drift/defect magnitudes (E1 steps 4-5) are likewise the generator's own disclosed defaults,
not measured values: healthy parts drift a few to ~10 percent of baseline over 168h, and a
typical defect roughly doubles Iddq by 168h - enough to be separable from healthy drift, which is
the point of the problem statement's worked example (lot median 10 uA, suspect part at 45 uA).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    unit: str
    lot_center_mu: float  # log-space mean of the lot-level center distribution
    lot_center_sigma: float  # log-space sigma - controls lot-to-lot spread of the center itself
    die_sigma_base: float  # typical log-space die-to-die spread within a lot
    die_sigma_jitter: float  # log-space sigma of the lot-to-lot variation in that spread (E1 step 1:
    # both center AND spread are sampled per lot, not just the center)
    healthy_drift_frac_median: float  # E1 step 4: median healthy drift at 168h, as a fraction of baseline
    healthy_drift_frac_sigma: float  # log-space sigma of that fraction across parts
    defect_scale: float  # E1 step 5: defect-term magnitude at 168h, as a fraction of baseline, at severity 1


PARAMETERS: dict[str, ParameterSpec] = {
    "iddq": ParameterSpec(
        name="iddq", unit="uA",
        lot_center_mu=2.48,  # exp(2.48) ~= 12 uA
        lot_center_sigma=0.5,  # ~90% of lot centers fall in ~5-30 uA, matching the cited patent range
        die_sigma_base=0.15,
        die_sigma_jitter=0.2,
        healthy_drift_frac_median=0.08,
        healthy_drift_frac_sigma=0.4,
        defect_scale=1.0,  # Iddq carries the defect current directly (context.md 3.3) - the most sensitive
    ),
    "leakage": ParameterSpec(
        name="leakage", unit="nA",
        lot_center_mu=1.61,  # exp(1.61) ~= 5 nA
        lot_center_sigma=0.5,
        die_sigma_base=0.15,
        die_sigma_jitter=0.2,
        healthy_drift_frac_median=0.08,
        healthy_drift_frac_sigma=0.4,
        defect_scale=0.8,  # related-but-distinct leakage path: responds to the same defect, a bit less strongly
    ),
    "prop_delay": ParameterSpec(
        name="prop_delay", unit="ns",
        lot_center_mu=1.61,  # exp(1.61) ~= 5 ns
        lot_center_sigma=0.3,  # timing is a tighter-controlled process parameter than leakage
        die_sigma_base=0.08,
        die_sigma_jitter=0.15,
        healthy_drift_frac_median=0.03,  # a few-percent NBTI delay shift over a full campaign
        healthy_drift_frac_sigma=0.4,
        defect_scale=0.3,  # timing moves proportionally far less than leakage currents do
    ),
}
