"""P5.7 explain/shap_b.py: TreeSHAP for Module B's median (point-estimate) quantile booster.

module_b.calibration.CalibratedDriftModel wraps, per horizon, a MAPIE ConformalizedQuantileRegressor
that internally fits three LGBMRegressor quantile models (module_b.model.make_quantile_regressor):
lower (alpha/2), upper (1 - alpha/2), and median (alpha=0.5). predicted_168h's point estimate comes
from the median one - module_b.calibration.forecast reads MAPIE's own y_preds[2] (verified against
mapie==1.5.0's source, mapie/regression/quantile_regression.py: `_MapieQuantileRegressor.predict`
returns `y_preds[2]`, and `single_estimator_ = estimators_[2]` is set identically in both the
prefit and the fit-from-scratch path).

MAPIE 1.5.0's public `ConformalizedQuantileRegressor` API (fit/conformalize/predict/predict_interval/
conformity_scores) has no accessor for the three individual fitted estimators - the one place they
live is the private `_mapie_quantile_regressor.single_estimator_` composed onto it (an
sklearn-convention fitted attribute name, but on an object that is itself private). Reading that
attribute from here is the only way to reach the booster shap.TreeExplainer needs; it does not change
module_b's algorithm, only introspects an already-fitted object, and it is pinned to mapie==1.5.0's
internal layout - a MAPIE upgrade that restructures ConformalizedQuantileRegressor could break this
file without changing module_b/ at all (flagged in the P5.7 report, not a reason to avoid it: there is
no other way to reach a per-feature explanation of Module B's prediction with the locked stack).

Feature scope (AGENTS.md rule 6): FEATURE_NAMES (module_b.model) are built only from 0h/24h/(96h)
fields - the booster's own inputs never include 168h, so nothing extra needs masking here.

Model is reachable at explanation time via the same in-memory object module_b.predictor.predict used:
either the `models` dict `run_full_pipeline`/callers already hold, or module_b.predictor.synthetic_models
(functools.cache'd per part_number) - explain/ takes the model as a parameter rather than re-deriving
it, so both paths work without a second accessor.
"""
import shap

from contracts import ModuleBInput
from explain.cache import ExplainCache
from explain.models import FeatureContribution, ShapExplanation
from module_b.calibration import CalibratedDriftModel, horizon_of
from module_b.model import FEATURE_NAMES, feature_matrix


def explain_module_b(
    frame: ModuleBInput, model: CalibratedDriftModel, cache: ExplainCache | None = None,
) -> ShapExplanation:
    """TreeSHAP contributions for one part's Module B point-estimate (median quantile) prediction, in
    the model's own residual/output space - before module_b.predictor adds the persistence anchor back
    to get predicted_168h. Raises KeyError if `model` has no regressor for `frame`'s horizon
    (forecast_unavailable case) - callers check that first, the same as module_b.predictor.predict does.

    `cache` (Block 4c Part 2): when given, shap.TreeExplainer(booster) is reused for every call whose
    booster is the same object (same part_number/parameter/horizon, since
    module_b.predictor.synthetic_models is itself functools.cache'd) instead of reconstructed -
    TreeExplainer's construction depends only on the booster, so this is numerically identical, only
    the redundant construction is removed. Keyed by id(booster), not by lot. Default None reproduces
    the exact pre-optimization behavior (a fresh TreeExplainer on every call)."""
    horizon = horizon_of(frame)
    booster = model.regressors[horizon]._mapie_quantile_regressor.single_estimator_

    X = feature_matrix([frame])
    if cache is not None:
        key = id(booster)
        if key not in cache.tree_explainers:
            cache.tree_explainers[key] = shap.TreeExplainer(booster)
        explainer = cache.tree_explainers[key]
    else:
        explainer = shap.TreeExplainer(booster)
    shap_values = explainer.shap_values(X)[0]
    base_value = float(explainer.expected_value)
    prediction = float(booster.predict(X)[0])

    contributions = sorted(
        (
            FeatureContribution(feature=name, value=float(X[0, i]), shap_value=float(shap_values[i]))
            for i, name in enumerate(FEATURE_NAMES)
        ),
        key=lambda c: abs(c.shap_value),
        reverse=True,
    )
    return ShapExplanation(
        component_id=frame.component_id,
        parameter=frame.parameter,
        horizon=horizon,
        base_value=base_value,
        model_prediction=prediction,
        contributions=contributions,
    )
