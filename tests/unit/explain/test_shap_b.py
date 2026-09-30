"""P5.7 (explain/shap_b.py): TreeSHAP for Module B's median-quantile booster."""
import pytest

from contracts import to_module_b_input
from features.compute import compute
from generator.lot import generate_lot
from module_b.calibration import calibrate_drift_models, horizon_of
from module_b.model import FEATURE_NAMES

from explain.models import ShapExplanation
from explain.shap_b import explain_module_b

TRAIN_SEEDS = range(14)
PART_NUMBER = "PN-1"


@pytest.fixture(scope="module")
def models():
    lots = [generate_lot(f"{PART_NUMBER}-L{s}", PART_NUMBER, s, account_id="a") for s in TRAIN_SEEDS]
    frames = [f for g in lots for f in compute(g.dataset)]
    return calibrate_drift_models(frames)


@pytest.fixture(scope="module")
def sample_input(models):
    lot = generate_lot(f"{PART_NUMBER}-CHECK", PART_NUMBER, 999, account_id="a")
    frames = compute(lot.dataset)
    frame = next(f for f in frames if f.parameter == "iddq")
    return to_module_b_input(frame)


def test_returns_a_shap_explanation(models, sample_input):
    model = models[(PART_NUMBER, "iddq")]
    result = explain_module_b(sample_input, model)
    assert isinstance(result, ShapExplanation)
    assert result.component_id == sample_input.component_id
    assert result.parameter == "iddq"
    assert result.horizon == horizon_of(sample_input)


def test_additivity_matches_the_boosters_own_prediction(models, sample_input):
    """base_value + sum(shap) must equal the booster's own prediction for this part, within 1e-6 -
    the model's raw residual-space output, not predicted_168h (which adds the persistence anchor)."""
    model = models[(PART_NUMBER, "iddq")]
    result = explain_module_b(sample_input, model)
    total = result.base_value + sum(c.shap_value for c in result.contributions)
    assert total == pytest.approx(result.model_prediction, abs=1e-6)


def test_deterministic_on_two_calls(models, sample_input):
    model = models[(PART_NUMBER, "iddq")]
    r1 = explain_module_b(sample_input, model)
    r2 = explain_module_b(sample_input, model)
    assert r1 == r2


def test_uses_only_0h_24h_96h_features_never_168h(models, sample_input):
    """AGENTS.md rule 6: Module B's explanation may only use features available at the 0h/24h(/96h)
    horizon. FEATURE_NAMES itself has no 168h-derived column; assert the explanation's own feature
    names are exactly that set, so a future FEATURE_NAMES change surfaces here too."""
    model = models[(PART_NUMBER, "iddq")]
    result = explain_module_b(sample_input, model)
    feature_names = {c.feature for c in result.contributions}
    assert feature_names == set(FEATURE_NAMES)
    assert not any("168h" in name for name in feature_names)


def test_contributions_sorted_by_absolute_shap_value_descending(models, sample_input):
    model = models[(PART_NUMBER, "iddq")]
    result = explain_module_b(sample_input, model)
    magnitudes = [abs(c.shap_value) for c in result.contributions]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_raises_when_the_horizon_has_no_regressor(models, sample_input):
    model = models[(PART_NUMBER, "iddq")]
    stripped = model.__class__(**{**model.__dict__, "regressors": {}})
    with pytest.raises(KeyError):
        explain_module_b(sample_input, stripped)
