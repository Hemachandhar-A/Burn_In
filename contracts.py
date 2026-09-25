"""Data contracts for the burn-in screening system.

A verbatim transcription of IMPLEMENTATION_PLAN.md Part 5 (5.1-5.6) - not new design.
FROZEN after session L1 sign-off (G0). Nobody edits this file except the Lead, and only
through the Part 6 contract-change process (CONTRACT_CHANGES.md).

Sections mirror the plan:
  5.1 config   5.2 ingestion -> features   5.3 features -> modules
  5.4 modules -> fusion   5.5 database schema (SQLAlchemy)   5.6 REST API models
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ---------------------------------------------------------------------------
# 5.1 Config object - every disclosed default, made concrete
# ---------------------------------------------------------------------------


class ScreeningConfig(BaseModel):
    model_config = {"frozen": True}
    fn_fp_cost_ratio: float = 10.0  # context.md 7.12, 8.3 - disclosed judgment call
    pda_threshold: float = 0.05  # context.md 1.7, 7.7
    confirmed_outcome_fn_ceiling: float = 0.05  # context.md 5.17
    min_confirmed_outcomes_for_ceiling: int = 10  # context.md 5.17
    small_lot_fallback_threshold: int = 30  # context.md 5.16 - exact AEC-Q001 minimum
    signoff_timing_flag_minutes: int = 2  # context.md 5.6
    report_history_cap_runs: int = 10  # context.md 7.10
    lot_size_default: int = 77  # context.md 3.3
    defect_prevalence_range: tuple[float, float] = (0.01, 0.08)  # context.md 3.3 - evidence-thin
    power_law_exponent_range: tuple[float, float] = (0.15, 0.30)  # context.md 1.4
    activation_energy_range_eV: tuple[float, float] = (0.3, 2.0)  # context.md 1.4, 3.3
    schema_version: str = "1.0"


class HarnessThresholds(BaseModel):
    """Harness-derived, never hand-set. Written by P1's harness (session P1.7) to
    config/harness_thresholds.yaml; read by module_a/ (P3) in session P3.3."""

    model_config = {"frozen": True}
    module_a_review_threshold: float
    module_a_reject_threshold: float
    combination_strategy: Literal["max", "weighted_average", "meta_model"]  # E5 step 6's winner


# ---------------------------------------------------------------------------
# 5.2 Ingestion -> Features (P1/P2 -> P2, P3, P4)
# ---------------------------------------------------------------------------


class Reading(BaseModel):
    component_id: str
    lot_id: str
    part_number: str
    manufacturer: str
    date_code: str
    parameter: str  # str, not Literal: an unrecognized parameter is a VALID Reading (context.md 5.9)
    checkpoint_hour: float  # explicit numeric, not an assumed 0/24/96/168 - context.md 5.9
    value: float
    unit: str


class LotDataset(BaseModel):
    lot_id: str
    part_number: str
    status: Literal["IN_PROGRESS", "COMPLETE"]
    readings: list[Reading]
    account_id: str  # ingestion attribution - context.md 7.3


class FeatureFrame(BaseModel):
    """One frame per (component, parameter) pair - value_* are scalars, so the frame is
    already parameter-scoped."""

    component_id: str
    lot_id: str
    part_number: str  # lets Module B pick its per-part-number model without a separate argument
    parameter: str  # which parameter this frame is about
    value_0h: float
    value_24h: float
    value_96h: float | None
    value_168h: float | None  # populated only on a Complete lot - Module A's post-hoc screening (context.md 7.1)
    delta_24h: float
    delta_96h: float | None
    delta_168h: float | None
    # Pooled-fallback semantics: on a lot with < 30 parts (used_pooled_fallback=True) these hold the
    # median of the pooled cross-lot reference for this part number when one was supplied, otherwise the
    # lot's own median (still flagged) - not always this lot's own median.
    lot_median_0h: float
    lot_median_24h: float
    robust_z: dict[str, float]  # keyed per checkpoint label ("0h", "24h", "96h", "168h"); parameter is the frame's own field
    lot_size: int
    used_pooled_fallback: bool  # < 30 parts - context.md 5.16
    elapsed_hours: dict[str, float]  # actual elapsed hours keyed by checkpoint label ("0h", "24h", "96h", "168h"); irregular checkpoints allowed


# Unrecognized-parameter handling (context.md 5.9): a `parameter` outside
# {iddq, leakage, prop_delay} is a valid Reading - Module A must accept it.
# FeatureFrame is always fully populated for any parameter present in the readings;
# "unrecognized" shows up on ModuleBResult (forecast_unavailable=True, predicted_168h=None),
# which downstream must treat as "forecast unavailable," never as zero or a silent drop.

# ---------------------------------------------------------------------------
# 5.3 Features -> Module A / Module B (P2 -> P3, P4)
# ---------------------------------------------------------------------------


class ModuleAResult(BaseModel):
    component_id: str
    parameter: str
    robust_z: float
    mcd_distance: float | None  # None if lot < 30 (5-feature MCD ceiling - context.md 4.2)
    isolation_forest_score: float | None  # None on a part number's first-ever lot (cold start)
    ecod_score: float
    explainable_tags: dict[str, bool]  # {"robust_z": True, "mcd": True, "isolation_forest": False, "ecod": True}
    direction: Literal["above_median", "below_median"]  # direction-awareness cap - context.md 4.2
    severity_tier: Literal["PASS", "REVIEW", "REJECT"]
    severity_cap_reason: str | None  # populated if capped - context.md 5.16, 6.2


class ModuleBResult(BaseModel):
    component_id: str
    parameter: str
    predicted_168h: float | None  # None if parameter outside trained three
    interval_lower: float | None
    interval_upper: float | None
    physics_baseline_prediction: float | None
    physics_disagreement_gap: float | None
    drift_rate: float | None
    exceeds_safety_slope: bool | None
    forecast_unavailable: bool  # explicit flag - context.md 5.9


# ---------------------------------------------------------------------------
# 5.4 Module results -> Fusion (P3, P4 -> P5)
# ---------------------------------------------------------------------------


class RiskAssessment(BaseModel):
    component_id: str
    lot_id: str
    verdict: Literal["PASS", "WATCH", "REJECT"]
    module_a_rank: float
    module_b_rank: float  # two separate rankings, never fused - context.md 6.3
    worst_parameter: str


class LotDisposition(BaseModel):
    lot_id: str
    status: Literal["IN_PROGRESS", "COMPLETE"]
    pda_result: float
    verdict: Literal[
        "LOT_ON_TRACK", "LOT_AT_RISK", "STOP_RUN_RECOMMENDED", "ACCEPT", "HOLD", "REJECT"
    ]  # forecast wording vs. final wording - context.md 5.18, never conflated
    is_forecast: bool


# ---------------------------------------------------------------------------
# 5.5 Database schema - six tables, all append-only (no UPDATE anywhere)
# P2 owns the write path and the repository API; nobody else writes SQL.
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    account_id: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    role: Mapped[str]
    pin_hash: Mapped[str]  # argon2-cffi hash, never the raw PIN


class Project(Base):
    __tablename__ = "projects"
    project_id: Mapped[str] = mapped_column(primary_key=True)
    lot_id: Mapped[str] = mapped_column(index=True)
    part_number: Mapped[str]
    test_date: Mapped[datetime]  # lot-level physical test date from the ingestion metadata form (E7 step 1); distinct from created_at
    created_at: Mapped[datetime]
    created_by: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))


class ProjectData(Base):
    __tablename__ = "project_data"
    analysis_run_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    raw_data: Mapped[str]  # JSON-serialized
    results_json: Mapped[str]  # JSON-serialized AnalysisResults (5.6) - identical to E9's JSON export
    diff_vs_prior: Mapped[str | None]  # JSON-serialized; null only for a project's first-ever run
    created_at: Mapped[datetime]


class Event(Base):
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    event_type: Mapped[str]  # constrained to the Literal in EventResponse (5.6) at the API layer
    timestamp: Mapped[datetime]
    payload: Mapped[str]  # JSON-serialized


class DispositionSignoff(Base):
    __tablename__ = "disposition_signoffs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    component_id: Mapped[str] = mapped_column(index=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("project_data.analysis_run_id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    verdict: Mapped[str]  # constrained to Literal["ACCEPT","HOLD","REJECT"] at the API layer
    rationale: Mapped[str]
    timestamp: Mapped[datetime]


class ConfirmedOutcome(Base):
    __tablename__ = "confirmed_outcomes"
    confirmed_outcome_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    component_id: Mapped[str] = mapped_column(index=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("project_data.analysis_run_id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    confirmed_outcome: Mapped[str]  # constrained to the Literal in ConfirmedOutcomeRequest (5.6)
    note: Mapped[str | None]
    recorded_at: Mapped[datetime]


# ---------------------------------------------------------------------------
# 5.6 REST API - request and response models
# ---------------------------------------------------------------------------


class AnalysisResults(BaseModel):
    """The output of one full pipeline run - see Part 5.7. Reused verbatim by
    LotSummaryResponse (a live lot) and ProjectDataResponse (a stored historical run),
    because they are the same shape by design: a reload is not a different kind of data."""

    assessments: list[RiskAssessment]
    disposition: LotDisposition


class LoginRequest(BaseModel):
    account_id: str
    pin: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    account_id: str
    role: str


class LotUploadResponse(BaseModel):
    lot_id: str
    part_number: str
    status: Literal["IN_PROGRESS", "COMPLETE"]
    reading_count: int
    # component_ids with no 0h or 24h reading for some parameter (INSUFFICIENT_DATA, E7 step 7): they get no
    # FeatureFrame, so the uploader must see them here, never as a silent drop (rule 7). Default [] so
    # existing constructors keep working; ingestion populates it.
    insufficient_data_components: list[str] = []


class LotSummaryResponse(AnalysisResults):
    pass


class DispositionRecord(BaseModel):
    project_id: str
    component_id: str  # both required to link to /parts/{component_id} and its project context
    account_id: str
    verdict: Literal["ACCEPT", "HOLD", "REJECT"]
    rationale: str
    timestamp: datetime
    analysis_run_id: str


class ConfirmedOutcomeRecord(BaseModel):
    project_id: str
    component_id: str
    account_id: str
    confirmed_outcome: Literal["Confirmed Good", "Confirmed Defective", "Unknown"]
    note: str | None
    recorded_at: datetime
    analysis_run_id: str


class PartDetailResponse(BaseModel):
    module_a: ModuleAResult
    module_b: ModuleBResult
    explanation_sentence: str
    confidence_qualifier: str  # E4 steps 5-6
    severity_cap_note: str | None  # E4 step 8 - worded per which capping reason applied
    unavailable_forecast_note: str | None  # E4 step 9
    staleness_note: str | None  # E4 step 10
    disposition_history: list[DispositionRecord]
    confirmed_outcomes: list[ConfirmedOutcomeRecord]


class DispositionRequest(BaseModel):
    verdict: Literal["ACCEPT", "HOLD", "REJECT"]
    rationale: str


class ConfirmedOutcomeRequest(BaseModel):
    confirmed_outcome: Literal["Confirmed Good", "Confirmed Defective", "Unknown"]
    note: str | None = None


class ProjectSummary(BaseModel):
    project_id: str
    lot_id: str
    part_number: str
    created_at: datetime
    created_by: str


class ProjectDataResponse(BaseModel):
    analysis_run_id: str
    project_id: str
    results: AnalysisResults
    diff_vs_prior: dict | None  # dict deliberately - heterogeneous; see Part 5.6 note


class EventResponse(BaseModel):
    event_id: str
    project_id: str
    account_id: str
    event_type: Literal["ingest", "checkpoint_add", "analysis_run", "config_change"]
    timestamp: datetime
    payload: dict  # dict deliberately - depends on event_type; see Part 5.6 note


class PendingSettingChange(BaseModel):
    field: Literal["fn_fp_cost_ratio", "pda_threshold", "confirmed_outcome_fn_ceiling"]
    proposed_value: float
    proposed_by: str
    signed_off_by: str | None


class SettingsResponse(BaseModel):
    fn_fp_cost_ratio: float
    pda_threshold: float
    confirmed_outcome_fn_ceiling: float
    pending_changes: list[PendingSettingChange]


class SettingsProposalRequest(BaseModel):
    field: Literal["fn_fp_cost_ratio", "pda_threshold", "confirmed_outcome_fn_ceiling"]
    proposed_value: float


class SettingsSignoffRequest(BaseModel):
    field: Literal["fn_fp_cost_ratio", "pda_threshold", "confirmed_outcome_fn_ceiling"]


class WorklistResponse(BaseModel):
    pending: list[DispositionRecord]  # dispositions with no matching confirmed_outcome yet


class CorrectiveStatusResponse(BaseModel):
    fn_rate: float
    fp_rate: float
    confirmed_outcome_count: int
    status: Literal["OK", "CEILING_EXCEEDED", "INSUFFICIENT_DATA"]  # INSUFFICIENT_DATA below the min count


class DPARecommendation(BaseModel):
    component_id: str
    reason: str


class DPAWorkOrderResponse(BaseModel):
    recommendations: list[DPARecommendation]  # up to 3, per E13 step 5
