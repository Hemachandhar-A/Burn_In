"""P4.1 / E3 step 2: global LightGBM quantile model per part number, trained across lots."""

import numpy as np
import pytest
from lightgbm import LGBMRegressor

from contracts import FeatureFrame, to_module_b_input
from features.compute import compute
from generator.lot import generate_lot
from module_b.baselines import physics_baselines
from module_b.model import (
    FEATURE_NAMES,
    build_training_set,
    feature_matrix,
    make_quantile_regressor,
    predict_168h,
    train_drift_models,
    view_at_24h,
)


def _frame(cid="C1", lot="L1", pn="PN-1", param="iddq", v168=13.0, v96=12.0, t24=24.0, t96=96.0) -> FeatureFrame:
    has96 = v96 is not None
    has168 = v168 is not None
    labels = ["0h", "24h"] + (["96h"] if has96 else []) + (["168h"] if has168 else [])
    hours = {"0h": 0.0, "24h": t24, "96h": t96, "168h": 168.0}
    return FeatureFrame(
        component_id=cid,
        lot_id=lot,
        part_number=pn,
        parameter=param,
        value_0h=10.0,
        value_24h=11.0,
        value_96h=v96,
        value_168h=v168,
        delta_24h=1.0,
        delta_96h=None if v96 is None else v96 - 10.0,
        delta_168h=None if v168 is None else v168 - 10.0,
        lot_median_0h=10.0,
        lot_median_24h=11.0,
        robust_z={k: 0.0 for k in labels},
        lot_size=77,
        used_pooled_fallback=False,
        elapsed_hours={k: hours[k] for k in labels},
    )


def _generated_frames(lot_seeds, part_number="PN-1") -> list[FeatureFrame]:
    frames = []
    for s in lot_seeds:
        frames += compute(generate_lot(f"{part_number}-L{s}", part_number, s, account_id="a").dataset)
    return frames


# --- features -------------------------------------------------------------------------------


def test_feature_matrix_has_one_row_per_input_and_named_columns():
    X = feature_matrix([to_module_b_input(_frame()), to_module_b_input(_frame("C2"))])
    assert X.shape == (2, len(FEATURE_NAMES))


def test_missing_96h_is_nan_not_imputed():
    # AGENTS.md rule 7: LightGBM handles NaN natively - no guessed 96h value.
    X = feature_matrix([to_module_b_input(_frame(v96=None))])
    nan_cols = {FEATURE_NAMES[i] for i in np.flatnonzero(np.isnan(X[0]))}
    assert nan_cols == {"delta_96h", "elapsed_96h"}


def test_features_use_actual_elapsed_hours():
    X = feature_matrix([to_module_b_input(_frame(t24=23.6, t96=97.1))])
    assert X[0, FEATURE_NAMES.index("elapsed_24h")] == pytest.approx(23.6)
    assert X[0, FEATURE_NAMES.index("elapsed_96h")] == pytest.approx(97.1)


def test_view_at_24h_strips_every_trace_of_96h():
    v = view_at_24h(to_module_b_input(_frame()))
    assert v.value_96h is None and v.delta_96h is None
    assert "96h" not in v.robust_z and "96h" not in v.elapsed_hours


# --- training set: no leakage, lot-grouped --------------------------------------------------


def test_training_features_never_see_the_168h_target():
    # AGENTS.md rule 6: changing only the 168h reading must change y and nothing in X.
    a = build_training_set([_frame(v168=13.0)])
    b = build_training_set([_frame(v168=99.0)])
    np.testing.assert_array_equal(a.X, b.X)
    assert not np.array_equal(a.y, b.y)


def test_frames_without_a_168h_reading_are_not_training_rows():
    ts = build_training_set([_frame("C1", v168=None), _frame("C2")])
    assert set(ts.component_ids) == {"C2"}


def test_each_complete_frame_also_trains_its_24h_view():
    ts = build_training_set([_frame("C1"), _frame("C2", v96=None)])
    # C1 contributes its 96h row and its 24h view; C2 only ever had a 24h view.
    assert sorted(ts.component_ids) == ["C1", "C1", "C2"]
    assert int(np.isnan(ts.X[:, FEATURE_NAMES.index("delta_96h")]).sum()) == 2


def test_training_groups_are_lot_ids_for_lot_boundary_splits():
    # AGENTS.md rule 8 - both views of a part stay in its own lot's group.
    ts = build_training_set([_frame("C1", lot="L1"), _frame("C2", lot="L2")])
    assert sorted(ts.groups) == ["L1", "L1", "L2", "L2"]


def test_training_set_rejects_mixed_part_numbers_or_parameters():
    with pytest.raises(ValueError):
        build_training_set([_frame(pn="PN-1"), _frame("C2", pn="PN-2")])
    with pytest.raises(ValueError):
        build_training_set([_frame(param="iddq"), _frame("C2", param="leakage")])


# --- training and prediction ----------------------------------------------------------------


def test_quantile_regressor_is_lightgbm_quantile_loss_with_fixed_seed():
    m = make_quantile_regressor(alpha=0.9, seed=3)
    assert isinstance(m, LGBMRegressor)
    p = m.get_params()
    assert p["objective"] == "quantile" and p["alpha"] == 0.9 and p["random_state"] == 3
    assert p["deterministic"] is True


def test_one_global_model_per_part_number_and_parameter_across_lots():
    frames = _generated_frames([1, 2]) + _generated_frames([3], part_number="PN-2")
    models = train_drift_models(frames)
    assert set(models) == {(pn, p) for pn in ("PN-1", "PN-2") for p in ("iddq", "leakage", "prop_delay")}


def test_untrained_part_number_or_parameter_gets_no_prediction():
    models = train_drift_models(_generated_frames([1, 2]))
    known = to_module_b_input(_generated_frames([9])[0])
    other_pn = known.model_copy(update={"part_number": "PN-UNSEEN"})
    other_param = known.model_copy(update={"parameter": "vdd_ripple"})
    preds = predict_168h(models, [known, other_pn, other_param])
    assert preds[0] is not None and preds[1] is None and preds[2] is None


def test_training_and_prediction_are_deterministic():
    frames = _generated_frames([1, 2])
    held_out = [to_module_b_input(f) for f in _generated_frames([50])]
    assert predict_168h(train_drift_models(frames), held_out) == predict_168h(train_drift_models(frames), held_out)


def test_empty_inputs():
    assert train_drift_models([]) == {}
    assert predict_168h({}, []) == []


def test_higher_quantile_predicts_higher():
    frames = _generated_frames(range(1, 7))
    held_out = [to_module_b_input(f) for f in _generated_frames([60])]
    lo = np.array(predict_168h(train_drift_models(frames, alpha=0.1), held_out))
    hi = np.array(predict_168h(train_drift_models(frames, alpha=0.9), held_out))
    assert np.mean(hi > lo) > 0.9


@pytest.mark.parametrize("horizon", ["96h", "24h"])
def test_model_beats_every_physics_baseline_on_held_out_lots(horizon):
    # E3 step 1: the baselines are what any deployed model must beat. Held-out lots are disjoint from the
    # training lots (AGENTS.md rule 8). MAE is normalized per parameter so iddq's scale doesn't dominate.
    train = _generated_frames(range(12))
    test = _generated_frames(range(100, 106))
    models = train_drift_models(train)
    inputs = [to_module_b_input(f) for f in test]
    if horizon == "24h":
        inputs = [view_at_24h(i) for i in inputs]
    model_pred = predict_168h(models, inputs)
    base = physics_baselines(inputs)

    errors = {"model": [], "persistence": [], "linear": [], "power_law": []}
    for f, i, m in zip(test, inputs, model_pred):
        scale = abs(f.lot_median_0h)
        b = base[(i.lot_id, i.component_id, i.parameter)]
        errors["model"].append(abs(m - f.value_168h) / scale)
        for name in ("persistence", "linear", "power_law"):
            errors[name].append(abs(getattr(b, name) - f.value_168h) / scale)
    mae = {k: float(np.mean(v)) for k, v in errors.items()}
    assert mae["model"] < min(mae["persistence"], mae["linear"], mae["power_law"]), mae
