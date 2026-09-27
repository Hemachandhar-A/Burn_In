"""E5 step 3 / IMPLEMENTATION_PLAN.md Part 7.2: the golden-test fixture itself.

The golden test proper (Module A must flag the part) lives in tests/integration/test_golden_module_a.py.
These tests pin the fixture it runs on, so a failure there is always about Module A, never about a lot
that quietly stopped being the problem statement's worked example: lot median leakage 10 uA, one part at
45 uA, a 50 uA datasheet limit the part never crosses.
"""
import sys
import types

import numpy as np
import pytest

from contracts import FeatureFrame, LotDataset, ModuleAResult
from harness import golden
from harness.golden import (
    FEATURE_CHECKPOINTS,
    GOLDEN_COMPONENT_ID,
    GOLDEN_DATASHEET_LIMIT_UA,
    GOLDEN_LOT_ID,
    GOLDEN_LOT_MEDIAN_UA,
    GOLDEN_LOT_SIZE,
    GOLDEN_PARAMETER,
    GOLDEN_PART_VALUE_UA,
    GOLDEN_UNIT,
    GoldenTestUnavailable,
    TEMP_detect_module_a,
    golden_datasheet_limits,
    golden_feature_frames,
    golden_lot,
    golden_result,
    is_flagged,
    median_component_ids,
)
from harness.industry_baselines import dynamic_pat_scores, robust_center_sigma, static_limit_scores


def _values(lot: LotDataset, parameter: str, hour: float) -> dict[str, float]:
    return {r.component_id: r.value for r in lot.readings
            if r.parameter == parameter and r.checkpoint_hour == hour}


# --- the worked example's three numbers, exactly -------------------------------------------------

def test_constants_are_the_problem_statements_worked_example():
    assert (GOLDEN_LOT_MEDIAN_UA, GOLDEN_PART_VALUE_UA, GOLDEN_DATASHEET_LIMIT_UA) == (10.0, 45.0, 50.0)
    assert GOLDEN_PARAMETER == "leakage"
    assert GOLDEN_UNIT == "uA"


def test_lot_shape():
    lot = golden_lot()
    assert isinstance(lot, LotDataset)
    assert lot.status == "COMPLETE"
    assert {r.component_id for r in lot.readings} == set(golden.component_ids())
    assert len(golden.component_ids()) == GOLDEN_LOT_SIZE >= 30  # full-size lot: no pooled fallback, MCD fits
    assert {r.parameter for r in lot.readings} == {"iddq", "leakage", "prop_delay"}
    assert {r.checkpoint_hour for r in lot.readings} == {0.0, 24.0, 96.0, 168.0}
    # one reading per (component, parameter, checkpoint), no duplicates
    keys = [(r.component_id, r.parameter, r.checkpoint_hour) for r in lot.readings]
    assert len(keys) == len(set(keys)) == GOLDEN_LOT_SIZE * 3 * 4
    assert all(r.lot_id == lot.lot_id and r.part_number == lot.part_number for r in lot.readings)


@pytest.mark.parametrize("hour", [0.0, 24.0, 96.0, 168.0])
def test_lot_median_is_exactly_10_and_the_part_reads_45_at_every_checkpoint(hour):
    values = _values(golden_lot(), GOLDEN_PARAMETER, hour)
    assert float(np.median(list(values.values()))) == GOLDEN_LOT_MEDIAN_UA
    assert values[GOLDEN_COMPONENT_ID] == GOLDEN_PART_VALUE_UA


def test_golden_leakage_readings_are_in_microamps():
    lot = golden_lot()
    assert {r.unit for r in lot.readings if r.parameter == GOLDEN_PARAMETER} == {GOLDEN_UNIT}


def test_the_golden_part_is_the_lots_only_outlier_and_sits_above_the_median():
    lot = golden_lot()
    for hour in (0.0, 24.0, 96.0, 168.0):
        values = _values(lot, GOLDEN_PARAMETER, hour)
        healthy = [v for c, v in values.items() if c != GOLDEN_COMPONENT_ID]
        assert max(healthy) < GOLDEN_LOT_MEDIAN_UA * 1.5  # nobody else is anywhere near 45
    # healthy on its other parameters: exactly at the lot median, so only leakage can explain a flag
    for parameter in ("iddq", "prop_delay"):
        for hour in (0.0, 24.0, 96.0, 168.0):
            values = _values(lot, parameter, hour)
            assert values[GOLDEN_COMPONENT_ID] == float(np.median(list(values.values())))


def test_healthy_parts_drift_so_no_delta_is_degenerate():
    """A flat lot would give every part a zero delta - a zero-MAD edge case (Part 7.3 Features row) that
    would make the golden test fail for a reason that has nothing to do with the worked example."""
    lot = golden_lot()
    v0, v168 = _values(lot, GOLDEN_PARAMETER, 0.0), _values(lot, GOLDEN_PARAMETER, 168.0)
    deltas = np.array([v168[c] - v0[c] for c in v0 if c != GOLDEN_COMPONENT_ID])
    assert np.unique(deltas).size > GOLDEN_LOT_SIZE // 2


def test_lot_is_deterministic():
    assert golden_lot() == golden_lot()
    assert golden_feature_frames() == golden_feature_frames()


def test_lot_is_a_part_numbers_first_ever_lot():
    """No cross-lot history exists for this part number, so Isolation Forest is in cold start (E2 step 3):
    the flag has to come from the explainable, lot-relative detectors - which is what makes it REJECT-able
    under E12's explainability gate, and what the worked example is actually about."""
    from harness.held_out import HELD_OUT_PART_NUMBER

    assert golden_lot().part_number == golden.GOLDEN_PART_NUMBER != HELD_OUT_PART_NUMBER


# --- inside the datasheet limit, outside the lot --------------------------------------------------

def test_the_part_is_inside_the_50uA_datasheet_limit_at_every_checkpoint():
    """The whole point of the example: a static datasheet limit - the first industry baseline (E5 step 1) -
    passes this part."""
    scores = static_limit_scores(golden_lot(), golden_datasheet_limits())
    row = scores[(scores.component_id == GOLDEN_COMPONENT_ID) & (scores.parameter == GOLDEN_PARAMETER)]
    assert len(row) == 1
    assert bool(row.evaluable.iloc[0]) and not bool(row.flagged.iloc[0])
    assert row.score.iloc[0] == pytest.approx(GOLDEN_PART_VALUE_UA / GOLDEN_DATASHEET_LIMIT_UA)
    assert not scores.flagged.any()  # the entire lot is in spec


def test_datasheet_limit_is_fresh_and_in_microamps():
    limits = golden_datasheet_limits()
    assert set(limits) == {GOLDEN_PARAMETER}
    assert limits[GOLDEN_PARAMETER].upper == GOLDEN_DATASHEET_LIMIT_UA
    assert limits[GOLDEN_PARAMETER].unit == GOLDEN_UNIT
    limits.clear()
    assert golden_datasheet_limits()


def test_a_published_lot_relative_rule_does_see_the_outlier():
    """Sanity check on the fixture, not a claim about Module A: DPAT (AEC-Q001, robust median +/- 6 robust
    sigma per lot) flags the part and nothing else, so the lot really is a clean one-outlier lot."""
    scores = dynamic_pat_scores(golden_lot())
    flagged = scores[scores.flagged]
    assert set(zip(flagged.component_id, flagged.parameter)) == {(GOLDEN_COMPONENT_ID, GOLDEN_PARAMETER)}


# --- FeatureFrames: Module A's contracted input ---------------------------------------------------

def test_one_frame_per_component_parameter_pair():
    frames = golden_feature_frames()
    assert all(isinstance(f, FeatureFrame) for f in frames)
    pairs = [(f.component_id, f.parameter) for f in frames]
    assert len(pairs) == len(set(pairs)) == GOLDEN_LOT_SIZE * 3
    assert {f.lot_size for f in frames} == {GOLDEN_LOT_SIZE}
    assert not any(f.used_pooled_fallback for f in frames)
    lot = golden_lot()
    assert {(f.lot_id, f.part_number) for f in frames} == {(lot.lot_id, lot.part_number)}


def test_frames_carry_the_complete_lots_168h_read():
    """context.md 7.1 / CONTRACT_CHANGES.md 2026-09-25 Lead SUPERSEDES: Module A screens the full series of a
    COMPLETE lot, so every frame carries the real 168h read - never None, never a placeholder."""
    for f in golden_feature_frames():
        assert set(f.elapsed_hours) == set(FEATURE_CHECKPOINTS) == {"0h", "24h", "96h", "168h"}
        assert set(f.robust_z) == {"0h", "24h", "96h", "168h"}
        assert f.value_168h is not None and f.delta_168h is not None
    golden_frame = next(f for f in golden_feature_frames()
                        if (f.component_id, f.parameter) == (GOLDEN_COMPONENT_ID, GOLDEN_PARAMETER))
    assert (golden_frame.value_168h, golden_frame.delta_168h) == (GOLDEN_PART_VALUE_UA, 0.0)


def test_a_168h_read_never_leaks_into_earlier_checkpoint_fields(monkeypatch):
    """AGENTS.md rule 6's spirit on this frame: each checkpoint's statistics use only that checkpoint's reads.
    Scrambling every 168h read must move only the 168h fields."""
    real_lot = golden_lot()
    scrambled = real_lot.model_copy(update={"readings": [
        r.model_copy(update={"value": r.value * 7.0 + 3.0}) if r.checkpoint_hour == 168.0 else r
        for r in real_lot.readings]})
    before = golden_feature_frames()
    monkeypatch.setattr(golden, "golden_lot", lambda: scrambled)
    after = golden_feature_frames()
    early = ("value_0h", "value_24h", "value_96h", "delta_24h", "delta_96h", "lot_median_0h", "lot_median_24h")
    for b, a in zip(before, after, strict=True):
        assert [getattr(b, k) for k in early] == [getattr(a, k) for k in early]
        assert {k: v for k, v in b.robust_z.items() if k != "168h"} ==                {k: v for k, v in a.robust_z.items() if k != "168h"}
    assert any(b.value_168h != a.value_168h for b, a in zip(before, after))


def test_frames_carry_the_lot_readings_verbatim():
    lot = golden_lot()
    for f in golden_feature_frames():
        v = {h: _values(lot, f.parameter, h)[f.component_id] for h in (0.0, 24.0, 96.0, 168.0)}
        assert (f.value_0h, f.value_24h, f.value_96h, f.value_168h) == (v[0.0], v[24.0], v[96.0], v[168.0])
        assert f.delta_24h == v[24.0] - v[0.0]
        assert f.delta_96h == v[96.0] - v[0.0]
        assert f.delta_168h == v[168.0] - v[0.0]
        assert f.elapsed_hours == {"0h": 0.0, "24h": 24.0, "96h": 96.0, "168h": 168.0}


def test_golden_frame_robust_z_is_the_e2_step1_formula_by_hand():
    """(value - lot_median) / (lot_IQR / 1.35), lot-relative, per checkpoint."""
    lot = golden_lot()
    frame = next(f for f in golden_feature_frames()
                 if (f.component_id, f.parameter) == (GOLDEN_COMPONENT_ID, GOLDEN_PARAMETER))
    assert frame.lot_median_0h == frame.lot_median_24h == GOLDEN_LOT_MEDIAN_UA
    for label, hour in (("0h", 0.0), ("24h", 24.0), ("96h", 96.0), ("168h", 168.0)):
        values = np.array(list(_values(lot, GOLDEN_PARAMETER, hour).values()))
        q75, q25 = np.percentile(values, [75, 25])
        expected = (GOLDEN_PART_VALUE_UA - np.median(values)) / ((q75 - q25) / 1.35)
        assert frame.robust_z[label] == pytest.approx(expected)
        assert frame.robust_z[label] > 6.0  # far beyond any plausible REVIEW threshold
        center, sigma = robust_center_sigma(values)
        assert frame.robust_z[label] == pytest.approx((GOLDEN_PART_VALUE_UA - center) / sigma)


def test_median_parts_have_zero_z_everywhere():
    ids = median_component_ids()
    assert ids and GOLDEN_COMPONENT_ID not in ids
    for f in golden_feature_frames():
        if f.component_id in ids:
            assert f.robust_z == {"0h": 0.0, "24h": 0.0, "96h": 0.0, "168h": 0.0}


def test_the_golden_part_stays_flag_worthy_as_the_lot_widens_by_168h():
    """The healthy spread is 10% wider at 168h while the part holds at 45 uA: its 168h z is the lowest of its
    four, and still far beyond any plausible REVIEW threshold - the flag cannot depend on the tight 0h spread."""
    frame = next(f for f in golden_feature_frames()
                 if (f.component_id, f.parameter) == (GOLDEN_COMPONENT_ID, GOLDEN_PARAMETER))
    z = frame.robust_z
    assert z["168h"] < z["0h"] and z["168h"] == min(z.values())
    assert z["168h"] > 6.0


# --- flag definition and the TEMP_ Module A adapter -----------------------------------------------

def _result(component_id=GOLDEN_COMPONENT_ID, parameter=GOLDEN_PARAMETER, tier="REJECT", **kw):
    fields = {"component_id": component_id, "lot_id": GOLDEN_LOT_ID, "parameter": parameter, "robust_z": 30.0,
              "mcd_distance": None,
              "isolation_forest_score": None, "ecod_score": 0.99, "explainable_tags": {"robust_z": True},
              "direction": "above_median", "severity_tier": tier, "severity_cap_reason": None}
    fields.update(kw)
    return ModuleAResult(**fields)


@pytest.mark.parametrize("tier,flagged", [("PASS", False), ("REVIEW", True), ("REJECT", True)])
def test_flagged_means_any_tier_above_pass(tier, flagged):
    assert is_flagged(_result(tier=tier)) is flagged


def test_golden_result_picks_the_golden_pair():
    results = [_result(component_id="G-001", tier="PASS"), _result(),
               _result(parameter="iddq", tier="PASS")]
    assert golden_result(results) is results[1]


@pytest.mark.parametrize("results", [[], [_result(parameter="iddq")], [_result(), _result()]])
def test_golden_result_rejects_a_missing_or_duplicated_pair(results):
    with pytest.raises(AssertionError, match="exactly one ModuleAResult"):
        golden_result(results)


def _fake_module(monkeypatch, detect):
    module = types.ModuleType("module_a")
    if detect is not None:
        module.detect = detect
    monkeypatch.setitem(sys.modules, "module_a", module)
    # module_a/detect.py is real on disk now; shadow it so the fake package really lacks its entry point
    monkeypatch.setitem(sys.modules, "module_a.detect", None)


def test_adapter_reports_unavailable_when_module_a_does_not_exist(monkeypatch):
    monkeypatch.setitem(sys.modules, "module_a", None)  # import raises ModuleNotFoundError
    with pytest.raises(GoldenTestUnavailable, match="module_a"):
        TEMP_detect_module_a(golden_feature_frames())


def test_adapter_fails_when_module_a_exists_without_detect(monkeypatch):
    """module_a/ exists but exposes no detect(): a contract break to report, never a skip that would hide
    the golden test for good."""
    _fake_module(monkeypatch, None)
    with pytest.raises(golden.GoldenEntryPointMissing, match="detect"):
        TEMP_detect_module_a(golden_feature_frames())


def test_adapter_does_not_hide_a_broken_module_a(monkeypatch):
    """An ImportError from *inside* module_a is a real failure, never a skip."""
    import importlib

    real_import = importlib.import_module

    def broken(name, *a, **kw):
        if name == "module_a":
            raise ModuleNotFoundError("No module named 'pyod_typo'", name="pyod_typo")
        return real_import(name, *a, **kw)

    monkeypatch.delitem(sys.modules, "module_a", raising=False)
    monkeypatch.setattr(golden.importlib, "import_module", broken)
    with pytest.raises(ModuleNotFoundError, match="pyod_typo"):
        TEMP_detect_module_a(golden_feature_frames())


def test_adapter_passes_frames_through_and_validates_results(monkeypatch):
    seen = {}

    def detect(frames):
        seen["frames"] = frames
        return [_result(component_id=f.component_id, parameter=f.parameter, tier="PASS").model_dump()
                for f in frames]

    _fake_module(monkeypatch, detect)
    frames = golden_feature_frames()
    results = TEMP_detect_module_a(frames)
    assert seen["frames"] == frames
    assert all(isinstance(r, ModuleAResult) for r in results)  # dicts coerced through the contract
    assert len(results) == len(frames)


def test_adapter_resolves_detect_on_a_submodule(monkeypatch):
    package = types.ModuleType("module_a")
    sub = types.ModuleType("module_a.detect")
    sub.detect = lambda frames: [_result()]
    package.detect = sub
    monkeypatch.setitem(sys.modules, "module_a", package)
    assert TEMP_detect_module_a(golden_feature_frames()) == [_result()]


def test_resolve_treats_a_missing_parent_package_as_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "fusion", None)
    with pytest.raises(GoldenTestUnavailable, match="fusion/ does not exist"):
        golden.resolve("fusion.pipeline", "run_full_pipeline")


@pytest.mark.parametrize("bad", [None, _result(), [{"component_id": "x"}]])
def test_adapter_rejects_output_off_the_contract(monkeypatch, bad):
    _fake_module(monkeypatch, lambda frames: bad)
    with pytest.raises((TypeError, ValueError)):
        TEMP_detect_module_a(golden_feature_frames())
