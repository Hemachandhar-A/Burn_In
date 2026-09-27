"""P4.3 / E3 steps 6-7: physics-vs-model disagreement, full ModuleBResult recording, and the
out-of-scope-parameter rule - the real module_b.predict that P5's fusion calls in-process."""

import inspect

import pytest

from contracts import ModuleBInput, ModuleBResult, to_module_b_input
from features.compute import compute
from generator.lot import generate_lot
from module_b import predict
from module_b.baselines import physics_baselines
from module_b.calibration import calibrate_drift_models, forecast
from module_b.model import view_at_24h
from module_b.predictor import SYNTHETIC_LOTS, TRAINED_PARAMETERS, synthetic_models

FORECAST_FIELDS = (
    "predicted_168h", "interval_lower", "interval_upper", "physics_baseline_prediction",
    "physics_disagreement_gap", "drift_rate", "exceeds_safety_slope", "safety_slope",
    "lower_bound_exceeds_safety_slope",
)


def _lot_inputs(seed: int, part_number: str = "PN-1") -> list[ModuleBInput]:
    lot = generate_lot(f"{part_number}-T{seed}", part_number, seed, account_id="a")
    return [to_module_b_input(f) for f in compute(lot.dataset)]


@pytest.fixture(scope="module")
def models():
    return synthetic_models("PN-1")


@pytest.fixture(scope="module")
def lot():
    return _lot_inputs(300)


# --- Part 7.3 Module B row -------------------------------------------------------------------


def test_parameter_outside_the_trained_three_is_forecast_unavailable_never_a_guess(models, lot):
    # context.md 5.9: an unrecognized parameter gets forecast_unavailable=True and every forecast field None.
    odd = [i.model_copy(update={"parameter": "vdd_ripple"}) for i in lot[:5]]
    for r in predict(odd, models=models):
        assert r.forecast_unavailable is True
        assert all(getattr(r, f) is None for f in FORECAST_FIELDS)
        assert r.parameter == "vdd_ripple"


def test_out_of_scope_parameter_is_declined_even_if_a_model_was_somehow_trained_for_it():
    # The rule is the trained-three gate itself, not merely "no model happened to exist".
    frames = [f.model_copy(update={"parameter": "vdd_ripple"})
              for s in range(4) for f in compute(generate_lot(f"X{s}", "PN-1", s, account_id="a").dataset)
              if f.parameter == "iddq"]
    rogue = calibrate_drift_models(frames)
    assert ("PN-1", "vdd_ripple") in rogue
    inputs = [to_module_b_input(f) for f in frames[:3]]
    assert all(r.forecast_unavailable for r in predict(inputs, models=rogue))


def test_physics_baseline_is_the_lot_fitted_power_law_and_the_gap_is_computed_from_it(models, lot):
    # Baselines are fit over the whole batch (the lot), not one part at a time - the exponent is per lot.
    base = physics_baselines(lot)
    for i, r in zip(lot, predict(lot, models=models)):
        expected = base[(i.lot_id, i.component_id, i.parameter)].power_law
        assert r.physics_baseline_prediction == pytest.approx(expected)
        assert r.physics_disagreement_gap == pytest.approx(abs(r.predicted_168h - expected))
        assert r.physics_disagreement_gap >= 0


@pytest.mark.parametrize("horizon", ["96h", "24h"])
def test_interval_ordering_on_module_b_result(models, lot, horizon):
    inputs = lot if horizon == "96h" else [view_at_24h(i) for i in lot]
    for r in predict(inputs, models=models):
        assert r.interval_lower <= r.predicted_168h <= r.interval_upper


# --- E3 step 7: every field recorded, for every part -----------------------------------------


def test_every_available_forecast_records_all_e3_step7_fields(models, lot):
    results = predict(lot, models=models)
    assert len(results) == len(lot)
    for r in results:
        assert isinstance(r, ModuleBResult)
        assert r.forecast_unavailable is False
        assert all(getattr(r, f) is not None for f in FORECAST_FIELDS)
        assert r.exceeds_safety_slope == (r.drift_rate > r.safety_slope)


def test_results_carry_exactly_the_calibrated_forecast_values(models, lot):
    for r, fc in zip(predict(lot, models=models), forecast(models, lot)):
        assert (r.predicted_168h, r.interval_lower, r.interval_upper) == (
            fc.predicted_168h, fc.interval_lower, fc.interval_upper)
        assert (r.drift_rate, r.safety_slope, r.exceeds_safety_slope) == (
            fc.drift_rate, fc.safety_slope, fc.exceeds_safety_slope)


def test_part_number_without_a_calibrated_model_is_unavailable(lot):
    for r in predict(lot[:6], models={}):
        assert r.forecast_unavailable is True
        assert all(getattr(r, f) is None for f in FORECAST_FIELDS)


def test_mixed_batch_keeps_order_and_decides_per_input(models, lot):
    batch = [lot[0], lot[1].model_copy(update={"parameter": "gain"}), view_at_24h(lot[2])]
    out = predict(batch, models=models)
    assert [(r.component_id, r.parameter) for r in out] == [(i.component_id, i.parameter) for i in batch]
    assert [r.forecast_unavailable for r in out] == [False, True, False]


def test_predict_on_empty_input_returns_empty(models):
    assert predict([], models=models) == []


def test_predict_takes_the_canonical_module_b_input():
    assert inspect.signature(predict).parameters["frames"].annotation == list[ModuleBInput]


# --- TEMP default model source (CONTRACT_CHANGES 2026-09-26 P4, OPEN) ------------------------


def test_trained_parameters_are_exactly_the_generator_three():
    assert TRAINED_PARAMETERS == frozenset({"iddq", "leakage", "prop_delay"})


def test_synthetic_models_are_cached_deterministic_and_keyed_to_the_part_number(models):
    assert synthetic_models("PN-1") is models
    assert set(models) == {("PN-1", p) for p in TRAINED_PARAMETERS}
    assert SYNTHETIC_LOTS >= 2


def test_predict_without_models_uses_the_synthetic_prior_for_that_part_number(models, lot):
    assert predict(lot[:10]) == predict(lot[:10], models=models)


# --- lot_id population (contract 2bc522c) ---------------------------------------------------------


def test_result_lot_id_matches_its_input_on_both_construction_paths(models):
    """predict() builds ModuleBResult in two places - the real forecast and _unavailable - and both must
    carry the input's lot_id, including when lots are batched together and reuse component IDs."""
    lot_a, lot_b = _lot_inputs(320), _lot_inputs(321)
    # Real component IDs are only unique within a lot: strip the lot prefix so both lots share every ID.
    reused = lambda lot: [i.model_copy(update={"component_id": f"U{i.component_id[-4:]}"}) for i in lot]  # noqa: E731
    batch = reused(lot_a) + reused(lot_b)
    assert {i.lot_id for i in batch} == {"PN-1-T320", "PN-1-T321"}

    # Path 1: real forecast.
    results = predict(batch, models=models)
    assert any(not r.forecast_unavailable for r in results)
    assert [r.lot_id for r in results] == [i.lot_id for i in batch]

    # Path 2a: unavailable because the parameter is outside the trained three.
    odd = [i.model_copy(update={"parameter": "vdd_ripple"}) for i in batch[:3] + batch[-3:]]
    unavailable = predict(odd, models=models)
    assert all(r.forecast_unavailable for r in unavailable)
    assert [r.lot_id for r in unavailable] == [i.lot_id for i in odd]

    # Path 2b: unavailable because a required input is non-finite (a different trigger, same builder).
    bad = [i.model_copy(update={"value_24h": float("nan")}) for i in batch[:2] + batch[-2:]]
    unusable = predict(bad, models=models)
    assert all(r.forecast_unavailable for r in unusable)
    assert [r.lot_id for r in unusable] == [i.lot_id for i in bad]
