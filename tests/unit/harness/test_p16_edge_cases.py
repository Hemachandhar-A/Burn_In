"""P1.6 edge-case review: the golden test's fixture and adapters (harness/golden.py).

Gaps found on a full re-read, each pinned here before the fix:
    - the lot size came from ScreeningConfig.lot_size_default, a live-editable default (Part 5.1): an even
      value crashed the import, any other value silently changed the worked example
    - used_pooled_fallback followed ScreeningConfig.small_lot_fallback_threshold although the frames' robust
      statistics are always lot-relative
    - the horizon (FEATURE_CHECKPOINTS) and parameter table were mutable module-level dicts
    - golden_result / the lot-size check used bare `assert`, stripped under `python -O`
    - is_flagged counted any non-PASS string - including an off-contract tier - as flagged
    - adapters trusted ModuleAResult instances built with model_construct (no validation), rejected
      same-shaped non-dict objects, and rejected tuples
    - a signature mismatch surfaced as a bare TypeError from deep inside the call
    - the median-part control passed vacuously on an empty result list
    - a stage that exists but lacks its entry point was skipped (masking a real contract break), while a
      stray tests/unit/<name>/ namespace package (pytest's default prepend import mode puts tests/unit on
      sys.path) looked like the stage existing
    - the features and pipeline paths had no output validation at all
"""
import hashlib
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import types
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
import pytest
from pydantic import BaseModel

import contracts
from contracts import AnalysisResults, FeatureFrame, LotDisposition, ModuleAResult, RiskAssessment
from harness import golden
from harness.golden import (
    FEATURE_CHECKPOINTS,
    GOLDEN_COMPONENT_ID,
    GOLDEN_LOT_ID,
    GOLDEN_PARAMETER,
    GoldenEntryPointMissing,
    GoldenTestUnavailable,
    TEMP_detect_module_a,
    TEMP_features_compute,
    assessment_flagged,
    golden_assessment,
    golden_feature_frames,
    golden_lot,
    golden_result,
    is_flagged,
    median_component_ids,
    median_results,
    resolve,
    run_golden_pipeline,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _result(component_id=GOLDEN_COMPONENT_ID, parameter=GOLDEN_PARAMETER, tier="REJECT", **kw):
    fields = {"component_id": component_id, "parameter": parameter, "robust_z": 30.0, "mcd_distance": None,
              "isolation_forest_score": None, "ecod_score": 0.99, "explainable_tags": {"robust_z": True},
              "direction": "above_median", "severity_tier": tier, "severity_cap_reason": None}
    fields.update(kw)
    return ModuleAResult(**fields)


def _all_pass(frames):
    return [_result(component_id=f.component_id, parameter=f.parameter, tier="PASS") for f in frames]


def _fake(monkeypatch, name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _load_golden_copy(monkeypatch, **defaults):
    """A separate copy of harness/golden.py imported against a ScreeningConfig whose defaults were edited -
    the way Settings can edit them live. A copy, not a reload, so no other test sees different objects."""
    patched = type("PatchedScreeningConfig", (contracts.ScreeningConfig,),
                   {"__annotations__": {k: type(v) for k, v in defaults.items()}, **defaults})
    monkeypatch.setattr(contracts, "ScreeningConfig", patched)
    spec = importlib.util.spec_from_file_location("_golden_copy_under_test", golden.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the worked example must not depend on live-editable config ------------------------------------

@pytest.mark.parametrize("lot_size_default", [76, 80, 30, 200])
def test_editing_the_lot_size_default_does_not_change_or_break_the_golden_lot(monkeypatch, lot_size_default):
    copy = _load_golden_copy(monkeypatch, lot_size_default=lot_size_default)
    assert copy.GOLDEN_LOT_SIZE == 77
    assert copy.golden_lot() == golden_lot()
    assert copy.golden_feature_frames() == golden_feature_frames()


@pytest.mark.parametrize("threshold", [78, 100, 1])
def test_frames_report_lot_relative_statistics_whatever_the_fallback_threshold(monkeypatch, threshold):
    """The frames' robust statistics are computed from this lot alone, so used_pooled_fallback must say so -
    a frame claiming a pooled reference it never used would misdescribe its own z-scores."""
    copy = _load_golden_copy(monkeypatch, small_lot_fallback_threshold=threshold)
    assert not any(f.used_pooled_fallback for f in copy.golden_feature_frames())


# --- read-only horizon and parameter table -----------------------------------------------------------

def test_the_feature_horizon_is_read_only():
    with pytest.raises(TypeError):
        FEATURE_CHECKPOINTS["336h"] = 336.0  # type: ignore[index]
    with pytest.raises(TypeError):
        del FEATURE_CHECKPOINTS["168h"]  # type: ignore[attr-defined]
    assert tuple(FEATURE_CHECKPOINTS) == ("0h", "24h", "96h", "168h")
    assert all(set(f.elapsed_hours) == set(FEATURE_CHECKPOINTS) for f in golden_feature_frames())


def test_the_parameter_table_is_read_only():
    with pytest.raises(TypeError):
        golden._PARAMETERS["leakage"] = (99.0, 1.0, "uA")  # type: ignore[index]


def test_each_frame_owns_its_dicts():
    """A Module A that mutates one frame's dict in place must not silently change every other frame."""
    frames = golden_feature_frames()
    assert len({id(f.elapsed_hours) for f in frames}) == len({id(f.robust_z) for f in frames}) == len(frames)
    frames[0].elapsed_hours["0h"] = -1.0
    frames[0].robust_z["0h"] = 99.0
    assert all(f.elapsed_hours["0h"] == 0.0 for f in frames[1:])
    assert all(f.robust_z["0h"] != 99.0 for f in frames[1:])
    assert FEATURE_CHECKPOINTS["0h"] == 0.0
    assert golden_feature_frames()[0].elapsed_hours["0h"] == 0.0


# --- no bare asserts in library code -----------------------------------------------------------------

def _run(code: str, *flags: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *flags, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=False,
                          env={**os.environ, **(env or {})}, timeout=120)


def test_checks_still_fire_under_python_O():
    code = ("from harness.golden import golden_result, median_results\n"
            "for fn in (golden_result, median_results):\n"
            "    try:\n"
            "        fn([])\n"
            "    except AssertionError:\n"
            "        print('raised')\n"
            "    else:\n"
            "        print('silent')\n")
    out = _run(code, "-O")
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["raised", "raised"]


# --- determinism across processes (AGENTS.md rule 9) -------------------------------------------------

def _digest_code() -> str:
    return ("import hashlib, json\n"
            "from harness.golden import golden_lot, golden_feature_frames\n"
            "blob = golden_lot().model_dump_json() + json.dumps([f.model_dump() for f in golden_feature_frames()])\n"
            "print(hashlib.sha256(blob.encode()).hexdigest())\n")


def test_fixture_is_identical_across_processes_and_hash_seeds():
    local = hashlib.sha256((golden_lot().model_dump_json()
                            + json.dumps([f.model_dump() for f in golden_feature_frames()])).encode()).hexdigest()
    digests = set()
    for seed in ("0", "12345"):
        out = _run(_digest_code(), env={"PYTHONHASHSEED": seed})
        assert out.returncode == 0, out.stderr
        digests.add(out.stdout.strip())
    assert digests == {local}


def test_every_reading_is_finite_and_positive():
    values = np.array([r.value for r in golden_lot().readings])
    assert np.isfinite(values).all() and (values > 0).all()


# --- flag definitions: only the contracted vocabulary -----------------------------------------------

@pytest.mark.parametrize("tier", ["WATCH", "FLAGGED", "", "reject"])
def test_is_flagged_rejects_an_off_contract_tier(tier):
    bogus = ModuleAResult.model_construct(**{**_result().model_dump(), "severity_tier": tier})
    with pytest.raises(ValueError, match="severity_tier"):
        is_flagged(bogus)


@pytest.mark.parametrize("verdict,flagged", [("PASS", False), ("WATCH", True), ("REJECT", True)])
def test_assessment_flagged_uses_the_part_verdict_vocabulary(verdict, flagged):
    a = RiskAssessment(component_id=GOLDEN_COMPONENT_ID, lot_id=GOLDEN_LOT_ID, verdict=verdict,
                       module_a_rank=1.0, module_b_rank=1.0, worst_parameter=GOLDEN_PARAMETER,
                       module_a_ran=True, module_b_ran=True, predicted_168h=None, actual_168h=None, explanation_sentence=None)
    assert assessment_flagged(a) is flagged


@pytest.mark.parametrize("verdict", ["REVIEW", "HOLD", "ACCEPT", "pass"])
def test_assessment_flagged_rejects_an_off_contract_verdict(verdict):
    a = RiskAssessment.model_construct(component_id=GOLDEN_COMPONENT_ID, lot_id=GOLDEN_LOT_ID, verdict=verdict,
                                       module_a_rank=1.0, module_b_rank=1.0, worst_parameter=GOLDEN_PARAMETER)
    with pytest.raises(ValueError, match="verdict"):
        assessment_flagged(a)


# --- median-part control must not pass vacuously -----------------------------------------------------

def test_median_results_needs_every_median_pair():
    frames = golden_feature_frames()
    with pytest.raises(AssertionError, match="median"):
        median_results([])
    full = _all_pass(frames)
    got = median_results(full)
    assert {(r.component_id, r.parameter) for r in got} == {
        (c, p) for c in median_component_ids() for p in ("iddq", "leakage", "prop_delay")}
    missing_one = [r for r in full if (r.component_id, r.parameter) != (median_component_ids()[0], "iddq")]
    with pytest.raises(AssertionError, match="median"):
        median_results(missing_one)
    with pytest.raises(AssertionError, match="median"):
        median_results([*full, next(r for r in full if r.component_id == median_component_ids()[0])])


def test_golden_result_failure_names_what_came_back():
    with pytest.raises(AssertionError, match="COMP-001"):
        golden_result([_result(component_id="COMP-001")])


# --- adapter output validation ------------------------------------------------------------------------

def test_detect_output_built_without_validation_is_revalidated(monkeypatch):
    def detect(frames):
        return [ModuleAResult.model_construct(**{**r.model_dump(), "severity_tier": "WATCH"})
                for r in _all_pass(frames)]

    _fake(monkeypatch, "module_a", detect=detect)
    with pytest.raises(ValueError):
        TEMP_detect_module_a(golden_feature_frames())


def test_detect_may_return_a_tuple(monkeypatch):
    _fake(monkeypatch, "module_a", detect=lambda frames: tuple(_all_pass(frames)))
    results = TEMP_detect_module_a(golden_feature_frames())
    assert isinstance(results, list) and len(results) == len(golden_feature_frames())


def test_detect_may_return_same_shaped_objects(monkeypatch):
    class TEMP_LocalResult(BaseModel):  # a P3-side TEMP_ model with the contracted fields
        component_id: str
        parameter: str
        robust_z: float
        mcd_distance: float | None
        isolation_forest_score: float | None
        ecod_score: float
        explainable_tags: dict[str, bool]
        direction: str
        severity_tier: str
        severity_cap_reason: str | None

    @dataclass
    class Plain:
        component_id: str
        parameter: str
        robust_z: float = 0.0
        mcd_distance: float | None = None
        isolation_forest_score: float | None = None
        ecod_score: float = 0.1
        explainable_tags: dict | None = None
        direction: str = "above_median"
        severity_tier: str = "PASS"
        severity_cap_reason: str | None = None

        def __post_init__(self):
            self.explainable_tags = self.explainable_tags or {}

    def detect(frames):
        out = [TEMP_LocalResult(**r.model_dump()) for r in _all_pass(frames[:1])]
        return out + [Plain(f.component_id, f.parameter) for f in frames[1:]]

    _fake(monkeypatch, "module_a", detect=detect)
    results = TEMP_detect_module_a(golden_feature_frames())
    assert all(type(r) is ModuleAResult for r in results)


@pytest.mark.parametrize("bad", ["PASS", {"component_id": "x"}, iter([]), 3])
def test_detect_output_that_is_not_a_sequence_is_rejected(monkeypatch, bad):
    _fake(monkeypatch, "module_a", detect=lambda frames: bad)
    with pytest.raises(TypeError, match="list"):
        TEMP_detect_module_a(golden_feature_frames())


# --- signature mismatches are named, errors inside the stage are not rewritten -----------------------

def test_a_detect_signature_mismatch_is_reported_as_a_contract_gap(monkeypatch):
    _fake(monkeypatch, "module_a", detect=lambda frames, history: [])
    with pytest.raises(TypeError, match="CONTRACT_CHANGES"):
        TEMP_detect_module_a(golden_feature_frames())


def test_a_typeerror_raised_inside_detect_propagates_unchanged(monkeypatch):
    def detect(frames):
        raise TypeError("bug inside module_a")

    _fake(monkeypatch, "module_a", detect=detect)
    with pytest.raises(TypeError, match="^bug inside module_a$"):
        TEMP_detect_module_a(golden_feature_frames())


@pytest.mark.parametrize("make", [
    lambda: (lambda frames, config=None: _all_pass(frames)),
    lambda: (lambda *args: _all_pass(args[0])),
    lambda: partial(lambda extra, frames: _all_pass(frames), None),
    lambda: type("Callable", (), {"__call__": lambda self, frames: _all_pass(frames)})(),
])
def test_compatible_detect_signatures_are_accepted(monkeypatch, make):
    _fake(monkeypatch, "module_a", detect=make())
    assert len(TEMP_detect_module_a(golden_feature_frames())) == len(golden_feature_frames())


# --- resolve: absent -> skip, present-but-broken -> fail ---------------------------------------------

def test_a_package_without_its_entry_point_fails_instead_of_skipping(monkeypatch):
    _fake(monkeypatch, "module_a")
    with pytest.raises(GoldenEntryPointMissing, match="detect"):
        TEMP_detect_module_a(golden_feature_frames())
    assert not issubclass(GoldenEntryPointMissing, GoldenTestUnavailable)


def test_a_non_callable_entry_point_fails(monkeypatch):
    _fake(monkeypatch, "module_a", detect=5)
    with pytest.raises(GoldenEntryPointMissing, match="detect"):
        TEMP_detect_module_a(golden_feature_frames())


@pytest.fixture
def probe_root(tmp_path, monkeypatch):
    """A throwaway sys.path root for real on-disk packages; every probe module is removed afterwards."""
    monkeypatch.syspath_prepend(str(tmp_path))
    before = set(sys.modules)
    yield tmp_path
    for name in set(sys.modules) - before:
        if name.startswith("golden_probe"):
            del sys.modules[name]
    importlib.invalidate_caches()


def _pkg(root: Path, dotted: str, init: str | None = "") -> None:
    path = root.joinpath(*dotted.split("."))
    path.mkdir(parents=True)
    if init is not None:
        (path / "__init__.py").write_text(init)
    importlib.invalidate_caches()


def test_a_stray_tests_namespace_package_is_not_the_stage(probe_root):
    """pytest's prepend import mode puts tests/unit on sys.path, so tests/unit/module_a/ (Part 4's layout)
    imports as a namespace package named module_a when the real module_a/ is absent."""
    _pkg(probe_root, "golden_probe_ns", init=None)
    with pytest.raises(GoldenTestUnavailable, match="golden_probe_ns"):
        resolve("golden_probe_ns", "detect")


def test_a_namespace_package_at_the_repo_root_is_the_stage(probe_root, monkeypatch):
    _pkg(probe_root, "golden_probe_rootns", init=None)
    (probe_root / "golden_probe_rootns" / "detect.py").write_text("def detect(frames):\n    return []\n")
    monkeypatch.setattr(golden, "_REPO_ROOT", probe_root)
    assert resolve("golden_probe_rootns", "detect")([]) == []


def test_a_real_package_resolves_its_entry_point_or_fails(probe_root):
    _pkg(probe_root, "golden_probe_real", init="def detect(frames):\n    return ['ok']\n")
    assert resolve("golden_probe_real", "detect")([]) == ["ok"]
    _pkg(probe_root, "golden_probe_bare")
    with pytest.raises(GoldenEntryPointMissing):
        resolve("golden_probe_bare", "detect")


def test_a_dotted_stage_whose_parent_exists_but_module_does_not_fails(probe_root):
    """fusion/ present without fusion/pipeline.py: Part 5.7 fixes pipeline.py as the orchestrator's home,
    and P5.1 creates it in the same session as fusion/ itself - so this is a break, not 'not built yet'."""
    _pkg(probe_root, "golden_probe_fus")
    with pytest.raises(GoldenEntryPointMissing, match="golden_probe_fus.pipeline"):
        resolve("golden_probe_fus.pipeline", "run_full_pipeline")


def test_a_dotted_stage_with_no_parent_is_unavailable_and_names_the_parent():
    with pytest.raises(GoldenTestUnavailable, match=r"golden_probe_absent/ does not exist"):
        resolve("golden_probe_absent.pipeline", "run_full_pipeline")


def test_a_broken_import_inside_a_real_package_propagates(probe_root):
    _pkg(probe_root, "golden_probe_broken", init="import golden_probe_no_such_dependency\n")
    with pytest.raises(ModuleNotFoundError, match="golden_probe_no_such_dependency"):
        resolve("golden_probe_broken", "detect")


def test_a_broken_submodule_propagates(probe_root):
    _pkg(probe_root, "golden_probe_sub")
    (probe_root / "golden_probe_sub" / "detect.py").write_text("import golden_probe_missing_dep\n")
    importlib.invalidate_caches()
    with pytest.raises(ModuleNotFoundError, match="golden_probe_missing_dep"):
        resolve("golden_probe_sub", "detect")


# --- the features path ----------------------------------------------------------------------------------

def test_features_compute_is_called_with_the_lot_and_validated(monkeypatch):
    seen = {}

    def compute(lot):
        seen["lot"] = lot
        return [f.model_dump() for f in golden_feature_frames()]

    _fake(monkeypatch, "features", compute=compute)
    frames = TEMP_features_compute(golden_lot())
    assert seen["lot"] == golden_lot()
    assert all(type(f) is FeatureFrame for f in frames)


@pytest.mark.parametrize("bad", [None, [{"component_id": "x"}]])
def test_features_output_off_the_contract_is_rejected(monkeypatch, bad):
    _fake(monkeypatch, "features", compute=lambda lot: bad)
    with pytest.raises((TypeError, ValueError)):
        TEMP_features_compute(golden_lot())


def test_features_absent_is_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "features", None)
    with pytest.raises(GoldenTestUnavailable, match="features"):
        TEMP_features_compute(golden_lot())


def test_features_signature_mismatch_is_reported(monkeypatch):
    _fake(monkeypatch, "features", compute=lambda lot, history, config: [])
    with pytest.raises(TypeError, match="CONTRACT_CHANGES"):
        TEMP_features_compute(golden_lot())


# --- the pipeline path ----------------------------------------------------------------------------------

def _analysis(*assessments, lot_id=GOLDEN_LOT_ID):
    return AnalysisResults(assessments=list(assessments), disposition=LotDisposition(
        lot_id=lot_id, status="COMPLETE", pda_result=0.013, verdict="ACCEPT", is_forecast=False))


def _assessment(component_id=GOLDEN_COMPONENT_ID, verdict="REJECT", lot_id=GOLDEN_LOT_ID):
    return RiskAssessment(component_id=component_id, lot_id=lot_id, verdict=verdict, module_a_rank=1.0,
                          module_b_rank=1.0, worst_parameter=GOLDEN_PARAMETER,
                          module_a_ran=True, module_b_ran=True, predicted_168h=None, actual_168h=None, explanation_sentence=None)


def test_golden_assessment_picks_the_golden_component():
    a = _assessment()
    assert golden_assessment(_analysis(_assessment(component_id="G-001", verdict="PASS"), a)) == a


@pytest.mark.parametrize("assessments", [
    [],
    [_assessment(component_id="COMP-001")],
    [_assessment(), _assessment()],
    [_assessment(lot_id="OTHER-LOT")],
])
def test_golden_assessment_needs_exactly_one_for_the_golden_part_in_the_golden_lot(assessments):
    with pytest.raises(AssertionError, match=GOLDEN_COMPONENT_ID):
        golden_assessment(_analysis(*assessments))


def test_golden_assessment_accepts_a_dict_and_revalidates_a_constructed_model():
    assert golden_assessment(_analysis(_assessment()).model_dump()).verdict == "REJECT"
    bogus = AnalysisResults.model_construct(
        assessments=[RiskAssessment.model_construct(**{**_assessment().model_dump(), "verdict": "FLAGGED"})],
        disposition=_analysis().disposition)
    with pytest.raises(ValueError):
        golden_assessment(bogus)


@pytest.mark.parametrize("bad", [None, [], "REJECT"])
def test_golden_assessment_rejects_output_that_is_not_analysis_results(bad):
    with pytest.raises((TypeError, ValueError)):
        golden_assessment(bad)


def test_pipeline_absent_is_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "fusion", None)
    with pytest.raises(GoldenTestUnavailable, match="fusion"):
        run_golden_pipeline()


def test_pipeline_is_called_with_the_golden_lot_and_a_default_config(monkeypatch):
    seen = {}

    def run_full_pipeline(lot, config):
        seen.update(lot=lot, config=config)
        return _analysis(_assessment()).model_dump()

    _fake(monkeypatch, "fusion", __path__=[])
    _fake(monkeypatch, "fusion.pipeline", run_full_pipeline=run_full_pipeline)
    assert golden_assessment(run_golden_pipeline()).verdict == "REJECT"
    assert seen["lot"] == golden_lot()
    assert seen["config"] == contracts.ScreeningConfig()


def test_pipeline_signature_mismatch_names_part_5_7(monkeypatch):
    _fake(monkeypatch, "fusion", __path__=[])
    _fake(monkeypatch, "fusion.pipeline", run_full_pipeline=lambda lot: None)
    with pytest.raises(TypeError, match="5.7"):
        run_golden_pipeline()


def test_a_stage_with_no_introspectable_signature_is_still_called(monkeypatch):
    """inspect.signature raises for some callables (a bad __signature__, some C builtins): the adapter must
    fall back to just calling, not crash or skip."""
    class Opaque:
        __signature__ = "not a Signature"

        def __call__(self, frames):
            return _all_pass(frames)

    with pytest.raises(TypeError):
        import inspect
        inspect.signature(Opaque())
    _fake(monkeypatch, "module_a", detect=Opaque())
    assert len(TEMP_detect_module_a(golden_feature_frames())) == len(golden_feature_frames())


def test_the_golden_lot_is_post_ingestion_and_its_units_are_stable():
    """The fixture enters after ingestion's unit normalization (E7 step 6), so its units are fixed here: one
    unit per parameter across the whole lot, and the worked example's leakage in uA."""
    units = {}
    for r in golden_lot().readings:
        units.setdefault(r.parameter, set()).add(r.unit)
    assert units == {"iddq": {"uA"}, "leakage": {"uA"}, "prop_delay": {"ns"}}
