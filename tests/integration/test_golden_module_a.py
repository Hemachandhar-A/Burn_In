"""THE GOLDEN TEST - IMPLEMENTATION_PLAN.md Part 7.2, essential-features.md E5 step 3, AGENTS.md rule 5.

    A lot with median leakage 10 uA and a part reading 45 uA, against a 50 uA datasheet limit,
    must be flagged.

The problem statement's own worked example. Every stage that touches module_a/ or fusion/ runs this before
every commit, and it must never regress once Module A is real (P3.3).

Status while stages are still stubs, by design:
    - a stage whose package does not exist on the branch yet -> SKIPPED, with the reason (never a silent pass)
    - a stage that exists but lacks its entry point          -> FAILS (a skip would hide the golden test)
    - a stage that exists but is still a fixed-score stub     -> expected to FAIL until it is real
      (module_a until P3.3, features until P2.4, fusion until P5.3)
    - an ImportError from inside an existing stage            -> FAILS; a broken module is never a skip
    - stage output off its contract                           -> FAILS

The fixture and adapters (harness/golden.py) are pinned by tests/unit/harness/test_harness_golden_fixture.py
and test_p16_edge_cases.py, so a failure here is about the pipeline, not about the lot. Part 7.4: this file is
added, never edited by anyone else - add a new file.
"""
import pytest

from harness.golden import (
    GOLDEN_COMPONENT_ID,
    GOLDEN_DATASHEET_LIMIT_UA,
    GOLDEN_LOT_MEDIAN_UA,
    GOLDEN_PARAMETER,
    GOLDEN_PART_VALUE_UA,
    GoldenTestUnavailable,
    TEMP_detect_module_a,
    TEMP_features_compute,
    assessment_flagged,
    golden_assessment,
    golden_feature_frames,
    golden_lot,
    golden_result,
    is_flagged,
    median_results,
    run_golden_pipeline,
)

_EXAMPLE = (f"lot median {GOLDEN_LOT_MEDIAN_UA:g} uA, part {GOLDEN_COMPONENT_ID} at {GOLDEN_PART_VALUE_UA:g} uA, "
            f"datasheet limit {GOLDEN_DATASHEET_LIMIT_UA:g} uA")


def _available(call, *args, stage: str):
    try:
        return call(*args)
    except GoldenTestUnavailable as exc:
        pytest.skip(f"golden test not runnable yet: {exc} ({stage})")


def _module_a(frames):
    return _available(TEMP_detect_module_a, frames, stage="module_a: P3.0 stub / P3.3 real")


def _pick(select, results, stub_hint: str):
    """golden_result / golden_assessment, with the same GOLDEN TEST FAILED framing as a wrong verdict."""
    try:
        return select(results)
    except AssertionError as exc:
        raise AssertionError(f"GOLDEN TEST FAILED - {exc}. {stub_hint}") from exc


_MODULE_A_STUB = "Expected while module_a is the P3.0 stub (until P3.3); otherwise a real regression."
_FEATURES_STUB = ("Expected while features is the P2.1 stub (until P2.4) or module_a the P3.0 stub (until P3.3); "
                  "otherwise a real regression.")
_FUSION_STUB = "Expected while fusion is the P5.1 stub (until P5.3); otherwise a real regression."


def _golden_failure(result) -> str:
    return (f"GOLDEN TEST FAILED - {_EXAMPLE} must be flagged, got severity_tier={result.severity_tier!r} "
            f"(robust_z={result.robust_z}, cap={result.severity_cap_reason!r}). If module_a is still the P3.0 "
            f"fixed-score stub this is expected until P3.3; otherwise it is a real regression (AGENTS.md rule 5).")


def test_golden_part_is_flagged_by_module_a():
    result = _pick(golden_result, _module_a(golden_feature_frames()), _MODULE_A_STUB)
    assert is_flagged(result), _golden_failure(result)
    # 45 uA against a 10 uA median is an above-median deviation: the direction cap (E2 step 6) never applies
    assert result.direction == "above_median"


def test_golden_lot_parts_on_the_median_pass():
    """The control: a Module A that flags everything would pass the test above. Parts sitting exactly on the
    lot median on every parameter at every checkpoint have nothing to flag - and each must actually be
    scored, so an empty result cannot pass this vacuously."""
    scored = _pick(median_results, _module_a(golden_feature_frames()), _MODULE_A_STUB)
    flagged = sorted((r.component_id, r.parameter, r.severity_tier) for r in scored if is_flagged(r))
    assert not flagged, f"parts exactly on the lot median were flagged: {flagged}"


def test_golden_part_is_flagged_through_features_compute():
    """Same example, but with P2's real feature stage producing Module A's input from the raw lot."""
    frames = _available(TEMP_features_compute, golden_lot(), stage="features: P2.1 stub / P2.4 real")
    result = _pick(golden_result, _module_a(frames), _FEATURES_STUB)
    assert is_flagged(result), (
        f"GOLDEN TEST FAILED - {_EXAMPLE} must be flagged, got severity_tier={result.severity_tier!r} "
        f"(robust_z={result.robust_z}) on the path features.compute -> module_a.detect. {_FEATURES_STUB} "
        f"(AGENTS.md rule 5)")


def test_golden_part_is_flagged_by_the_full_pipeline():
    """End to end through fusion.run_full_pipeline (Part 5.7): the part's final verdict is not PASS."""
    output = _available(run_golden_pipeline, stage="fusion: P5.1 stub / P5.3 real")
    assessment = _pick(golden_assessment, output, _FUSION_STUB)
    assert assessment_flagged(assessment), (
        f"GOLDEN TEST FAILED - {_EXAMPLE} must be flagged, final verdict was PASS. {_FUSION_STUB} "
        f"(AGENTS.md rule 5)")
    assert assessment.worst_parameter == GOLDEN_PARAMETER
