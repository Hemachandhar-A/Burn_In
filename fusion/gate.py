from typing import Literal
from contracts import ModuleAResult, ModuleBResult
from fusion.settings import MODULE_B_ROLES


def module_b_tier(module_b: ModuleBResult | None, role: str = "current") -> Literal["PASS", "REVIEW", "REJECT"]:
    """Module B's tier under `role` (docs/MODULE_B_ROLE_EXPERIMENT.md). "current" is the behaviour of an in-progress lot
    (and of a finished lot up to demo-v2): REJECT when the forecast exceeds the safety slope, else PASS. A forecast that is
    unavailable (exceeds_safety_slope None) is PASS in every role."""
    if role not in MODULE_B_ROLES:
        raise ValueError(f"unknown Module B role {role!r}; expected one of {MODULE_B_ROLES}")
    if module_b is None or role in ("advisory", "off"):
        return "PASS"
    if role == "tiered":
        if module_b.lower_bound_exceeds_safety_slope:
            return "REJECT"
        return "REVIEW" if module_b.exceeds_safety_slope else "PASS"
    return "REJECT" if module_b.exceeds_safety_slope else "PASS"


def compute_part_verdict(
    module_a: ModuleAResult | None,
    module_b: ModuleBResult | None,
    *,
    b_role: str = "current",
) -> tuple[Literal["PASS", "WATCH", "REJECT"], str | None, Literal["PASS", "REVIEW", "REJECT"]]:
    """
    Apply the two-tier verdict table (E12 step 1) and the explainability gate (E12 step 2).
    Returns (fused_verdict, final_cap_reason, capped_a_tier).

    `b_role` is how Module B counts: "current" (the default, and always what the pipeline passes for an in-progress lot) or,
    for a COMPLETE lot only, the configured `MODULE_B_FINISHED_LOT_ROLE` (fusion/settings.py).
    """
    b_tier = module_b_tier(module_b, b_role)  # validates the role

    if module_a is not None:
        a_tier = module_a.severity_tier
        cap_reason = module_a.severity_cap_reason
        
        # 2. Explainability gate on REJECT (E12 step 2)
        if a_tier == "REJECT" and not module_a.explainable_corroboration:
            a_tier = "REVIEW"
            cap_reason = "explainability_gate"
    else:
        a_tier = "PASS"
        cap_reason = None

    # E12 step 1: Fusion table
    if a_tier == "REJECT" or b_tier == "REJECT":
        verdict = "REJECT"
    elif a_tier == "REVIEW" and b_tier == "REVIEW":
        verdict = "REJECT"
    elif a_tier == "REVIEW" or b_tier == "REVIEW":
        verdict = "WATCH"
    else:
        verdict = "PASS"
        
    return verdict, cap_reason, a_tier
