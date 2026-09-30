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

# E4 step 6's confidence qualifier needs a numeric threshold for its second, independent signal
# (context.md 4.3/7.6's physics-vs-model disagreement gap) that no source document states - a
# disclosed judgment call (AGENTS.md rule 12), named here rather than left as a hidden magic number.
# The physics baseline is treated as "agreeing" with the model when it falls within this multiple of
# the calibrated interval's own half-width; 1.0 means "within the model's own stated uncertainty".
_PHYSICS_DISAGREEMENT_HALF_WIDTH_MULTIPLIER: float = 1.0

_HIGH_CONFIDENCE = "high confidence"
_BORDERLINE = "borderline - recommend retest"


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


def confidence_qualifier(module_b: ModuleBResult | None) -> str | None:
    """E4 step 6: two independent confidence signals, both already computed by module_b/ - never
    re-derived here (rule 1). None when Module B did not run or the forecast is unavailable (E4
    step 9's unavailable_forecast_note covers that case instead, never a fabricated qualifier).

    Signal 1 (CQR interval width vs. safety slope): whether the calibrated interval's lower bound
    reaches the same exceeds/does-not-exceed conclusion as the point estimate - disagreement means
    the interval is wide enough to flip the call.
    Signal 2 (context.md 4.3/7.6's physics-vs-model disagreement gap): whether the physics baseline
    falls within the model's own calibrated interval (scaled by the named multiplier above)."""
    if module_b is None or module_b.forecast_unavailable:
        return None
    if module_b.exceeds_safety_slope is None or module_b.lower_bound_exceeds_safety_slope is None:
        return None

    interval_agrees = module_b.exceeds_safety_slope == module_b.lower_bound_exceeds_safety_slope

    physics_agrees = True
    if (
        module_b.physics_disagreement_gap is not None
        and module_b.interval_lower is not None
        and module_b.interval_upper is not None
    ):
        half_width = abs(module_b.interval_upper - module_b.interval_lower) / 2.0
        physics_agrees = module_b.physics_disagreement_gap <= half_width * _PHYSICS_DISAGREEMENT_HALF_WIDTH_MULTIPLIER

    return _HIGH_CONFIDENCE if (interval_agrees and physics_agrees) else _BORDERLINE
