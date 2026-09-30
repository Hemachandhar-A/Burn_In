"""Block 3B Part 3: E4 steps 5-10's QA-facing text and notes - pure functions over values every
one of Module A/B, fusion's gate, and storage's stored diff already computed (AGENTS.md rule 1:
nothing here re-derives a detector's own math). Deterministic, fixed inputs, no randomness (rule 9).

`ZScoreRow`/`ShapExplanation` (explain/models.py) and `ModuleBResult`/`RiskAssessment` (contracts.py)
are read, never recomputed. `ZScoreRow` carries no physical unit (contracts.FeatureFrame has none
either - a disclosed simplification, not a guess at one), so the sentence's "median = X, value = Y"
clause is unitless by construction.
"""
from contracts import ModuleBResult
from explain.models import ShapExplanation, ZScoreRow


def explanation_sentence(
    component_id: str,
    *,
    zscore_row: ZScoreRow | None = None,
    module_b: ModuleBResult | None = None,
    shap: ShapExplanation | None = None,
) -> str:
    """E4 step 5's sentence template. The z-score clause appears only when `zscore_row` is given
    (Module A ran for this part); the drift-forecast clause only when `module_b` is given, not
    unavailable, and carries a usable drift_rate/safety_slope pair - a module that did not compute
    something is never claimed to have. `shap`'s top contribution (already sorted by |shap_value|
    descending, explain/shap_b.py) names the primary driver, shown only alongside the drift clause."""
    clauses = [f"Part {component_id}:"]

    if zscore_row is not None:
        direction_word = "above" if zscore_row.z >= 0 else "below"
        clauses.append(
            f"{zscore_row.parameter} at 24h is {abs(zscore_row.z):.1f} robust-sigma {direction_word} "
            f"lot median (median = {zscore_row.lot_median:g}, value = {zscore_row.value:g})."
        )

    has_drift = (
        module_b is not None
        and not module_b.forecast_unavailable
        and module_b.drift_rate is not None
        and module_b.safety_slope is not None
        and module_b.safety_slope != 0
    )
    if has_drift:
        pct = (module_b.drift_rate / module_b.safety_slope - 1.0) * 100.0
        verb = "exceeds" if pct >= 0 else "is under"
        clauses.append(f"Predicted 168h drift {verb} the calibrated safety slope by {abs(pct):.0f}%.")
        if shap is not None and shap.contributions:
            clauses.append(f"Primary driver: {shap.contributions[0].feature}.")

    return " ".join(clauses)
