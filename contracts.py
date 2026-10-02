"""Data contracts for the burn-in screening system.

A verbatim transcription of IMPLEMENTATION_PLAN.md Part 5 (5.1-5.6) - not new design.
FROZEN after session L1 sign-off (G0). Nobody edits this file except the Lead, and only
through the Part 6 contract-change process (CONTRACT_CHANGES.md).

Sections mirror the plan:
  5.1 config   5.2 ingestion -> features   5.3 features -> modules
  5.4 modules -> fusion   5.5 database schema (SQLAlchemy)   5.6 REST API models
"""
import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator
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

    @field_validator("value", "checkpoint_hour")
    @classmethod
    def _must_be_finite(cls, v: float, info) -> float:
        # A literal NaN/inf is neither a reading nor "no reading" (a blank cell is): reject it here, once,
        # so Module A, the feature statistics and the report never see it (rule 7 - never silently coerced).
        if not math.isfinite(v):
            raise ValueError(f"{info.field_name} must be a finite number, got {v!r}")
        return v


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


class ModuleBInput(BaseModel):
    """What Module B is allowed to see: a FeatureFrame minus value_168h/delta_168h. 168h is Module B's
    prediction target, so it is absent from this type by construction (AGENTS.md rule 6) - not filtered
    later by convention. Build it with to_module_b_input(frame), never by hand."""

    component_id: str
    lot_id: str
    part_number: str  # selects the per-part-number model
    parameter: str
    value_0h: float
    value_24h: float
    value_96h: float | None
    delta_24h: float
    delta_96h: float | None
    # Pooled-fallback semantics: on a lot with < 30 parts (used_pooled_fallback=True) these hold the
    # median of the pooled cross-lot reference for this part number when one was supplied, otherwise the
    # lot's own median (still flagged) - not always this lot's own median.
    lot_median_0h: float
    lot_median_24h: float
    robust_z: dict[str, float]  # "0h"/"24h"/"96h" keys only - never "168h"
    lot_size: int
    used_pooled_fallback: bool
    elapsed_hours: dict[str, float]  # "0h"/"24h"/"96h" keys only - never "168h"


def to_module_b_input(frame: FeatureFrame) -> ModuleBInput:
    """The one sanctioned FeatureFrame -> ModuleBInput conversion. Drops value_168h/delta_168h and also
    strips the "168h" key from robust_z and elapsed_hours, which are open-ended dicts that would
    otherwise carry the target through on a Complete lot."""
    data = frame.model_dump(exclude={"value_168h", "delta_168h"})
    data["robust_z"] = {k: v for k, v in frame.robust_z.items() if k != "168h"}
    data["elapsed_hours"] = {k: v for k, v in frame.elapsed_hours.items() if k != "168h"}
    return ModuleBInput(**data)



class ModuleAResult(BaseModel):
    component_id: str
    lot_id: str  # component IDs are only unique within a lot - a batch spanning lots must not collide
    parameter: str
    robust_z: float
    mcd_distance: float | None  # None if lot < 30 (5-feature MCD ceiling - context.md 4.2)
    isolation_forest_score: float | None  # None on a part number's first-ever lot (cold start)
    ecod_score: float
    explainable_tags: dict[str, bool]  # {"robust_z": True, "mcd": True, "isolation_forest": False, "ecod": False}
    direction: Literal["above_median", "below_median"]  # direction-awareness cap - context.md 4.2
    severity_tier: Literal["PASS", "REVIEW", "REJECT"]
    severity_cap_reason: str | None  # populated if capped - context.md 5.16, 6.2
    # E2 step 5's max-combined percentile (0-1) - the same value severity_tier and the direction-awareness
    # cap were computed against. Flagged twice (P1 during P1.7, P5 during P5.2) as missing from this
    # contract - see CONTRACT_CHANGES.md.
    combined_severity: float
    # True iff at least one explainable-tagged detector (robust_z or mcd, per explainable_tags) reached or
    # tied combined_severity; False iff combined_severity was reached solely by unexplainable-tagged
    # detectors (isolation_forest and/or ecod). This is a property of the whole detector set, not a single
    # "worst detector" name - it handles ties and multi-detector cases a single name cannot. Fusion's E12
    # step 2 explainability gate keys off this field, not a hardcoded detector name.
    explainable_corroboration: bool


class ModuleBResult(BaseModel):
    component_id: str
    lot_id: str  # component IDs are only unique within a lot - a batch spanning lots must not collide
    parameter: str
    predicted_168h: float | None  # None if parameter outside trained three
    interval_lower: float | None
    interval_upper: float | None
    physics_baseline_prediction: float | None
    physics_disagreement_gap: float | None
    drift_rate: float | None
    exceeds_safety_slope: bool | None
    safety_slope: float | None  # the calibrated threshold drift_rate was compared against (E3 step 7's "threshold used"); same units as drift_rate; None whenever drift_rate/exceeds_safety_slope are
    # The conservative counterpart to exceeds_safety_slope: the same drift-rate comparison against
    # safety_slope, but with interval_lower in place of predicted_168h - the calibrated interval's lower
    # bound, not the point estimate. STOP_RUN_RECOMMENDED (essential-features.md E12 step 5, context.md
    # 5.18) keys off this field, not exceeds_safety_slope. Same required-but-nullable pattern, None
    # whenever exceeds_safety_slope/safety_slope are.
    lower_bound_exceeds_safety_slope: bool | None
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
    # Per-component detail the stored run diff (context.md 5.15) and the report need. Required-but-nullable
    # like FeatureFrame's optional fields: a producer must state them, never leave them implicit.
    module_a_ran: bool  # Module A scored this component in this run
    module_b_ran: bool  # Module B forecast this component in this run
    predicted_168h: float | None  # Module B's forecast; None when unavailable
    actual_168h: float | None  # the measured 168h once it exists (forecast resolved into an actual); else None
    explanation_sentence: str | None  # E4 step 5's sentence; None until the explainability engine produces it


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
    # Block 4d (additive, nullable, CONTRACT_CHANGES.md): lot metadata from the ingestion form. Older rows
    # (and an old database file, see storage.database.init_db) read back None.
    manufacturer: Mapped[str | None] = mapped_column(default=None)
    date_code: Mapped[str | None] = mapped_column(default=None)


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
# Block 3B Part 2: additive explainability chart payload (E4 steps 1-4). Simple typed rows, not
# explain/models.py's local Pydantic models (that module is deliberately not contracts.py - see its
# own docstring), so the generated frontend TS client sees a plain, readable shape.
# ---------------------------------------------------------------------------


class ShapContributionRow(BaseModel):
    feature: str
    # Nullable (Block 3C, CONTRACT_CHANGES.md 2026-09-30): None means the feature itself is absent for
    # this part (e.g. delta_96h/elapsed_96h before a 96h reading exists, module_b/model.py:32,37's
    # native-missing NaN) - not a guessed value. shap_value stays a finite float regardless.
    value: float | None = None
    shap_value: float


class MCDContributionRow(BaseModel):
    parameter: str
    contribution: float


class EcodDimensionRow(BaseModel):
    dimension: str
    score: float


class ZScoreTableRow(BaseModel):
    parameter: str
    value: float
    lot_median: float
    z: float


class TrajectoryPoint(BaseModel):
    """Block 4c Part 3b: one measured checkpoint of a part's worst parameter over burn-in - built at
    analysis time from the stored FeatureFrame, one point per checkpoint that actually has a value
    (never a guessed/NaN one - rule 7, and the same discipline the earlier SHAP null bug required)."""

    checkpoint_hour: int
    value: float
    lot_median: float | None = None  # only 0h/24h frames carry a lot_median field; None at 96h/168h


class PartExplanation(BaseModel):
    """Per-component explainability payload (E4 steps 1-9): the four chart mechanisms plus the
    text/notes for that one part. Every field optional/defaulted - a PASS part gets none of this
    (AnalysisResults.part_explanations only ever holds non-PASS parts, Part 3g)."""

    shap_contributions: list[ShapContributionRow] = []
    mcd_contributions: list[MCDContributionRow] = []
    ecod_dimensions: list[EcodDimensionRow] = []
    zscore_table: list[ZScoreTableRow] = []
    explanation_sentence: str | None = None
    confidence_qualifier: str | None = None
    severity_cap_note: str | None = None
    unavailable_forecast_note: str | None = None
    # Additive (Block 4c Part 3b, CONTRACT_CHANGES.md 2026-09-30): default [] so a pre-Block-4c stored
    # row still parses.
    trajectory: list[TrajectoryPoint] = []


# ---------------------------------------------------------------------------
# 5.6 REST API - request and response models
# ---------------------------------------------------------------------------


class AnalysisResults(BaseModel):
    """The output of one full pipeline run - see Part 5.7. Reused verbatim by
    LotSummaryResponse (a live lot) and ProjectDataResponse (a stored historical run),
    because they are the same shape by design: a reload is not a different kind of data."""

    assessments: list[RiskAssessment]
    disposition: LotDisposition
    # component_ids with no 0h or 24h reading for some parameter (INSUFFICIENT_DATA, E7 step 7), carried
    # through to a dashboard reload - not just the upload response (LotUploadResponse.insufficient_data_components).
    # Default [] so existing constructors and stored rows without the field keep working (CONTRACT_CHANGES.md).
    insufficient_data_components: list[str] = []
    # Block 3B Part 2 (additive, CONTRACT_CHANGES.md 2026-09-30): keyed by component_id, one
    # PartExplanation per non-PASS assessment (E4 steps 1-9) - a PASS part has no entry, not an
    # empty one. Defaults so a pre-Block-3B stored row still parses.
    part_explanations: dict[str, PartExplanation] = {}
    explanation_summary: str = ""  # E4 step 7's lot-level rollup template
    # Block 3B Part 4 (additive, CONTRACT_CHANGES.md 2026-09-30): GET /parts/{component_id} needs
    # PartDetailResponse.module_a/module_b, but RiskAssessment (the only per-component shape
    # AnalysisResults stored before this) never carried the full ModuleAResult/ModuleBResult - only
    # a fused summary. Keyed by component_id, one entry per analysed component for whichever
    # parameter is that component's worst_parameter - never re-run the pipeline to reconstruct one.
    module_a_results: dict[str, ModuleAResult] = {}
    module_b_results: dict[str, ModuleBResult] = {}


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
    # Optional (Block 3C, CONTRACT_CHANGES.md 2026-09-30): None on an in-progress part - Module A
    # never runs before COMPLETE (documented gap, unchanged); the fused ruling itself is unaffected.
    module_a: ModuleAResult | None = None
    module_b: ModuleBResult | None = None
    explanation_sentence: str
    confidence_qualifier: str  # E4 steps 5-6
    severity_cap_note: str | None  # E4 step 8 - worded per which capping reason applied
    unavailable_forecast_note: str | None  # E4 step 9
    staleness_note: str | None  # E4 step 10
    disposition_history: list[DispositionRecord]
    confirmed_outcomes: list[ConfirmedOutcomeRecord]
    # Additive (Block 3B, CONTRACT_CHANGES.md 2026-09-30): the chart-bearing counterpart to the flat
    # text fields above, which predate this block and stay as-is for backward compatibility.
    explanation: PartExplanation | None = None
    # Additive (Block 4c Part 3a, CONTRACT_CHANGES.md 2026-09-30, Lead ruling D79): the five
    # identifiers a disposition round trip needs (POST /parts/{component_id}/disposition takes
    # project_id/analysis_run_id as query params, not derived from anywhere else) - previously the
    # caller had no way to get these from GET /parts/{component_id} itself. Optional with a None
    # default so an old stored/cached response still parses; fusion/router.py::get_part_detail fills
    # all five on every response for a found part - never None in practice.
    component_id: str | None = None
    lot_id: str | None = None
    project_id: str | None = None
    analysis_run_id: str | None = None
    verdict: Literal["PASS", "WATCH", "REJECT"] | None = None


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
    # Block 4d (additive, default None): lot metadata persisted with the project.
    manufacturer: str | None = None
    date_code: str | None = None
    test_date: datetime | None = None


class ProjectDataResponse(BaseModel):
    analysis_run_id: str
    project_id: str
    results: AnalysisResults
    diff_vs_prior: dict | None  # dict deliberately - heterogeneous; see Part 5.6 note


class EventResponse(BaseModel):
    event_id: str
    project_id: str
    account_id: str
    event_type: Literal["ingest", "checkpoint_add", "analysis_run", "config_change", "timing_flag"]
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
    # Nullable (Block 4a-resume R2, CONTRACT_CHANGES.md 2026-09-30): None means that rate's
    # denominator is genuinely zero (e.g. no Confirmed Defective outcomes yet for fn_rate) - not a
    # guessed 0.0. Was previously required float; the earlier-session workaround that coerced a zero
    # denominator to 0.0 at the API boundary is retired by this widening.
    fn_rate: float | None = None
    fp_rate: float | None = None
    confirmed_outcome_count: int
    status: Literal["OK", "CEILING_EXCEEDED", "INSUFFICIENT_DATA"]  # INSUFFICIENT_DATA below the min count


class DPARecommendation(BaseModel):
    component_id: str
    reason: str


class DPAWorkOrderResponse(BaseModel):
    recommendations: list[DPARecommendation]  # up to 3, per E13 step 5
