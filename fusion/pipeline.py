import math

from contracts import (
    LotDataset, ScreeningConfig, AnalysisResults, RiskAssessment, LotDisposition, to_module_b_input,
    PartExplanation, ShapContributionRow, MCDContributionRow, EcodDimensionRow, ZScoreTableRow,
    FeatureFrame, TrajectoryPoint,
)
from features.compute import compute
from module_a.detect import detect as module_a_detect
from module_a.settings import module_a_scoring_config
from module_b.predictor import predict as module_b_predict, synthetic_models as module_b_synthetic_models, TRAINED_PARAMETERS
from fusion.gate import compute_part_verdict
from ingestion.quality import check_missing_checkpoints
from explain.cache import ExplainCache
from explain.zscore import build_zscore_table
from explain.mcd import explain_mcd
from explain.ecod import explain_ecod
from explain.shap_b import explain_module_b
from explain.text import (
    explanation_sentence, confidence_qualifier, explanation_summary as build_explanation_summary,
    severity_cap_note, unavailable_forecast_note,
)

def _build_trajectory(frame: FeatureFrame, unit: str | None = None) -> list[TrajectoryPoint]:
    """Block 4c Part 3b: one TrajectoryPoint per MEASURED checkpoint of `frame` (its own worst
    parameter's frame) - 0h/24h always attempted, 96h/168h only when the frame actually carries a
    value (value_168h is populated only on a COMPLETE lot). Skips an absent (None) or non-finite
    value rather than emitting one (rule 7 / the earlier SHAP null bug's own lesson: never let a NaN
    reach a stored/serialized field). lot_median is read from the frame's own lot_median_0h/24h
    fields when the checkpoint has one; FeatureFrame carries no lot_median_96h/168h field at all, so
    those points get lot_median=None rather than a computed guess."""
    candidates: list[tuple[int, float | None, float | None]] = [
        (0, frame.value_0h, frame.lot_median_0h),
        (24, frame.value_24h, frame.lot_median_24h),
        (96, frame.value_96h, None),
        (168, frame.value_168h, None),
    ]
    points = []
    for hour, value, median in candidates:
        if value is None or not math.isfinite(value):
            continue
        median_value = median if (median is not None and math.isfinite(median)) else None
        points.append(TrajectoryPoint(checkpoint_hour=hour, value=value, lot_median=median_value, unit=unit))
    return points


def run_full_pipeline(
    lot: LotDataset, config: ScreeningConfig, *, _explain_cache: bool = True,
) -> AnalysisResults:
    """`_explain_cache` (Block 4c Part 2, keyword-only, underscore-prefixed - not part of the public
    signature Part 5.7 froze): defaults to True, building a fresh ExplainCache() below and passing it
    to every per-part explain_mcd/explain_ecod/explain_module_b call so fit_mcd/fit_ecod/
    TreeExplainer construction are each done once per (lot, checkpoint)/(lot, parameter)/fitted-model
    instead of once per flagged part. False disables it (cache=None passed to every call instead,
    reproducing the exact pre-optimization behavior) - a test-only hook
    (tests/unit/fusion/test_explain_cache.py) proving the cached and uncached paths produce
    numerically identical part_explanations, not a knob any real caller should ever need."""
    is_complete = lot.status == "COMPLETE"
    is_forecast = not is_complete

    # Part 1a (Block 3B): single source of the INSUFFICIENT_DATA rule - computed here, not
    # reimplemented, so AnalysisResults.insufficient_data_components carries it on every path
    # (live GET /lots/{lot_id} and a stored reload alike), not just the ingestion upload response.
    quality_flags = check_missing_checkpoints(lot.readings)
    insufficient_data_components = sorted(
        {f.component_id for f in quality_flags if f.flag_type == "INSUFFICIENT_DATA"}
    )

    frames = compute(lot)
    # F24 Part 3: the canonical unit per parameter (readings are unit-normalised at ingestion, so one per parameter).
    unit_by_parameter: dict[str, str] = {}
    for reading in lot.readings:
        if reading.unit:
            unit_by_parameter.setdefault(reading.parameter, reading.unit)
    
    a_results = []
    if is_complete:
        # MODULE_A_SCORING (module_a/settings.py): None under the default "rank" mode, i.e. the unchanged call.
        a_results = module_a_detect(frames, scoring=module_a_scoring_config())
    
    # Severity for picking a part's worst frame and for ranking: s = -log10 p when absolute scoring supplies it
    # (no saturation or ties at large s), else combined_severity (the rank-mode percentile).
    def severity_key(r):
        return r.severity_log10p if r.severity_log10p is not None else r.combined_severity

    a_by_comp = {}
    for r in a_results:
        cid = r.component_id
        if cid not in a_by_comp or severity_key(r) > severity_key(a_by_comp[cid]):
            a_by_comp[cid] = r
    
    # module_b_predict is called
    b_inputs = [to_module_b_input(frame) for frame in frames]
    b_results = module_b_predict(b_inputs) if frames else []
    b_results = [r.model_copy(update={"unit": unit_by_parameter.get(r.parameter)}) for r in b_results]
    
    # rank components for Module A: by combined_severity descending, component_id ascending
    a_scores = [(-severity_key(r), r.component_id) for r in a_by_comp.values()]
    a_scores.sort()
    a_rank_map = {cid: float(rank) for rank, (_, cid) in enumerate(a_scores, start=1)}
    
    # rank components for Module B: by drift_rate / safety_slope, handling None
    # A component with no usable value ranks after every component that has one.
    # Group Module B results by component to find the max severity parameter per component.
    b_max_severity = {}
    b_worst_param = {}
    for r in b_results:
        cid = r.component_id
        if r.drift_rate is not None and r.safety_slope is not None and r.safety_slope > 0:
            severity = r.drift_rate / r.safety_slope
            if cid not in b_max_severity or severity > b_max_severity[cid]:
                b_max_severity[cid] = severity
                b_worst_param[cid] = r
                
    b_scores = []
    # Identify unique components from b_results
    b_cids = {r.component_id for r in b_results}
    for cid in b_cids:
        severity = b_max_severity.get(cid)
        if severity is not None:
            # -severity for descending, cid for ascending tie-break
            b_scores.append((-severity, cid))
        else:
            # Component has no usable value, sort it after usable ones
            b_scores.append((1e9, cid))
            
    b_scores.sort()
    b_rank_map = {cid: float(rank) for rank, (_, cid) in enumerate(b_scores, start=1)}
    
    # Update b_by_comp to match the worst parameter used for ranking
    b_by_comp = b_worst_param
    
    # Identify unique components
    component_ids = set()
    for frame in frames:
        component_ids.add(frame.component_id)

    # Part 3g (Block 3B): lookups keyed by (component_id, parameter) - a_by_comp/b_by_comp above are
    # each module's own per-component "worst" pick (by that module's own ranking), which may not be
    # the SAME parameter as the assessment's eventual worst_parameter. Explanations must describe
    # whatever worst_parameter actually is, using that exact parameter's own module result - never a
    # different parameter's numbers attributed to it.
    a_results_by_key = {(r.component_id, r.parameter): r for r in a_results}
    b_results_by_key = {(r.component_id, r.parameter): r for r in b_results}
    b_input_by_key = {(f.component_id, f.parameter): b_inputs[i] for i, f in enumerate(frames)}
    cap_reason_by_cid: dict[str, str | None] = {}

    assessments = []
    failures = 0
    lower_bound_failures = 0
    total_parts = len(component_ids)

    for cid in sorted(component_ids):
        # find the frame with the worst parameter?
        # we can just use the first frame's parameter if it's PASS, else worst parameter from module_a/b
        # Let's get all frames for this component
        comp_frames = [f for f in frames if f.component_id == cid]
        a_res = a_by_comp.get(cid)
        b_res = b_by_comp.get(cid)

        verdict, cap_reason, _ = compute_part_verdict(a_res, b_res)
        cap_reason_by_cid[cid] = cap_reason

        if verdict == "REJECT" or (b_res and b_res.exceeds_safety_slope):
            failures += 1
            
        if is_forecast:
            if b_res and b_res.lower_bound_exceeds_safety_slope is True:
                lower_bound_failures += 1
        else:
            if verdict == "REJECT":
                lower_bound_failures += 1
            
        worst_parameter = comp_frames[0].parameter
        if a_res and a_res.severity_tier != "PASS":
            worst_parameter = a_res.parameter
        elif b_res and b_res.exceeds_safety_slope:
            worst_parameter = b_res.parameter
            
        actual_168h = None
        if is_complete:
            # find actual 168h for worst_parameter
            for f in comp_frames:
                if f.parameter == worst_parameter:
                    actual_168h = f.value_168h
                    
        predicted_168h = b_res.predicted_168h if b_res else None
        
        assessment = RiskAssessment(
            component_id=cid,
            lot_id=lot.lot_id,
            verdict=verdict,
            # Rank 0.0 is the "not ranked" sentinel. It may only appear with module_a_ran or module_b_ran False.
            module_a_rank=a_rank_map.get(cid, 0.0),
            module_b_rank=b_rank_map.get(cid, 0.0),
            worst_parameter=worst_parameter,
            module_a_ran=is_complete,
            module_b_ran=True,
            predicted_168h=predicted_168h,
            actual_168h=actual_168h,
            explanation_sentence=None,
        )
        assessments.append(assessment)

    # Part 4 (Block 3B, CONTRACT_CHANGES.md 2026-09-30): GET /parts/{component_id} needs the full
    # ModuleAResult/ModuleBResult for every analysed component (not just non-PASS ones), stored
    # rather than re-run - one entry per component, for that component's own worst_parameter. Module
    # A is absent entirely on an in-progress lot (a_results_by_key is empty), a documented gap.
    module_a_results: dict[str, object] = {}
    module_b_results: dict[str, object] = {}
    for assessment in assessments:
        a_for_detail = a_results_by_key.get((assessment.component_id, assessment.worst_parameter))
        if a_for_detail is not None:
            module_a_results[assessment.component_id] = a_for_detail
        b_for_detail = b_results_by_key.get((assessment.component_id, assessment.worst_parameter))
        if b_for_detail is not None:
            module_b_results[assessment.component_id] = b_for_detail

    # Part 3g (Block 3B): E4's explanation mechanisms, one PartExplanation per non-PASS assessment.
    # PASS parts get no entry (not an empty one) - explain/text.py's functions all already return
    # None/[] for a module that did not compute something, so nothing here fabricates data.
    # Block 4c Part 2: a per-run explain_cache (never module-level state - fresh every call) so
    # fit_mcd/fit_ecod/TreeExplainer construction are each done once per (lot, checkpoint)/
    # (lot, parameter)/fitted-model and reused across every flagged part below, instead of refit once
    # per part (profiling: CONTRACT_CHANGES.md 2026-09-30 - this loop was ~92% of a warm upload's time).
    explain_cache = ExplainCache() if _explain_cache else None
    part_explanations: dict[str, PartExplanation] = {}
    for assessment in assessments:
        if assessment.verdict == "PASS":
            continue
        cid = assessment.component_id
        worst_parameter = assessment.worst_parameter
        comp_frames = [f for f in frames if f.component_id == cid]
        a_res_for_explain = a_results_by_key.get((cid, worst_parameter))
        b_res_for_explain = b_results_by_key.get((cid, worst_parameter))

        zscore_rows = []
        try:
            zscore_rows = build_zscore_table(comp_frames, "24h", unit_by_parameter).rows
        except ValueError:
            zscore_rows = []
        # The sentence's z-score clause only claims Module A's own worst-parameter result - never a
        # table lookup for a parameter Module A did not flag here. G5 Part C: it quotes
        # ModuleAResult.robust_z itself and the checkpoint that number came from - the same
        # max-|z| rule module_a/detect.py applies to frame.robust_z (Step 1) - not the 24h-only
        # zscore_table row, which can carry a different checkpoint's (smaller) z. The optional
        # "(median, value)" detail is only available for 0h/24h (FeatureFrame has no 96h/168h median).
        zscore_sentence_row = None
        sentence_checkpoint = "24h"
        if a_res_for_explain is not None:
            worst_frame = next((f for f in comp_frames if f.parameter == worst_parameter), None)
            if worst_frame is not None and worst_frame.robust_z:
                sentence_checkpoint = max(worst_frame.robust_z, key=lambda k: abs(worst_frame.robust_z[k]))
            if sentence_checkpoint in ("0h", "24h"):
                try:
                    checkpoint_rows = build_zscore_table(comp_frames, sentence_checkpoint, unit_by_parameter).rows
                except ValueError:
                    checkpoint_rows = []
                zscore_sentence_row = next((r for r in checkpoint_rows if r.parameter == worst_parameter), None)

        mcd_contributions = []
        try:
            mcd_contributions = explain_mcd(frames, "24h", cid, cache=explain_cache).contributions
        except ValueError:
            mcd_contributions = []

        ecod_dimensions = []
        try:
            ecod_dimensions = explain_ecod(frames, worst_parameter, cid, cache=explain_cache).contributions
        except ValueError:
            ecod_dimensions = []

        shap_exp = None
        if (
            worst_parameter in TRAINED_PARAMETERS
            and b_res_for_explain is not None
            and not b_res_for_explain.forecast_unavailable
        ):
            model = module_b_synthetic_models(lot.part_number).get((lot.part_number, worst_parameter))
            b_input = b_input_by_key.get((cid, worst_parameter))
            if model is not None and b_input is not None:
                try:
                    shap_exp = explain_module_b(b_input, model, cache=explain_cache)
                except KeyError:
                    shap_exp = None

        sentence = explanation_sentence(
            cid, zscore_row=zscore_sentence_row, module_b=b_res_for_explain, shap=shap_exp,
            module_a=a_res_for_explain, module_a_checkpoint=sentence_checkpoint,
        )

        worst_parameter_frame = next((f for f in comp_frames if f.parameter == worst_parameter), None)
        trajectory = (
            _build_trajectory(worst_parameter_frame, unit_by_parameter.get(worst_parameter))
            if worst_parameter_frame is not None else []
        )

        part_explanations[cid] = PartExplanation(
            shap_contributions=[
                ShapContributionRow(
                    feature=c.feature,
                    value=c.value if math.isfinite(c.value) else None,
                    shap_value=c.shap_value,
                )
                for c in (shap_exp.contributions if shap_exp else [])
            ],
            mcd_contributions=[
                MCDContributionRow(parameter=c.parameter, contribution=c.contribution)
                for c in mcd_contributions
            ],
            ecod_dimensions=[
                EcodDimensionRow(dimension=c.dimension, score=c.score) for c in ecod_dimensions
            ],
            zscore_table=[
                ZScoreTableRow(parameter=r.parameter, value=r.value, lot_median=r.lot_median, z=r.z, unit=r.unit)
                for r in zscore_rows
            ],
            explanation_sentence=sentence,
            confidence_qualifier=confidence_qualifier(b_res_for_explain),
            severity_cap_note=severity_cap_note(cap_reason_by_cid.get(cid), assessment.verdict),
            unavailable_forecast_note=unavailable_forecast_note(b_res_for_explain),
            trajectory=trajectory,
        )

    explanation_summary = build_explanation_summary(assessments, insufficient_data_components)

    pda_result = (failures / total_parts) if total_parts > 0 else 0.0
    pda_exceeded = pda_result >= config.pda_threshold
    
    lower_bound_pda = (lower_bound_failures / total_parts) if total_parts > 0 else 0.0
    lower_bound_pda_exceeded = lower_bound_pda >= config.pda_threshold
    
    if total_parts == 0:
        # D50: never reassure without data - a lot with nothing to assess is not "on track"/"accept"
        # by default. pda_result stays 0.0 (no failures counted, not "0% failure rate confirmed").
        lot_verdict = "LOT_AT_RISK" if is_forecast else "HOLD"
    elif is_forecast:
        if lower_bound_pda_exceeded:
            lot_verdict = "STOP_RUN_RECOMMENDED"
        elif failures > 0:
            lot_verdict = "LOT_AT_RISK"
        else:
            lot_verdict = "LOT_ON_TRACK"
    else:
        if pda_exceeded:
            lot_verdict = "REJECT"
        elif any(a.verdict == "WATCH" for a in assessments):
            lot_verdict = "HOLD"
        else:
            lot_verdict = "ACCEPT"
        # Part 1 ruling (Block 3B): a COMPLETE lot with >=1 analysed part but a non-empty
        # insufficient_data_components must never be ACCEPT - HOLD instead. Scoped to the ACCEPT
        # case only: REJECT/HOLD from the ordinary rules above are unaffected (D15 stays).
        if lot_verdict == "ACCEPT" and insufficient_data_components:
            lot_verdict = "HOLD"

    disposition = LotDisposition(
        lot_id=lot.lot_id,
        status=lot.status,
        pda_result=pda_result,
        verdict=lot_verdict,
        is_forecast=is_forecast
    )

    return AnalysisResults(
        assessments=assessments,
        disposition=disposition,
        insufficient_data_components=insufficient_data_components,
        part_explanations=part_explanations,
        explanation_summary=explanation_summary,
        module_a_results=module_a_results,
        module_b_results=module_b_results,
    )
