"""Tests for P3.0 stub — session P3.0 (Stub), IMPLEMENTATION_PLAN.md Part 10.

These tests verify that module_a.detect() returns correctly-shaped ModuleAResult objects
matching the frozen contract in contracts.py, so P5.1 can build against it immediately (R6).

This is the STUB test file — it tests shape/contract only, not algorithm correctness.
Algorithm-correctness tests are in test_p3_1.py through test_p3_3.py (sessions P3.1–P3.3).
"""

import pytest
from contracts import FeatureFrame, ModuleAResult


def _make_feature_frame(
    component_id: str = "C001",
    lot_id: str = "LOT001",
    part_number: str = "PN-42X",
    parameter: str = "iddq",
    value_0h: float = 10.0,
    value_24h: float = 11.0,
    value_96h=12.0,
    value_168h=13.0,
    lot_size: int = 50,
    used_pooled_fallback: bool = False,
) -> FeatureFrame:
    """Minimal valid FeatureFrame fixture for use across module_a tests."""
    return FeatureFrame(
        component_id=component_id,
        lot_id=lot_id,
        part_number=part_number,
        parameter=parameter,
        value_0h=value_0h,
        value_24h=value_24h,
        value_96h=value_96h,
        value_168h=value_168h,
        delta_24h=value_24h - value_0h,
        delta_96h=(value_96h - value_0h) if value_96h is not None else None,
        delta_168h=(value_168h - value_0h) if value_168h is not None else None,
        lot_median_0h=10.0,
        lot_median_24h=11.0,
        robust_z={"0h": 0.0, "24h": 0.1, "96h": 0.2, "168h": 0.3},
        lot_size=lot_size,
        used_pooled_fallback=used_pooled_fallback,
        elapsed_hours={"0h": 0.0, "24h": 24.0, "96h": 96.0, "168h": 168.0},
    )


class TestStubOutputShape:
    """P3.0: stub must return ModuleAResult with the exact contracted shape."""

    def test_detect_returns_list(self):
        from module_a.detect import detect

        frames = [_make_feature_frame()]
        results = detect(frames)
        assert isinstance(results, list)

    def test_detect_returns_one_result_per_frame(self):
        from module_a.detect import detect

        frames = [_make_feature_frame("C001"), _make_feature_frame("C002")]
        results = detect(frames)
        assert len(results) == len(frames)

    def test_result_is_module_a_result_instance(self):
        from module_a.detect import detect

        frames = [_make_feature_frame()]
        results = detect(frames)
        assert isinstance(results[0], ModuleAResult)

    def test_component_id_matches_frame(self):
        from module_a.detect import detect

        frame = _make_feature_frame(component_id="PART-XYZ")
        results = detect([frame])
        assert results[0].component_id == "PART-XYZ"

    def test_parameter_matches_frame(self):
        from module_a.detect import detect

        frame = _make_feature_frame(parameter="leakage")
        results = detect([frame])
        assert results[0].parameter == "leakage"

    def test_robust_z_is_float(self):
        from module_a.detect import detect

        results = detect([_make_feature_frame()])
        assert isinstance(results[0].robust_z, float)

    def test_ecod_score_is_float(self):
        from module_a.detect import detect

        results = detect([_make_feature_frame()])
        assert isinstance(results[0].ecod_score, float)

    def test_explainable_tags_has_required_keys(self):
        """explainable_tags must carry all four detector keys (contracts.py line 154)."""
        from module_a.detect import detect

        results = detect([_make_feature_frame()])
        tags = results[0].explainable_tags
        assert isinstance(tags, dict)
        for key in ("robust_z", "mcd", "isolation_forest", "ecod"):
            assert key in tags, f"missing key: {key}"
            assert isinstance(tags[key], bool)

    def test_direction_is_valid_literal(self):
        from module_a.detect import detect

        results = detect([_make_feature_frame()])
        assert results[0].direction in ("above_median", "below_median")

    def test_severity_tier_is_valid_literal(self):
        from module_a.detect import detect

        results = detect([_make_feature_frame()])
        assert results[0].severity_tier in ("PASS", "REVIEW", "REJECT")

    def test_severity_cap_reason_is_none_or_str(self):
        from module_a.detect import detect

        results = detect([_make_feature_frame()])
        cap = results[0].severity_cap_reason
        assert cap is None or isinstance(cap, str)

    def test_mcd_distance_none_when_lot_small(self):
        """mcd_distance must be None when lot_size < 30 (contracts.py / context.md 4.2)."""
        from module_a.detect import detect

        small_lot_frame = _make_feature_frame(lot_size=25)
        results = detect([small_lot_frame])
        assert results[0].mcd_distance is None

    def test_mcd_distance_float_or_none(self):
        """On a sufficient-size lot, mcd_distance must be a float or None (cold-start)."""
        from module_a.detect import detect

        large_lot_frame = _make_feature_frame(lot_size=50)
        results = detect([large_lot_frame])
        mcd = results[0].mcd_distance
        assert mcd is None or isinstance(mcd, float)

    def test_isolation_forest_score_is_float_or_none(self):
        """isolation_forest_score is None on cold-start (first-ever lot for part number)."""
        from module_a.detect import detect

        results = detect([_make_feature_frame()])
        iso = results[0].isolation_forest_score
        assert iso is None or isinstance(iso, float)

    def test_empty_input_returns_empty_list(self):
        from module_a.detect import detect

        assert detect([]) == []

    def test_accepts_unrecognized_parameter(self):
        """Module A must accept any parameter string -- context.md 5.9 / contracts.py note."""
        from module_a.detect import detect

        frame = _make_feature_frame(parameter="exotic_measurement")
        results = detect([frame])
        assert len(results) == 1
        assert results[0].parameter == "exotic_measurement"

    def test_accepts_in_progress_lot_without_168h(self):
        """value_168h and delta_168h are None on an IN_PROGRESS lot -- must not raise."""
        from module_a.detect import detect

        frame = _make_feature_frame(value_168h=None)
        results = detect([frame])
        assert len(results) == 1

    def test_result_passes_pydantic_validation(self):
        """The returned object must pass ModuleAResult's own Pydantic validation."""
        from module_a.detect import detect

        frames = [_make_feature_frame()]
        results = detect(frames)
        # Re-validate: model_validate re-runs all validators
        validated = ModuleAResult.model_validate(results[0].model_dump())
        assert validated.component_id == results[0].component_id

    def test_multiple_parameters_for_same_component(self):
        """Multiple FeatureFrames with same component_id but different params are valid."""
        from module_a.detect import detect

        frames = [
            _make_feature_frame(component_id="C001", parameter="iddq"),
            _make_feature_frame(component_id="C001", parameter="leakage"),
            _make_feature_frame(component_id="C001", parameter="prop_delay"),
        ]
        results = detect(frames)
        assert len(results) == 3
        params = {r.parameter for r in results}
        assert params == {"iddq", "leakage", "prop_delay"}

    def test_lot_id_populated_from_frame(self):
        """ModuleAResult.lot_id must match the FeatureFrame.lot_id it was built from.

        Added after lot_id was added to ModuleAResult in the develop merge
        (component IDs are only unique within a lot — a batch spanning lots must not collide).
        """
        from module_a.detect import detect

        frame = _make_feature_frame(component_id="C001", lot_id="LOT999")
        results = detect([frame])
        assert results[0].lot_id == "LOT999", (
            "lot_id must round-trip from FeatureFrame to ModuleAResult"
        )

    def test_lot_id_distinct_across_frames(self):
        """When frames carry different lot_ids, each result carries its own lot_id."""
        from module_a.detect import detect

        frames = [
            _make_feature_frame(component_id="C001", lot_id="LOT_A"),
            _make_feature_frame(component_id="C002", lot_id="LOT_B"),
        ]
        results = detect(frames)
        result_a = next(r for r in results if r.component_id == "C001")
        result_b = next(r for r in results if r.component_id == "C002")
        assert result_a.lot_id == "LOT_A"
        assert result_b.lot_id == "LOT_B"
