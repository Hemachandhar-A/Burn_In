"""Block 3B Part 3: E4 steps 5-10's QA-facing text and notes - pure functions over values every
one of Module A/B, fusion's gate, and storage's stored diff already computed (AGENTS.md rule 1:
nothing here re-derives a detector's own math). Deterministic, fixed inputs, no randomness (rule 9).

`ZScoreRow`/`ShapExplanation` (explain/models.py) and `ModuleBResult`/`RiskAssessment` (contracts.py)
are read, never recomputed. `ZScoreRow` carries no physical unit (contracts.FeatureFrame has none
either - a disclosed simplification, not a guess at one), so the sentence's "median = X, value = Y"
clause is unitless by construction.
"""
from collections import Counter

from contracts import ModuleAResult, ModuleBResult, RiskAssessment
from explain.models import ShapExplanation, ZScoreRow
from module_b.model import FEATURE_NAMES

# E4 step 5's "Primary driver: ..." clause names a module_b.model.FEATURE_NAMES entry (SHAP's own
# feature-engineering name, e.g. "delta_96h") - QA-facing text humanizes it instead, per feature.
# Every name in FEATURE_NAMES is mapped; an unrecognized name (should not occur, but never a KeyError)
# falls back to the raw name rather than hiding it.
_FEATURE_NAME_LABELS: dict[str, str] = {
    "delta_24h": "0h-to-24h change",
    "delta_96h": "0h-to-96h change",
    "offset_0h": "0h value vs. lot median",
    "offset_24h": "24h value vs. lot median",
    "lot_drift_24h": "lot median's 0h-to-24h change",
    "elapsed_24h": "elapsed hours to the 24h reading",
    "elapsed_96h": "elapsed hours to the 96h reading",
    "value_0h": "0h baseline value",
}
assert set(_FEATURE_NAME_LABELS) == set(FEATURE_NAMES), (
    "_FEATURE_NAME_LABELS must have one entry per module_b.model.FEATURE_NAMES"
)


def _humanize_feature(feature: str) -> str:
    return _FEATURE_NAME_LABELS.get(feature, feature)

# E4 step 6's confidence qualifier needs a numeric threshold for its second, independent signal
# (context.md 4.3/7.6's physics-vs-model disagreement gap) that no source document states - a
# disclosed judgment call (AGENTS.md rule 12), named here rather than left as a hidden magic number.
# The physics baseline is treated as "agreeing" with the model when it falls within this multiple of
# the calibrated interval's own half-width; 1.0 means "within the model's own stated uncertainty".
_PHYSICS_DISAGREEMENT_HALF_WIDTH_MULTIPLIER: float = 1.0

_HIGH_CONFIDENCE = "high confidence"
_BORDERLINE_INTERVAL = "forecast borderline: the prediction interval spans the safety slope - recommend retest"
_BORDERLINE_PHYSICS = "forecast borderline: the physics baseline disagrees with the forecast - recommend retest"


def explanation_sentence(
    component_id: str,
    *,
    zscore_row: ZScoreRow | None = None,
    module_b: ModuleBResult | None = None,
    shap: ShapExplanation | None = None,
    module_a: ModuleAResult | None = None,
    module_a_checkpoint: str = "24h",
) -> str:
    """E4 step 5's sentence template. The z-score clause appears only when Module A ran for this
    part (`module_a` given) or, for callers that predate that, `zscore_row` is given; the
    drift-forecast clause only when `module_b` is given, not unavailable, and carries a usable
    drift_rate/safety_slope pair - a module that did not compute something is never claimed to have.
    `shap`'s top contribution (already sorted by |shap_value| descending, explain/shap_b.py) names
    the primary driver, shown only alongside the drift clause.

    G5 Part C: when `module_a` is given, the clause quotes ModuleAResult.robust_z (Module A's own
    worst-checkpoint number) and direction, and names `module_a_checkpoint` - the checkpoint that
    number came from - never a different checkpoint's z. `zscore_row` then only supplies the
    optional "(median = X, value = Y)" detail, and must be the row for that same checkpoint (or
    None: FeatureFrame carries a lot median only for 0h/24h)."""
    clauses = [f"Part {component_id}:"]

    if module_a is not None:
        direction_word = "below" if module_a.direction == "below_median" else "above"
        clause = (
            f"{module_a.parameter} at {module_a_checkpoint} is {module_a.robust_z:.1f} robust-sigma "
            f"{direction_word} lot median"
        )
        if zscore_row is not None:
            clause += f" (median = {zscore_row.lot_median:g}, value = {zscore_row.value:g})"
        clauses.append(clause + ".")
    elif zscore_row is not None:
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
            clauses.append(f"Primary driver: {_humanize_feature(shap.contributions[0].feature)}.")

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

    if not interval_agrees:
        return _BORDERLINE_INTERVAL
    return _HIGH_CONFIDENCE if physics_agrees else _BORDERLINE_PHYSICS


def _missing_components_sentence(insufficient_data_components: list[str]) -> str | None:
    if not insufficient_data_components:
        return None
    n = len(insufficient_data_components)
    names = ", ".join(sorted(insufficient_data_components))
    noun = "component" if n == 1 else "components"
    verb_have = "has" if n == 1 else "have"
    verb_be = "was" if n == 1 else "were"
    return f"{n} {noun} {verb_have} insufficient data and {verb_be} not analysed: {names}."


def explanation_summary(
    assessments: list[RiskAssessment], insufficient_data_components: list[str]
) -> str:
    """E4 step 7's lot-level rollup, a template over `assessments`/`insufficient_data_components` -
    both already computed by fusion (Part 1a), nothing new derived here. "Flagged" matches the
    project's own vocabulary (AGENTS.md rule 10): verdict WATCH or REJECT, never PASS.

    "concentrated in X" is only used when X holds more than half of the flagged parts - otherwise
    the breakdown is spread across every worst_parameter that appears, ordered by count descending
    then parameter name ascending, for determinism (rule 9)."""
    total = len(assessments)
    if total == 0:
        base = "No parts analysed."
    else:
        flagged = [a for a in assessments if a.verdict != "PASS"]
        if not flagged:
            base = f"0 of {total} parts flagged."
        else:
            n_watch = sum(1 for a in flagged if a.verdict == "WATCH")
            counts = Counter(a.worst_parameter for a in flagged)
            top_count = max(counts.values())
            if top_count > len(flagged) / 2:
                top_parameter = min(p for p, c in counts.items() if c == top_count)
                base = f"{len(flagged)} of {total} parts flagged, concentrated in {top_parameter}"
            else:
                breakdown = ", ".join(
                    f"{p} ({c})" for p, c in sorted(counts.items(), key=lambda pc: (-pc[1], pc[0]))
                )
                base = f"{len(flagged)} of {total} parts flagged, spread across {breakdown}"
            if n_watch:
                base += f", {n_watch} crossing REVIEW only"
            base += "."

    missing = _missing_components_sentence(insufficient_data_components)
    return f"{base} {missing}" if missing else base


# The two, and only two, reasons fusion/gate.py's cap_reason can carry (E12 step 2, E2 step 6) -
# named here to match fusion/gate.py's and module_a/detect.py's own string values exactly.
_EXPLAINABILITY_GATE = "explainability_gate"
_DIRECTION_CAP = "below_median_direction_cap"


def severity_cap_note(cap_reason: str | None, final_verdict: str) -> str | None:
    """E4 step 8, generalized over both capping reasons (never a single wording for both).
    `cap_reason` is fusion.gate.compute_part_verdict's own second return value - read, not
    re-derived. None means no cap fired, so no note (a hidden cap protects the system's logic but
    not the reviewer's understanding of it - E12 step 2 - so this is set whenever a cap fired, not
    only when it changed the final verdict)."""
    if cap_reason is None:
        return None

    if cap_reason == _EXPLAINABILITY_GATE:
        note = (
            "Module A's REJECT-level severity was capped to REVIEW: it was driven solely by an "
            "unexplainable detector (Isolation Forest or ECOD) - a REJECT must be corroborated by "
            "an explainable detector (z-score or MCD)."
        )
        if final_verdict == "REJECT":
            note += " The final REJECT verdict relies on Module B's own signal, not Module A's."
        return note

    if cap_reason == _DIRECTION_CAP:
        return (
            "Module A's severity was capped to REVIEW: the deviation is below the lot median "
            "(direction-awareness cap) - a below-median value cannot reach REJECT-eligible on "
            "this basis alone."
        )

    raise ValueError(f"unrecognized severity_cap_reason {cap_reason!r}")


def unavailable_forecast_note(module_b: ModuleBResult | None) -> str | None:
    """E4 step 9: an explicit note in place of the trajectory chart when Module B declined to
    forecast (module_b/predictor.py's forecast_unavailable=True - a parameter outside the trained
    three, no calibrated model for it, or a non-finite required input). None when Module B did not
    run at all, or ran and produced a real forecast - never a note claiming unavailability that
    isn't true."""
    if module_b is None or not module_b.forecast_unavailable:
        return None
    if module_b.unavailable_reason:
        return f"Drift prediction unavailable - {module_b.unavailable_reason}."
    return (
        f"Drift prediction unavailable for {module_b.parameter}: outside Module B's trained "
        f"parameter set, no calibrated model, or an invalid required input."
    )


def staleness_note(
    disposition_analysis_run_id: str,
    latest_analysis_run_id: str,
    second_latest_analysis_run_id: str | None,
    diff_vs_prior: dict | None,
) -> str | None:
    """E4 step 10 / E11: named exactly what changed, sourced ONLY from the stored diff - never a
    bare flag, never an invented one (rule 7). `storage.repository.save_analysis_run` only ever
    computes `diff_vs_prior` against a `ProjectData` row's own immediate predecessor - there is no
    stored diff for a wider gap - so this returns None unless the disposition was signed against
    exactly the run immediately before the latest one (`second_latest_analysis_run_id`), in which
    case the latest row's own `diff_vs_prior` IS that exact pair's diff."""
    if disposition_analysis_run_id == latest_analysis_run_id:
        return None  # not stale - signed against the latest run
    if second_latest_analysis_run_id is None or second_latest_analysis_run_id != disposition_analysis_run_id:
        return None  # gap wider than one run: no single stored diff spans it (CONTRACT_CHANGES.md)
    if diff_vs_prior is None:
        return None

    parts = []
    for cid, modules in sorted((diff_vs_prior.get("newly_activated_modules") or {}).items()):
        parts.append(f"{cid}: {', '.join(sorted(modules))} activated")
    for cid, info in sorted((diff_vs_prior.get("resolved_forecasts") or {}).items()):
        parts.append(f"{cid}: forecast resolved (predicted {info.get('predicted')}, actual {info.get('actual')})")
    for cid, info in sorted((diff_vs_prior.get("verdict_changes") or {}).items()):
        parts.append(f"{cid}: verdict moved from {info.get('from')} to {info.get('to')}")

    if not parts:
        return "A newer analysis run exists since this disposition was signed off, with no tracked changes."
    return "A newer analysis run exists since this disposition was signed off: " + "; ".join(parts) + "."
