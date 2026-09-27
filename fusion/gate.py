from typing import Literal
from contracts import ModuleAResult, ModuleBResult

def compute_part_verdict(
    module_a: ModuleAResult | None,
    module_b: ModuleBResult | None,
) -> tuple[Literal["PASS", "WATCH", "REJECT"], str | None, Literal["PASS", "REVIEW", "REJECT"]]:
    """
    Apply the two-tier verdict table (E12 step 1) and the explainability gate (E12 step 2).
    Returns (fused_verdict, final_cap_reason, capped_a_tier).
    """
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

    # Module B produces EARLY_REJECT (which we treat as REJECT) or PASS
    b_tier = "PASS"
    if module_b is not None:
        if module_b.exceeds_safety_slope:
            b_tier = "REJECT"
            
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
