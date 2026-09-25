"""Per-parameter distributional grounding for baseline sampling (E1 steps 1-2).

context.md 3.3: healthy-part baseline distribution is lognormal, nested lot -> die;
real Iddq measurements vary several-fold lot-to-lot even among good parts (patent
example: 5-35 uA range). The exact mu/sigma pairs below are the generator's own
calibrated defaults chosen to reproduce that cited magnitude and spread - a disclosed
design choice (context.md Part 8), not a measured value.

Iddq and leakage are related-but-distinct subthreshold-leakage mechanisms (context.md
1.3, 3.3) so they get independent lognormal parameters rather than sharing one. Delay
is a physically separate mechanism (NBTI-driven Vt shift) with its own scale (ns, not uA).
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


PARAMETERS: dict[str, ParameterSpec] = {
    "iddq": ParameterSpec(
        name="iddq", unit="uA",
        lot_center_mu=2.48,  # exp(2.48) ~= 12 uA
        lot_center_sigma=0.5,  # ~90% of lot centers fall in ~5-30 uA, matching the cited patent range
        die_sigma_base=0.15,
        die_sigma_jitter=0.2,
    ),
    "leakage": ParameterSpec(
        name="leakage", unit="nA",
        lot_center_mu=1.61,  # exp(1.61) ~= 5 nA
        lot_center_sigma=0.5,
        die_sigma_base=0.15,
        die_sigma_jitter=0.2,
    ),
    "prop_delay": ParameterSpec(
        name="prop_delay", unit="ns",
        lot_center_mu=1.61,  # exp(1.61) ~= 5 ns
        lot_center_sigma=0.3,  # timing is a tighter-controlled process parameter than leakage
        die_sigma_base=0.08,
        die_sigma_jitter=0.15,
    ),
}
