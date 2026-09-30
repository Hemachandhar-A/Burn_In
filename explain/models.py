"""P5.7 (explain/): local Pydantic models for the four explainability mechanisms (essential-features.md
E4). Local to explain/, not contracts.py - API mapping onto PartDetailResponse/explanation_sentence is
Block 3B's job, not this one. Every field here is read off an already-fitted model or an already-computed
value; nothing here re-derives a detector's own math (AGENTS.md rule 1)."""
from pydantic import BaseModel


class FeatureContribution(BaseModel):
    """One feature's TreeSHAP contribution to Module B's median-quantile prediction."""

    feature: str
    value: float
    shap_value: float


class ShapExplanation(BaseModel):
    """TreeSHAP decomposition of Module B's point-estimate (median quantile) prediction, in the
    model's own residual/output space - before module_b.predictor adds the persistence anchor back
    to get predicted_168h. base_value + sum(shap_value for contributions) == model_prediction."""

    component_id: str
    parameter: str
    horizon: str  # "24h" or "96h" - module_b.calibration.horizon_of
    base_value: float
    model_prediction: float
    contributions: list[FeatureContribution]  # sorted by |shap_value| descending


class ParameterContribution(BaseModel):
    """One parameter's contribution to the squared Mahalanobis distance (may be negative -
    contributions sum to the total, they are not individually bounded like a percentage)."""

    parameter: str
    contribution: float


class MCDExplanation(BaseModel):
    """Per-parameter decomposition of one part's squared Mahalanobis distance at one checkpoint,
    using the fitted MinCovDet's own location_/precision_ (contributions sum to mahalanobis_distance_squared)."""

    component_id: str
    checkpoint: str
    mahalanobis_distance_squared: float
    contributions: list[ParameterContribution]  # sorted by |contribution| descending


class ZScoreRow(BaseModel):
    parameter: str
    value: float
    lot_median: float
    z: float


class ZScoreTable(BaseModel):
    """Per-parameter robust z-score table for one part at one checkpoint, read directly off
    FeatureFrame - no z-score is recomputed here."""

    component_id: str
    checkpoint: str  # "0h" or "24h" - the only checkpoints FeatureFrame carries a named lot_median for
    rows: list[ZScoreRow]  # sorted by parameter name


class DimensionContribution(BaseModel):
    dimension: str  # "value_0h" or "value_24h" - module_a's ECOD feature matrix columns
    score: float


class EcodExplanation(BaseModel):
    """Per-dimension ECOD tail scores for one part, from the fitted ECOD's own `.O` matrix.
    sum(contribution.score) == aggregated_score (PyOD's own aggregation: decision_scores_ = O.sum(axis=1))."""

    component_id: str
    parameter: str
    aggregated_score: float
    contributions: list[DimensionContribution]
