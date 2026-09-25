"""THE GOLDEN TEST - IMPLEMENTATION_PLAN.md Part 7.2, essential-features.md E5 step 3, AGENTS.md rule 5.

    A lot with median leakage 10 uA and a part reading 45 uA, against a 50 uA datasheet limit,
    must be flagged.

The problem statement's own worked example. Every stage that touches module_a/ or fusion/ runs this before
every commit, and it must never regress once Module A is real (P3.3).

Status while stages are still stubs, by design:
    - a stage that does not exist on the branch yet     -> SKIPPED, with the reason (never a silent pass)
    - a stage that exists but is still a fixed-score stub -> expected to FAIL until it is real
      (module_a until P3.3, features until P2.4, fusion until P5.3)
    - an ImportError from inside an existing stage       -> FAILS; a broken module is never a skip

The fixture (harness/golden.py) is pinned by tests/unit/harness/test_golden.py, so a failure here is about
the pipeline, not about the lot. Part 7.4: this file is added, never edited by anyone else - add a new file.
"""
import pytest

from contracts import AnalysisResults, FeatureFrame, LotDataset, ScreeningConfig
from harness.golden import (
    GOLDEN_COMPONENT_ID,
    GOLDEN_DATASHEET_LIMIT_UA,
    GOLDEN_LOT_MEDIAN_UA,
    GOLDEN_PARAMETER,
    GOLDEN_PART_VALUE_UA,
    GoldenTestUnavailable,
    TEMP_detect_module_a,
    golden_feature_frames,
    golden_lot,
    golden_result,
    is_flagged,
    median_component_ids,
    resolve,
)

_EXAMPLE = (f"lot median {GOLDEN_LOT_MEDIAN_UA:g} uA, part {GOLDEN_COMPONENT_ID} at {GOLDEN_PART_VALUE_UA:g} uA, "
            f"datasheet limit {GOLDEN_DATASHEET_LIMIT_UA:g} uA")


def _module_a(frames: list[FeatureFrame]):
    try:
        return TEMP_detect_module_a(frames)
    except GoldenTestUnavailable as exc:
        pytest.skip(f"golden test not runnable yet: {exc} (P3.0 stub / P3.3 real)")


def _golden_failure(result) -> str:
    return (f"GOLDEN TEST FAILED - {_EXAMPLE} must be flagged, got severity_tier={result.severity_tier!r} "
            f"(robust_z={result.robust_z}, cap={result.severity_cap_reason!r}). If module_a is still the P3.0 "
            f"fixed-score stub this is expected until P3.3; otherwise it is a real regression (AGENTS.md rule 5).")


def test_golden_part_is_flagged_by_module_a():
    result = golden_result(_module_a(golden_feature_frames()))
    assert is_flagged(result), _golden_failure(result)
    # 45 uA against a 10 uA median is an above-median deviation: the direction cap (E2 step 6) never applies
    assert result.direction == "above_median"


def test_golden_lot_parts_on_the_median_pass():
    """The control: a Module A that flags everything would pass the test above. Parts sitting exactly on the
    lot median on every parameter at every checkpoint have nothing to flag."""
    results = _module_a(golden_feature_frames())
    on_median = set(median_component_ids())
    flagged = sorted({(r.component_id, r.parameter, r.severity_tier) for r in results
                      if r.component_id in on_median and is_flagged(r)})
    assert not flagged, f"parts exactly on the lot median were flagged: {flagged}"


def test_golden_part_is_flagged_through_features_compute():
    """Same example, but with P2's real feature stage producing Module A's input from the raw lot."""
    try:
        compute = resolve("features", "compute")
    except GoldenTestUnavailable as exc:
        pytest.skip(f"golden test (features path) not runnable yet: {exc} (P2.1 stub / P2.4 real)")
    lot = golden_lot()
    frames = compute(lot)
    result = golden_result(_module_a(frames))
    assert is_flagged(result), _golden_failure(result) + " [path: features.compute -> module_a.detect]"


def test_golden_part_is_flagged_by_the_full_pipeline():
    """End to end through fusion.run_full_pipeline (Part 5.7): the part's final verdict is not PASS."""
    try:
        run_full_pipeline = resolve("fusion.pipeline", "run_full_pipeline")
    except GoldenTestUnavailable as exc:
        pytest.skip(f"golden test (pipeline path) not runnable yet: {exc} (P5.1 stub / P5.3 real)")
    lot: LotDataset = golden_lot()
    results = run_full_pipeline(lot, ScreeningConfig())
    results = results if isinstance(results, AnalysisResults) else AnalysisResults.model_validate(results)
    matches = [a for a in results.assessments if a.component_id == GOLDEN_COMPONENT_ID]
    assert len(matches) == 1, (
        f"GOLDEN TEST FAILED - expected one RiskAssessment for {GOLDEN_COMPONENT_ID}, got {len(matches)} "
        f"(expected while fusion is the P5.1 stub, until P5.3)")
    assessment = matches[0]
    assert assessment.verdict != "PASS", (
        f"GOLDEN TEST FAILED - {_EXAMPLE} must be flagged, final verdict was PASS (AGENTS.md rule 5)")
    assert assessment.worst_parameter == GOLDEN_PARAMETER
