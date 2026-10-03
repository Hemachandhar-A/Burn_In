"""F24 Part 1: the out-of-range guard (module_b.guard) - T1 boundaries, T2 scale sweep."""

import pytest

from contracts import LotDataset, ModuleBInput, to_module_b_input
from features.compute import compute
from generator.lot import generate_lot
from ingestion.units import normalize_readings
from module_b import guard, predict
from module_b.guard import InputRanges, fit_ranges, out_of_range_reason
from module_b.predictor import synthetic_models

RANGES = InputRanges(value_0h=(2.0, 50.0), lot_median_0h=(4.0, 30.0), rel_24h=(-0.05, 1.0), rel_96h=(-0.05, 2.0))


def _frame(**kw) -> ModuleBInput:
    base = dict(
        component_id="U1", lot_id="L", part_number="PN", parameter="iddq", value_0h=10.0, value_24h=10.8,
        value_96h=11.5, delta_24h=0.8, delta_96h=1.5, lot_median_0h=10.0, lot_median_24h=10.8,
        robust_z={"0h": 0.0, "24h": 0.0, "96h": 0.0}, lot_size=77, used_pooled_fallback=False,
        elapsed_hours={"0h": 0.0, "24h": 24.0, "96h": 96.0},
    )
    base.update(kw)
    return ModuleBInput(**base)


def test_inside_the_range_passes_through():
    assert out_of_range_reason(RANGES, _frame()) is None
    assert out_of_range_reason(None, _frame(value_0h=1e9)) is None  # nothing recorded -> nothing to compare


def test_value_0h_boundary_is_the_margin_times_the_edge():
    hi = 50.0 * guard.LEVEL_MARGIN
    lo = 2.0 / guard.LEVEL_MARGIN
    # lot median is kept in range so only the part's own level is under test
    assert out_of_range_reason(RANGES, _frame(value_0h=hi, value_24h=hi * 1.05, value_96h=None)) is None
    assert out_of_range_reason(RANGES, _frame(value_0h=lo, value_24h=lo * 1.05, value_96h=None)) is None
    just_above = out_of_range_reason(RANGES, _frame(value_0h=hi * 1.0001, value_24h=hi * 1.05, value_96h=None))
    just_below = out_of_range_reason(RANGES, _frame(value_0h=lo * 0.9999, value_24h=lo * 1.05, value_96h=None))
    assert just_above is not None and "0h value" in just_above
    assert just_below is not None and "0h value" in just_below


def test_lot_median_boundary():
    hi = 30.0 * guard.LOT_MARGIN
    assert out_of_range_reason(RANGES, _frame(lot_median_0h=hi)) is None
    reason = out_of_range_reason(RANGES, _frame(lot_median_0h=hi * 1.0001))
    assert reason is not None and "lot median" in reason
    assert out_of_range_reason(RANGES, _frame(lot_median_0h=4.0 / guard.LOT_MARGIN * 0.9999)) is not None


def test_relative_change_boundary_uses_the_span_margin():
    hi24 = 1.0 + guard.REL_MARGIN_SPANS * (1.0 - -0.05)
    v = lambda r: dict(value_24h=10.0 * (1 + r), value_96h=None)  # noqa: E731
    assert out_of_range_reason(RANGES, _frame(**v(hi24 - 1e-6))) is None
    assert "0h-to-24h" in out_of_range_reason(RANGES, _frame(**v(hi24 + 1e-3)))
    hi96 = 2.0 + guard.REL_MARGIN_SPANS * (2.0 - -0.05)
    ok96 = _frame(value_96h=10.0 * (1 + hi96 - 1e-6))
    bad96 = _frame(value_96h=10.0 * (1 + hi96 + 1e-3))
    assert out_of_range_reason(RANGES, ok96) is None
    assert "0h-to-96h" in out_of_range_reason(RANGES, bad96)


@pytest.mark.parametrize("bad", [0.0, -3.0])
def test_non_positive_value_0h_is_declined(bad):
    assert "not positive" in out_of_range_reason(RANGES, _frame(value_0h=bad))


def test_fit_ranges_records_the_calibration_inputs():
    r = fit_ranges([_frame(value_0h=4.0, value_24h=4.4, value_96h=None), _frame(value_0h=8.0, value_24h=8.0, value_96h=12.0)])
    assert r.value_0h == (4.0, 8.0) and r.rel_24h == pytest.approx((0.0, 0.1)) and r.rel_96h == pytest.approx((0.5, 0.5))
    assert fit_ranges([_frame(value_0h=-1.0)]) is None


def test_predict_declines_an_out_of_range_part_with_a_reason_and_no_verdict():
    models = synthetic_models("PN-1")
    lot = generate_lot("PN-1-G1", "PN-1", 301, account_id="a")
    inputs = [to_module_b_input(f) for f in compute(lot.dataset)]
    base = predict(inputs, models=models)
    assert not any(r.forecast_unavailable for r in base)
    scaled = [i.model_copy(update={"value_0h": i.value_0h * 1000, "value_24h": i.value_24h * 1000}) for i in inputs]
    for r in predict(scaled, models=models):
        assert r.forecast_unavailable is True
        assert r.exceeds_safety_slope is None and r.predicted_168h is None and r.drift_rate is None
        assert r.unavailable_reason and "outside the range" in r.unavailable_reason


# --- T2: scale sweep through the route's unit handling and the pipeline's own feature path -----------------


def _module_b_outcomes(readings, status, scaled_parameter: str, k: int):
    scaled = [r.model_copy(update={"value": r.value * 10.0**k}) if r.parameter == scaled_parameter else r for r in readings]
    normalized, errors = normalize_readings(scaled)  # what POST /lots does before the pipeline
    assert not errors
    lot = LotDataset(lot_id="SWEEP", part_number="DEMO-PN", status=status, readings=normalized, account_id="harness")
    out = {}
    for f in compute(lot):
        out[(f.component_id, f.parameter)] = f
    results = predict([to_module_b_input(f) for f in out.values()])
    return {(r.component_id, r.parameter): ("UNAVAILABLE" if r.forecast_unavailable else
                                            "REJECT" if r.exceeds_safety_slope else "PASS") for r in results}


def in_lot_window(readings, param, k) -> bool:
    import numpy as np

    rng = synthetic_models("DEMO-PN")[("DEMO-PN", param)].input_ranges.lot_median_0h
    median = float(np.median([r.value for r in readings if r.parameter == param and r.checkpoint_hour == 0])) * 10.0**k
    return rng[0] / guard.LOT_MARGIN <= median <= rng[1] * guard.LOT_MARGIN


@pytest.mark.parametrize("name,seed,checkpoints,status", [("complete", 5, None, "COMPLETE"), ("in_progress", 1, (0, 24), "IN_PROGRESS")])
def test_scale_sweep_never_gives_a_different_confident_verdict(name, seed, checkpoints, status, capsys):
    from scripts.load_demo_lots import generated_readings

    readings = generated_readings("SWEEP", seed, checkpoints)
    param = "iddq"
    base = _module_b_outcomes(readings, status, param, 0)
    table = []
    for k in range(-3, 4):
        got = _module_b_outcomes(readings, status, param, k)
        table.append((k, sum(v == "REJECT" for key, v in got.items() if key[1] == param),
                      sum(v == "UNAVAILABLE" for key, v in got.items() if key[1] == param)))
        for key, verdict in got.items():
            if key[1] != param:
                assert verdict == base[key]  # other parameters are untouched
            elif verdict != "UNAVAILABLE" and abs(k) >= 2:
                assert verdict == base[key], f"k={k} {key}: {verdict} vs k=0 {base[key]}"
            elif verdict != "UNAVAILABLE" and verdict != base[key]:
                # |k| = 1: a x10 lot can sit inside the calibrated lot-level window (the calibration lots span ~8x),
                # where it is indistinguishable from an ordinary high/low lot - a disclosed limit (FIXES_PLAN.md).
                assert in_lot_window(readings, param, k), f"k={k} {key}: confident {verdict} outside the lot window"
        if abs(k) >= 2:
            assert table[-1][2] == sum(1 for key in got if key[1] == param)  # every scaled part is declined
    with capsys.disabled():
        print(f"\nT2 scale sweep ({name} lot, iddq x 10^k): k, module B REJECTs, unavailable")
        for row in table:
            print("  ", row)
