# Implementation Plan — SIH 26170 Burn-In Anomaly Detection System

**How to use this document.** `context.md` says *why* every decision was made. `essential-features.md` / `non-essential-features.md` say *what* to build. This document says *who* builds *what*, *in what order*, against *what frozen interface*, and *how it gets tested and merged*. An agent picks up a session from Part 10 (its own work packet), reads the matching feature section in the other three documents, and implements — this document does not re-explain the reasoning those documents already own.

**Team.** One Lead (owns contracts, integration, PS2, and the PPT in parallel — does not own a build stage) plus five developers (P1–P5). Four (P2–P5) own exactly one build stage end to end. P1 owns three tracks that run at different points in the build: Generator, Harness, and — a resplit made when the stack moved to FastAPI+React — the entire frontend.

**Sessions, not days.** Part 10 is organized as a numbered sequence of sessions per track, each with an explicit prerequisite (which other session must be closed first), not a calendar slot. A team can close several sessions in one sitting or spread one across several — the plan tracks readiness, not the clock.

---

# Part 1 — Governing Rules

These override anything else in this document if they conflict.

**R1 — No ambiguity in shape; disclosed defaults for values.** Every data object's fields, types, and structure are frozen in Part 5 before anyone writes implementation code — an agent never guesses a field name or type. This does **not** mean every tunable number is invented fresh here: `context.md` Part 8 already discloses specific default values for every genuine judgment call (FN:FP ratio, PDA threshold, prevalence range, and others) — those defaults are copied into the frozen contracts as-is, not re-decided. The distinction: structure is zero-ambiguity; values are disclosed, adjustable defaults, exactly as already designed. Contracts are written as Pydantic `BaseModel`s specifically so FastAPI can derive the OpenAPI schema from them directly — the frontend's contract is generated from the backend's, never maintained in parallel.

**R2 — Reuse before you build.** No statistical or ML algorithm is implemented from scratch if a maintained library provides it. `essential-features.md` names the library for every feature. Custom code exists only where those documents explicitly say so (the safety-slope derivation, the risk-fusion rules, explanation templates, guardrail-style checks). This extends to the frontend: no hand-written fetch call or hand-maintained type duplicates what the generated client already provides.

**R3 — One person, one directory.** Every path in Part 4's repository structure has exactly one owner — `frontend/` included. Nobody edits another person's directory — they request a change through the Lead. This is the entire merge-conflict strategy, and it only works if followed literally. **Calling another owner's exposed function is not an edit and is explicitly allowed** — every router imports `identity/`'s `get_current_account`, `ingestion/router.py` imports `fusion/`'s `run_full_pipeline` (5.7), and everyone imports `storage/`'s repository API (5.5). The rule is: import and call, never inline-reimplement, never edit the file it lives in. Three instances of this pattern exist by session 0; if a fourth comes up mid-build, it follows the same rule without needing a new exception written down.

**R4 — Contracts are frozen after session 0, and only the Lead edits them.** `contracts.py` is written by the Lead in session 0, reviewed and signed off by all five developers the same session, and is read-only for everyone else afterward. Changes go through the process in Part 6 — never a direct edit by anyone but the Lead. The generated TS client is downstream of `contracts.py` and the routes built on it — it is never hand-edited either, by anyone, including the Lead; it's regenerated, or it's wrong.

**R5 — Test-driven, stage by stage, comprehensively.** Tests are written before or alongside implementation, never after. Every stage's tests must cover the edge-case checklist for that stage (Part 7.3) before the stage is considered done — not a subjective "comprehensive," a checklist with boxes to tick. This includes the Frontend row, closed by screenshot-verification against `essential-features.md` E6, not by a Python test.

**R6 — Stub your own output before you need someone else's.** Each track writes a stub of its own output, matching the frozen contract, at the start of its first session — before real implementation exists. This is what lets every downstream person start building immediately rather than waiting. For the frontend specifically, "stub" means building the first screens against a locally-mocked response matching the OpenAPI schema, before the real route exists.

**R7 — Nothing merges without its tests passing and one review.** No exceptions, including under deadline pressure — a red `main` blocks the Lead's integration, which blocks everyone. **One narrow, explicitly-named exception, not a loophole**: the Lead's own contracts work (Part 8) commits directly to `develop` rather than through a branch+PR — because the same-session sign-off from all five (session 0) and the `CONTRACT_CHANGES.md` checkpoint review (Part 6) already function as review, arguably more rigorous than a single PR approval. Every other commit, by everyone, including the Lead's own non-contract work (scripts, tooling), follows R7 with no exception.

**R8 — Locked stack, pinned versions, no mid-build substitutions.** Part 3's dependency list and exact versions — Python *and* npm packages alike — are fixed at session 0. Adding a new library mid-build, on either side of the stack, is a request to the Lead, not a unilateral choice.

**R9 — Generated artifacts are regenerated, never hand-edited.** The OpenAPI schema (derived from `contracts.py` + the routes) and the TS client generated from it are both build artifacts, not source of truth. If either looks wrong, the fix is upstream — in `contracts.py` or the route — followed by regeneration, never a direct edit to the generated file.

---

# Part 2 — Team & Roles

| Person | Owns (stage/track) | Owns (features, `essential-features.md` IDs) | Depends on |
|---|---|---|---|
| **Lead** | Contracts, `api/` skeleton, integration, merge, demo/PPT, PS2 in parallel | — (no build stage) | Everyone's completed work, at merge time |
| **P1** | Generator + Harness, **and** the frontend (`frontend/`) | E1, E5, E6 (React implementation) | Frozen contracts for Generator/Harness; each frontend screen additionally depends on the specific backend route it consumes |
| **P2** | Ingestion + Features + Report + Storage schema, plus routers for all of these | E7, E8, E9, E11 (schema — first writer) | P1's generator *output contract* (not the generator itself) |
| **P3** | Module A — no router; output stays internal | E2 | P2's `FeatureFrame` contract |
| **P4** | Module B — no router; output stays internal | E3 | P2's `FeatureFrame` contract — parallel to P3, no shared files |
| **P5** | Fusion + Explainability + Identity/Disposition + CAPA, plus routers for all of these | E4, E10, E12, E13 (backend logic feeding E6's screens) | P3's and P4's result contracts |

**Load imbalance, disclosed rather than pretended away — and it moved.** Under the original Streamlit design, P5 carried the largest scope, since everything converged there including the UI. Moving the UI to a separate React build and reassigning it to P1 fixes that specific imbalance — P5 is down to four owned directories — but creates a new one: **P1 now carries three tracks** (the critical-path Generator, the Harness, and the entire frontend), more sequential load than anyone else on the team, P5 included under the old plan. This is the direct, accepted cost of the resplit, not an oversight. The one mitigation available: the Harness (E5 steps 4–7) gates nobody downstream, so it's the safest thing to hand off if P1's frontend track is running behind — to the Lead, or to whoever among P3/P4 lands their own stage early.

**A second, smaller new dependency worth naming:** P1's frontend track is now blocked, screen by screen, on P5's routers landing (Part 10) — a dependency that didn't exist when the UI was Streamlit calling Python functions directly in-process. Worth the Lead watching specifically at checkpoints.

---

# Part 3 — Locked Tech Stack

Pinned exactly, not just named. A fresh clone installing this must produce identical behavior on all six machines.

| Layer | Choice | Pin discipline |
|---|---|---|
| Language (backend) | Python 3.11 | Exact minor version on every machine |
| Language (frontend) | TypeScript, Node.js LTS | Exact Node version on every machine |
| Dependency manager (backend) | `uv` (or Poetry) with a committed lockfile | No one installs outside the lockfile |
| Dependency manager (frontend) | npm with a committed `package-lock.json` | Same discipline, other side of the stack |
| API framework | **FastAPI** + Uvicorn, Pydantic v2 | Resolved as primary, not a stretch path — see `context.md` 7.13 for the reasoning and the trade-offs this locks in |
| Frontend framework | **React** + Vite, plain client-side SPA — no Next.js/Remix/SSR | This is an internal review tool, not something needing SEO or server rendering; a plain SPA is the right fit for the requirement, not a lesser choice made under time pressure |
| Frontend routing | `react-router-dom` | — |
| Frontend server-state | `@tanstack/react-query` for anything from the API (caching, refetch-on-mutation); plain `useState`/Context for local UI state only; no Redux — 7 screens doesn't need it | — |
| Frontend charts | `react-plotly.js@^3` + `plotly.js@^3` | v3 is the current maintained line (released 2026-06-09) — it dropped support for `plotly.js` v1/v2 and React <18, so an older pin silently breaks; same library the backend reasoning already justified for statistical charting, not a new choice, just version-verified |
| Generated API client | `openapi-typescript` (schema → types) + `openapi-fetch` (typed fetch wrapper) | This is the pairing `openapi-typescript`'s own documentation recommends, not one option among several — regenerated from the live OpenAPI schema, never hand-written (R9) |
| Data | pandas, NumPy, SciPy | Exact versions in lockfile |
| Module A | scikit-learn (`MinCovDet`, `IsolationForest`), PyOD (`ECOD`) | Exact versions — `MinCovDet`'s guidance (`n_samples > 5·n_features`) and ECOD's `contamination` default are version-sensitive |
| Module B | **LightGBM** (quantile loss), **MAPIE** | Resolved here, not deferred — R1 asks for no ambiguity, and "pick one later" is exactly the ambiguity that rule rules out. LightGBM: native quantile objective (needed for the safety slope), native NaN handling (useful for a missing 96h reading), fast on small-medium CPU-only tabular data. MAPIE: it's the library that directly implements the CQR paper already cited in `context.md` 4.4 (Romano et al. 2019). |
| Explainability | `shap` | `TreeExplainer` only |
| Auth | `PyJWT>=2.13.0` (HS256 tokens), `argon2-cffi` (PIN hashing) | Version floor is load-bearing for PyJWT, not cosmetic: 2.9.0–2.12.1 carry real, fixed CVEs (algorithm-confusion and DoS issues), patched in 2.13.0 — pin the floor, not just the name. Argon2id resolved over `bcrypt`: bcrypt remains acceptable but current OWASP guidance (2026) recommends Argon2id as the default for new code; `bcrypt` was the first draft's pick, corrected here on verification, not left as a stale habit. Secret generated once by the Lead into a git-ignored `.env` (`.env.example` committed, no real secret in git); no token revocation or refresh rotation — disclosed simplification, `context.md` Part 8.1 |
| Storage | SQLite via `sqlalchemy` | No Postgres for this build |
| Report | **`fpdf2`** | Resolved: `weasyprint` depends on system libraries (Pango, Cairo) that can fail to install cleanly on some machines — a real risk with five people on five different setups and no time to debug it mid-build. `fpdf2` is pure Python, zero system dependencies. |
| Backend tests | `pytest`, `pytest-cov`, `httpx` (FastAPI's `TestClient`) | `hypothesis` optional, not required |
| Frontend tests | Vitest, React Testing Library, jsdom | — |
| Linting | `ruff` (backend), ESLint + Prettier (frontend) | — |

**Acceptance gate before any feature code is written:** every person clones, installs from both lockfiles (`uv`/Poetry *and* npm), and runs an empty `pytest` suite *and* an empty `vitest` suite green. This is a session-0 exit criterion (Part 9), not a suggestion.

---

# Part 4 — Repository Structure (Directory Ownership)

```
burnin-screening/
├── requirements.lock / pyproject.toml        [Lead — batches all Python dependency additions]
├── package.json / package-lock.json          [P1 — frontend dependencies, batched through the Lead per R8]
├── contracts.py                              [Lead — Pydantic BaseModels, frozen after session 0, R4]
├── CONTRACT_CHANGES.md                       [Everyone appends; Lead resolves — Part 6]
├── BLOCKERS.md                               [Everyone appends; Lead triages — Part 11]
├── .env.example                              [Lead — JWT_SECRET placeholder; real .env is git-ignored]
├── config/
│   ├── defaults.yaml                         [Lead — the disclosed-default values, Part 5.1]
│   └── harness_thresholds.yaml               [P1 — harness-derived, written in session P1.7, read by P3 in session P3.3 — Part 5.1. The one file-level exception to directory-level ownership: config/ is otherwise Lead's, but this one file is P1's to write, since Lead has no basis to generate harness-derived values]
├── api/                                      [Lead — main.py: app instance, CORS, router registration, StaticFiles mount for the built frontend]
├── generator/                                [P1 — E1]
├── harness/                                  [P1 — E5]
├── ingestion/                                [P2 — E7, plus router.py]
├── features/                                 [P2 — E8]
├── report/                                   [P2 — E9, plus router.py]
├── storage/                                  [P2 — E11, all six tables; exposes a repository API (5.5) and router.py for read-only list routes — nobody else writes SQL here]
├── module_a/                                 [P3 — E2 — no router; consumed by Fusion in-process]
├── module_b/                                 [P4 — E3 — no router; consumed by Fusion in-process]
├── fusion/                                   [P5 — E12, plus router.py and pipeline.py — the orchestrator, 5.7]
├── explain/                                  [P5 — E4 — no router of its own; consumed by fusion/router.py in-process, same person]
├── identity/                                 [P5 — E10, plus router.py — JWT issue/verify lives here]
├── capa/                                     [P5 — E13, plus router.py]
├── frontend/                                 [P1 — E6, the React implementation; tests co-located as frontend/src/**/*.test.tsx per JS convention, not under tests/unit]
├── tests/
│   ├── unit/{generator,ingestion,features,module_a,module_b,fusion,explain,identity,capa}/   [by owner — Python only]
│   └── integration/                          [everyone adds files, nobody edits an existing one — Part 7.4]
├── scripts/                                  [Lead — see below]
│   ├── seed.py                               [written once by the Lead; run locally by every person — SQLite is a local file per machine, not a shared server, so each clone needs its own seeded accounts (Part 10, session L1)]
│   ├── evaluate.py                           [thin CLI wrapper invoking P1's harness/ functions on demand — regenerates PPT numbers, doesn't reimplement E5]
│   ├── demo.py                               [CLI walkthrough: seeds one demo lot via generator/ and prints a console summary — a rehearsal aid distinct from build_demo.sh, which starts the actual servers]
│   ├── dev.sh                                [two-process dev loop — Part 5.6]
│   └── build_demo.sh                         [single-process demo build — Part 5.6]
└── (repo root)                               [context.md, essential-features.md, non-essential-features.md, IMPLEMENTATION_PLAN.md, AGENTS.md live at the root, not in a docs/ folder — every AGENTS.md prompt references them there]
```

`app/` (the old Streamlit screens directory) is retired — no replacement directory carries its name; its content is split between `frontend/` (the screens themselves) and each backend owner's `router.py` (the data those screens need).

---

# Part 5 — Data Contracts

This section is what R1 means concretely. Every shape a stage hands to another stage — and, now, every shape the frontend receives over HTTP — is defined here, once, before anyone writes implementation logic. Disclosed default values are copied from `context.md` Part 8 directly — not re-decided. Written as Pydantic `BaseModel`s so FastAPI derives the OpenAPI schema, and the frontend's TS client, directly from them.

## 5.1 Config object — every disclosed default, made concrete

```python
from pydantic import BaseModel
from typing import Literal

class ScreeningConfig(BaseModel):
    model_config = {"frozen": True}
    fn_fp_cost_ratio: float = 10.0              # context.md 7.12, 8.3 — disclosed judgment call
    pda_threshold: float = 0.05                 # context.md 1.7, 7.7
    confirmed_outcome_fn_ceiling: float = 0.05  # context.md 5.17
    min_confirmed_outcomes_for_ceiling: int = 10 # context.md 5.17
    small_lot_fallback_threshold: int = 30      # context.md 5.16 — exact AEC-Q001 minimum
    signoff_timing_flag_minutes: int = 2        # context.md 5.6
    report_history_cap_runs: int = 10           # context.md 7.10
    lot_size_default: int = 77                  # context.md 3.3
    defect_prevalence_range: tuple[float, float] = (0.01, 0.08)     # context.md 3.3 — disclosed as evidence-thin
    power_law_exponent_range: tuple[float, float] = (0.15, 0.30)    # context.md 1.4
    activation_energy_range_eV: tuple[float, float] = (0.3, 2.0)    # context.md 1.4, 3.3 — corrected range
    schema_version: str = "1.0"
```

**REVIEW/REJECT thresholds are explicitly *not* defaulted here.** They are harness-derived (`context.md` Part 6.2, 7.12) — P1's harness (E5) computes and writes them; every other stage reads them, nobody hand-sets them. **Named location, so this isn't left as a "computes and writes them" with no stated destination:**

```python
class HarnessThresholds(BaseModel):
    model_config = {"frozen": True}
    module_a_review_threshold: float
    module_a_reject_threshold: float
    combination_strategy: Literal["max", "weighted_average", "meta_model"]  # E5 step 6's winner
```

Written by P1's harness to `config/harness_thresholds.yaml` (session P1.7, once the combination-strategy bake-off has a winner — E5 step 6) — a separate file from `config/defaults.yaml` specifically because these are harness-derived, not user-editable via Settings, and shouldn't sit inside a dataclass whose other fields *are* live-editable. `module_a/` (P3) reads this file at runtime in session P3.3 (E2 step 8) — this is the one legitimate case of one person's directory reading a file another person's session produces outside the contracts/API surface, because it's a static config artifact, not a live cross-directory function call.

## 5.2 Ingestion → Features (P1/P2 → P2, P3, P4)

```python
class Reading(BaseModel):
    component_id: str; lot_id: str; part_number: str
    manufacturer: str; date_code: str
    parameter: str           # str, not Literal: an unrecognized parameter is a VALID Reading (context.md 5.9)
    checkpoint_hour: float   # explicit numeric, not an assumed 0/24/96/168 — context.md 5.9
    value: float; unit: str

class LotDataset(BaseModel):
    lot_id: str; part_number: str; status: Literal["IN_PROGRESS", "COMPLETE"]
    readings: list[Reading]
    account_id: str          # ingestion attribution — context.md 7.3

class FeatureFrame(BaseModel):
    # One frame per (component, parameter) pair — value_* are scalars, so the frame is already parameter-scoped.
    component_id: str; lot_id: str
    part_number: str; parameter: str    # part_number lets Module B pick its per-part-number model; parameter says which one this frame is about
    value_0h: float; value_24h: float; value_96h: float | None
    delta_24h: float; delta_96h: float | None
    lot_median_0h: float; lot_median_24h: float
    robust_z: dict[str, float]          # keyed per checkpoint label ("0h", "24h", "96h") — parameter is the frame's own field
    lot_size: int; used_pooled_fallback: bool   # < 30 parts — context.md 5.16
    elapsed_hours: dict[str, float]     # actual elapsed hours keyed by checkpoint label ("0h", "24h", "96h") — a bare list couldn't say which entry was which
```

**Unrecognized-parameter handling (`context.md` 5.9):** a `parameter` value outside `{iddq, leakage, prop_delay}` is a valid `Reading` — Module A must accept it; `FeatureFrame` fields feeding Module B are `None` for that parameter, which Module B's contract (5.3) must treat as "forecast unavailable," never as zero or a silent drop.

## 5.3 Features → Module A / Module B (P2 → P3, P4)

```python
class ModuleAResult(BaseModel):
    component_id: str; parameter: str
    robust_z: float; mcd_distance: float | None   # None if lot < 30 (5-feature MCD ceiling — context.md 4.2)
    isolation_forest_score: float | None            # None on a part number's first-ever lot (cold start)
    ecod_score: float
    explainable_tags: dict[str, bool]   # {"robust_z": True, "mcd": True, "isolation_forest": False, "ecod": True}
    direction: Literal["above_median", "below_median"]   # feeds the direction-awareness cap — context.md 4.2
    severity_tier: Literal["PASS", "REVIEW", "REJECT"]
    severity_cap_reason: str | None     # populated if capped — context.md 5.16, 6.2

class ModuleBResult(BaseModel):
    component_id: str; parameter: str
    predicted_168h: float | None        # None if parameter outside trained three
    interval_lower: float | None; interval_upper: float | None
    physics_baseline_prediction: float | None
    physics_disagreement_gap: float | None
    drift_rate: float | None; exceeds_safety_slope: bool | None
    forecast_unavailable: bool          # explicit flag — context.md 5.9
```

## 5.4 Module results → Fusion (P3, P4 → P5)

```python
class RiskAssessment(BaseModel):
    component_id: str; lot_id: str
    verdict: Literal["PASS", "WATCH", "REJECT"]
    module_a_rank: float; module_b_rank: float   # two separate rankings, never fused — context.md 6.3
    worst_parameter: str

class LotDisposition(BaseModel):
    lot_id: str; status: Literal["IN_PROGRESS", "COMPLETE"]
    pda_result: float
    verdict: Literal["LOT_ON_TRACK", "LOT_AT_RISK", "STOP_RUN_RECOMMENDED",
                      "ACCEPT", "HOLD", "REJECT"]   # forecast wording vs. final wording — context.md 5.18, never conflated
    is_forecast: bool
```

## 5.5 Database schema — six tables, fully typed, all append-only (transcribed from `context.md` 5.10, unchanged by the stack switch)

**P2 owns proposing changes to the schema (through `CONTRACT_CHANGES.md`, Part 6) and 100% of the functions that read and write these tables — not a separate file holding the class definitions.** The table classes below live in `contracts.py`, the one shared, Lead-maintained file everyone reads from; a table is a frozen shape, same as any Pydantic model. P2 exposes a small repository API, and every other stage calls it from its own directory; nobody but P2 ever writes SQL against these tables. Signatures (auto-generated fields — `created_at`, `timestamp`, `recorded_at`, `event_id` — are set inside each function, never passed in):

```python
def save_account(account_id: str, display_name: str, role: str, pin_hash: str) -> Account: ...
def save_project(project_id: str, lot_id: str, part_number: str, created_by: str) -> Project: ...
def save_disposition_signoff(project_id: str, component_id: str, analysis_run_id: str,
                             account_id: str, verdict: str, rationale: str) -> DispositionSignoff: ...
def save_confirmed_outcome(project_id: str, component_id: str, analysis_run_id: str, account_id: str,
                           confirmed_outcome: str, note: str | None = None) -> ConfirmedOutcome: ...
def log_event(project_id: str, account_id: str, event_type: str, payload: dict) -> Event: ...
```

Each has a `query_*` counterpart. `save_project` and `save_analysis_run` are named explicitly because an earlier pass of this document defined the `projects` and `project_data` tables below without ever naming the function that writes to them — a real gap, since without it nothing explains how a row gets into either table. `save_analysis_run(project_id, raw_data, results: AnalysisResults) -> ProjectData` is where the diff-against-prior-run computation actually happens (E11 step 4) — it reads the immediately prior row for the same `project_id`, computes the three-part diff (module activated for the first time, a prediction resolved into an actual, a verdict moved), and writes both the new row and its diff in one call. (`AnalysisResults` is defined in 5.6, not here — it's referenced ahead of its definition because it belongs naturally with the REST response models it's shared by; nothing about that ordering changes what it means.)

```python
from datetime import datetime
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Account(Base):
    __tablename__ = "accounts"
    account_id: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    role: Mapped[str]
    pin_hash: Mapped[str]     # argon2-cffi hash, never the raw PIN

class Project(Base):
    __tablename__ = "projects"
    project_id: Mapped[str] = mapped_column(primary_key=True)
    lot_id: Mapped[str] = mapped_column(index=True)
    part_number: Mapped[str]
    created_at: Mapped[datetime]
    created_by: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))

class ProjectData(Base):
    __tablename__ = "project_data"
    analysis_run_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    raw_data: Mapped[str]              # JSON-serialized
    results_json: Mapped[str]          # JSON-serialized AnalysisResults (5.6) — identical shape to E9's JSON export
    diff_vs_prior: Mapped[str | None]  # JSON-serialized; null only for a project's first-ever run
    created_at: Mapped[datetime]

class Event(Base):
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    event_type: Mapped[str]            # constrained to the Literal in EventResponse (5.6) at the API layer
    timestamp: Mapped[datetime]
    payload: Mapped[str]               # JSON-serialized

class DispositionSignoff(Base):
    __tablename__ = "disposition_signoffs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    component_id: Mapped[str] = mapped_column(index=True)   # renamed from an earlier part_id — see the naming note below
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("project_data.analysis_run_id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    verdict: Mapped[str]               # constrained to Literal["ACCEPT","HOLD","REJECT"] at the API layer
    rationale: Mapped[str]
    timestamp: Mapped[datetime]

class ConfirmedOutcome(Base):
    __tablename__ = "confirmed_outcomes"
    confirmed_outcome_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    component_id: Mapped[str] = mapped_column(index=True)   # renamed from an earlier part_id — see the naming note below
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("project_data.analysis_run_id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    confirmed_outcome: Mapped[str]     # constrained to the Literal in ConfirmedOutcomeRequest (5.6)
    note: Mapped[str | None]
    recorded_at: Mapped[datetime]
```

**Naming consistency, fixed here:** every contract in 5.2–5.4 identifies a single physical part as `component_id`. An earlier pass of this table named the same concept `part_id` on these last two tables only — the kind of shape ambiguity R1 exists to rule out, however small. Both tables and their response models (5.6) now say `component_id`, with no other name for the same concept anywhere in the system.

No `UPDATE` anywhere — the repository API exposes only inserts and queries; `disposition_signoffs` and `confirmed_outcomes` deliberately have no natural key that would tempt one, by design (5.17/5.15). The JWT layer adds no new table — a token is stateless, nothing about a session is stored server-side (5.6's disclosed trade-off).

## 5.6 REST API — every endpoint, request and response fully typed

FastAPI derives the OpenAPI schema from these Pydantic models plus the routes below; `frontend/`'s TS client is generated from that schema — never hand-written (R9). Every model below is additional to 5.1–5.4, not a replacement for them — several reuse `ModuleAResult`, `ModuleBResult`, `RiskAssessment`, `LotDisposition` directly as response fields.

```python
from datetime import datetime

class AnalysisResults(BaseModel):
    """The output of one full pipeline run — see Part 5.7. Reused verbatim by
    LotSummaryResponse (a live lot) and ProjectDataResponse (a stored historical run),
    because they are the same shape by design: a reload is not a different kind of data."""
    assessments: list[RiskAssessment]; disposition: LotDisposition

class LoginRequest(BaseModel):
    account_id: str; pin: str

class TokenResponse(BaseModel):
    access_token: str; token_type: Literal["bearer"] = "bearer"
    account_id: str; role: str

class LotUploadResponse(BaseModel):
    lot_id: str; part_number: str
    status: Literal["IN_PROGRESS", "COMPLETE"]; reading_count: int

class LotSummaryResponse(AnalysisResults):
    pass

class DispositionRecord(BaseModel):
    project_id: str; component_id: str   # both required to link to /parts/{component_id} and its project context — missing in an earlier pass
    account_id: str; verdict: Literal["ACCEPT", "HOLD", "REJECT"]
    rationale: str; timestamp: datetime; analysis_run_id: str

class ConfirmedOutcomeRecord(BaseModel):
    project_id: str; component_id: str   # same fix as DispositionRecord, same reason
    account_id: str
    confirmed_outcome: Literal["Confirmed Good", "Confirmed Defective", "Unknown"]
    note: str | None; recorded_at: datetime; analysis_run_id: str

class PartDetailResponse(BaseModel):
    module_a: ModuleAResult; module_b: ModuleBResult
    explanation_sentence: str; confidence_qualifier: str   # E4 steps 5-6
    severity_cap_note: str | None        # E4 step 8 — populated for either capping reason, worded per which applied
    unavailable_forecast_note: str | None  # E4 step 9
    staleness_note: str | None            # E4 step 10
    disposition_history: list[DispositionRecord]
    confirmed_outcomes: list[ConfirmedOutcomeRecord]

class DispositionRequest(BaseModel):
    verdict: Literal["ACCEPT", "HOLD", "REJECT"]; rationale: str

class ConfirmedOutcomeRequest(BaseModel):
    confirmed_outcome: Literal["Confirmed Good", "Confirmed Defective", "Unknown"]
    note: str | None = None

class ProjectSummary(BaseModel):
    project_id: str; lot_id: str; part_number: str
    created_at: datetime; created_by: str

class ProjectDataResponse(BaseModel):
    analysis_run_id: str; project_id: str
    results: AnalysisResults   # was a bare dict in an earlier pass — the one endpoint that most needed a typed shape, since it feeds screens 3-4 on reload, ended up the least typed; fixed here
    diff_vs_prior: dict | None   # kept as dict deliberately — see the note below the table

class EventResponse(BaseModel):
    event_id: str; project_id: str; account_id: str
    event_type: Literal["ingest", "checkpoint_add", "analysis_run", "config_change"]
    timestamp: datetime; payload: dict   # kept as dict deliberately — see the note below the table

class PendingSettingChange(BaseModel):
    field: Literal["fn_fp_cost_ratio", "pda_threshold", "confirmed_outcome_fn_ceiling"]
    proposed_value: float; proposed_by: str; signed_off_by: str | None

class SettingsResponse(BaseModel):
    fn_fp_cost_ratio: float; pda_threshold: float; confirmed_outcome_fn_ceiling: float
    pending_changes: list[PendingSettingChange]

class SettingsProposalRequest(BaseModel):
    field: Literal["fn_fp_cost_ratio", "pda_threshold", "confirmed_outcome_fn_ceiling"]
    proposed_value: float

class SettingsSignoffRequest(BaseModel):
    field: Literal["fn_fp_cost_ratio", "pda_threshold", "confirmed_outcome_fn_ceiling"]

class WorklistResponse(BaseModel):
    pending: list[DispositionRecord]   # dispositions with no matching confirmed_outcome yet

class CorrectiveStatusResponse(BaseModel):
    fn_rate: float; fp_rate: float; confirmed_outcome_count: int
    status: Literal["OK", "CEILING_EXCEEDED", "INSUFFICIENT_DATA"]   # INSUFFICIENT_DATA below min_confirmed_outcomes_for_ceiling

class DPARecommendation(BaseModel):
    component_id: str; reason: str

class DPAWorkOrderResponse(BaseModel):
    recommendations: list[DPARecommendation]   # up to 3, per E13 step 5
```

`diff_vs_prior` and `payload` are the two deliberate exceptions to "everything is a named model, not a dict" — both are genuinely heterogeneous (a diff's fields depend on what changed; an event's payload depends on `event_type`), and a discriminated union for four event types or an open-ended diff shape would add real complexity for no gain a hackathon-scale frontend would notice. Everywhere else, a `dict` would have been the ambiguity R1 rules out — this is why the two are called out explicitly rather than left to look like an oversight.

| Method + Path | Request | Response | Auth | Router file (owner) |
|---|---|---|---|---|
| `POST /auth/login` | `LoginRequest` | `TokenResponse` | none | `identity/router.py` (P5) |
| `POST /lots` | multipart file + metadata | `LotUploadResponse` | required | `ingestion/router.py` (P2) |
| `POST /lots/{lot_id}/checkpoints` | multipart file | `LotUploadResponse` | required | `ingestion/router.py` (P2) |
| `POST /lots/demo` | — | `LotUploadResponse` | required | `ingestion/router.py` (P2) |
| `GET /lots/{lot_id}` | — | `LotSummaryResponse` | required | `fusion/router.py` (P5) |
| `GET /parts/{component_id}` | — | `PartDetailResponse` | required | `fusion/router.py` (P5 — aggregates `explain/`, `identity/`, `capa/`, all P5's own directories) |
| `POST /parts/{component_id}/disposition` | `DispositionRequest` | `DispositionRecord` | required | `identity/router.py` (P5) |
| `POST /parts/{component_id}/confirmed-outcome` | `ConfirmedOutcomeRequest` | `ConfirmedOutcomeRecord` | required | `capa/router.py` (P5) |
| `GET /projects` | — | `list[ProjectSummary]` | required | `storage/router.py` (P2) |
| `GET /projects/{project_id}` | — | `ProjectDataResponse` | required | `storage/router.py` (P2) |
| `GET /events` | — | `list[EventResponse]` | required | `storage/router.py` (P2) |
| `GET /disposition-signoffs` | — | `list[DispositionRecord]` | required | `storage/router.py` (P2) |
| `GET /settings` | — | `SettingsResponse` | required | `identity/router.py` (P5) |
| `POST /settings/propose` | `SettingsProposalRequest` | `PendingSettingChange` | required | `identity/router.py` (P5) |
| `POST /settings/signoff` | `SettingsSignoffRequest` | `SettingsResponse` | required | `identity/router.py` (P5) |
| `GET /settings/worklist` | — | `WorklistResponse` | required | `capa/router.py` (P5) |
| `GET /settings/corrective-status` | — | `CorrectiveStatusResponse` | required | `capa/router.py` (P5) |
| `POST /lots/{lot_id}/report` | — | binary (PDF) + `Content-Disposition` header; CSV/JSON via `Accept` negotiation | required | `report/router.py` (P2) |
| `POST /lots/{lot_id}/dpa-work-order` | — | `DPAWorkOrderResponse` | required | `capa/router.py` (P5) |

Every 4xx from a failed request/response validation is FastAPI's own automatic behavior, not code anyone writes — this is the "free layer" Part 7.3 already names. No pagination on list endpoints — acceptable at hackathon data volumes, a disclosed simplification, not an oversight.

**Auth mechanism.** `identity/` issues a `PyJWT>=2.13.0`-signed token (HS256; secret generated once into a git-ignored `.env`) containing `account_id`, `role`, and a short expiry. A FastAPI dependency, `get_current_account`, decodes and verifies it on every protected route above. The frontend holds the token in memory only — React Context, never `localStorage`/`sessionStorage`/a cookie (AGENTS.md rule 13); logging out discards the in-memory value, and a hard refresh re-prompts login. PIN hashing uses `argon2-cffi` (Argon2id), not `bcrypt` — see Part 3's note on why this was corrected on verification. **Disclosed trade-off:** no token revocation, no refresh-token rotation — a production system would need both; this one doesn't, given the pre-existing two-account, no-real-security scope already drawn for E10 (`context.md` Part 8.1).

**CORS and the demo-day shortcut.** `api/main.py` allows the Vite dev origin (`http://localhost:5173`) during active development, when `uvicorn --reload` and `vite dev` run as two processes (`scripts/dev.sh`). For the actual rehearsal and submission, the frontend is built (`npm run build`) and served as static files directly from FastAPI (`StaticFiles` mount) — **one process, not two** — specifically to remove the CORS/two-terminal failure mode at the exact moment it would be most visible (`scripts/build_demo.sh`).

## 5.7 Pipeline orchestration — who actually calls Features → Module A → Module B → Fusion, and when

**A gap found on this verification pass, not present in the original design either: nothing before this section ever said who owns wiring the stages together at runtime.** Every contract in 5.2–5.4 defines what one stage hands the next, and every session in Part 10 builds one stage in isolation — but a new lot arriving has to actually move through all of them in sequence, and no directory, function, or session was ever assigned that job. Fixed here, not left for whoever hits it first to invent on the spot.

```python
# fusion/pipeline.py — owned by P5, the natural point since Fusion already
# consumes every upstream stage's output and produces what gets stored.
def run_full_pipeline(lot: LotDataset, config: ScreeningConfig) -> AnalysisResults:
    """Imports and calls features.compute() (P2), module_a.detect() (P3), and
    module_b.predict() (P4) as library functions, in that order, then applies
    E12's fusion logic and E4's explanation generation. Returns the same
    AnalysisResults shape whether the lot is In-Progress or Complete —
    LotDisposition.is_forecast (5.4) carries that distinction, not a different
    return type."""
```

**This is a sanctioned cross-directory import, the same pattern already established for P2's storage repository API and identity's `get_current_account` — calling another owner's exposed function is not an R3 violation; editing the file it lives in is.** `ingestion/router.py` (P2) calls `run_full_pipeline` after every successful `POST /lots` or `POST /lots/{lot_id}/checkpoints`, then persists the result via `storage`'s `save_analysis_run(...)` (5.5) and logs an `analysis_run` event via `log_event(...)`. `fusion/router.py`'s `GET /lots/{lot_id}` and `storage/router.py`'s `GET /projects/{project_id}` are both reads of the already-computed, already-stored result — neither re-runs the pipeline live; this is what makes the staleness note (E4 step 10) meaningful, since it compares two *stored* snapshots, not a stored one against a freshly recomputed one.

**What this changes in Part 10, stated explicitly rather than left implicit:** P5's session P5.1 stub must include a callable stub of `run_full_pipeline` (returning fixed `AnalysisResults`, not just stub data objects) — P2's router needs something to call from day one, per R6. P2's sessions P2.3 and P2.5 call this function (stub or real, whichever exists at the time) rather than assembling a pipeline themselves — P2 never needs to know Module A/B's internals, only that this one function exists. As P3, P4, and P5's own fusion/explainability logic go from stub to real (sessions P3.3, P4.3, P5.2–P5.3, P5.7), `run_full_pipeline`'s behavior upgrades automatically, since P2's code never changes — it's still calling the same function.

---

# Part 6 — Contract-Change Process

**An agent that finds a contract gap never guesses and never edits `contracts.py` directly.**

1. Append an entry to `CONTRACT_CHANGES.md` (append-only): what's missing, why, a proposed fix.
2. Keep working against a locally-defined, clearly-prefixed temporary stub (`TEMP_<field_name>`) — never blocked waiting for a resolution. On the frontend, this means a typed local mock matching the shape you expect, not an untyped workaround (AGENTS.md rule 14).
3. **The Lead reviews `CONTRACT_CHANGES.md` at fixed checkpoints — not continuously.** **Concretely, not left as an undefined phrase** (a gap found checking Lead's own instructions for actionability): the start of every session Lead runs, whether L2 itself or before starting L3/L4/L5, **plus at least twice a day regardless** — so a gap logged mid-afternoon doesn't sit unresolved just because Lead's own next task happens to be PS2 or the PPT rather than another L-session. This is what makes the process compatible with the Lead also running PS2 and the PPT.
4. The Lead updates `contracts.py` and/or the affected route in one commit per review pass.
5. **The Lead regenerates the OpenAPI schema and the frontend's TS client in the same pass** (`npm run generate-client`) — this is the one new step the stack switch adds to this process. The requesting person swaps their `TEMP_` stub or local mock for the real field/type — a mechanical rename, not a rewrite.

---

# Part 7 — Testing Strategy

## 7.1 The rule

Tests are written before or alongside implementation. A stage is not "done" because code exists — it's done when every item on its checklist (7.3) passes.

## 7.2 The golden test — non-negotiable, named once, referenced everywhere

`context.md` 7.12 / `essential-features.md` E5: a lot with median leakage 10 µA and a part at 45 µA against a 50 µA limit **must** be flagged. This is the problem statement's own worked example. It is P1's responsibility (harness, E5) but every stage that touches Module A must not break it — it runs in the integration suite (7.4), not just P1's own tests.

## 7.3 Per-stage edge-case checklist

Pulled from cases already named across `context.md` — "comprehensive" means every row below has a passing check, not a feeling.

| Stage | Must-test edge cases |
|---|---|
| Generator (P1) | Determinism (same seed → identical output); all 5 held-out families present; ground-truth sidecar never leaks into the production schema |
| Ingestion (P2) | Missing 0h/24h → `INSUFFICIENT_DATA` equivalent; missing 96h → allowed, flagged; wide vs. long format equivalence; duplicate component IDs; unit mismatch; irregular checkpoint hours |
| Features (P2) | Zero-MAD lot (all-identical values); lot size < 30 triggers pooled fallback; lot size = 1 |
| Module A (P3) | The golden test (7.2); MCD degenerate fit at exactly the 30-part boundary; Isolation Forest cold start (part number's first-ever lot); ECOD contamination default behavior; below-median deviation capped correctly (direction-awareness) |
| Module B (P4) | Parameter outside trained three → `forecast_unavailable=True`, never a guess; physics baseline vs. live model disagreement computed correctly; CQR interval ordering (`lower ≤ point ≤ upper`) |
| Fusion (P5) | Explainability-gate cap fires only on Isolation-Forest-only signals; "both modules cross REVIEW" still fires REJECT even when Module A was capped; early-reject counts toward PDA; forecast vs. final PDA wording never conflated |
| Explainability (P5) | Every flagged component has all four mechanisms represented (z-score, MCD, ECOD, or SHAP as applicable); severity-cap note fires for both reasons (gate and direction) |
| Identity/CAPA (P5) | Dual sign-off requires two *distinct* account IDs, not two role labels; confirmed-outcome FN/FP computed separately, never blended; corrective status doesn't fire below the minimum confirmed-outcome count; JWT round-trip (valid token verifies; expired or tampered token rejected with 401) |
| **Frontend (P1)** | All 7 screens render with no console errors and match `essential-features.md` E6's inventory 1:1 (screenshot-verified, not eyeballed); generated client has zero hand-written `any`-typed calls; login round-trips a real JWT and a hard refresh correctly re-prompts login (rule 13's trade-off working as intended, not as a bug); every screen's loading/error state is handled, not just its happy path |

**A free layer, worth naming explicitly:** every backend route validates its request/response against the Pydantic contract automatically — FastAPI returns a 422 on a shape mismatch rather than silently accepting or coercing bad data. This doesn't replace the checklist above, but it does catch a class of contract-drift bug the Streamlit version had no equivalent guard against.

## 7.4 Integration tests — a distinct layer, with its own rule

`tests/integration/` is shared. **Rule: add new files, never edit an existing one.** The Lead owns merging these; anyone can add one.

## 7.5 Definition of "comprehensive," stated once

A stage passes when: (a) every row in its 7.3 checklist has a test or, for the Frontend row, a screenshot-verification pass, (b) the golden test still passes if the stage touches Module A, (c) `pytest` is green including coverage on the stage's own directory — or `vitest` is green for the frontend track, (d) one reviewer who is not the author has approved the PR.

---

# Part 8 — Git & Merge Strategy

**Branch model, every track named explicitly — no "etc." left to interpretation, since an earlier pass left exactly that gap:**

| Track | Branch | Notes |
|---|---|---|
| Lead — contracts + API skeleton (L1, L2) | commits directly to `develop` | **The one sanctioned exception to branch+PR discipline**, and stated as such rather than left silent: L1's same-session sign-off from all five, and L2's `CONTRACT_CHANGES.md` checkpoint review (Part 6), *are* the review R7 requires — structured differently (reviewed by all five, continuously) rather than skipped |
| Lead — scripts, tooling (L3, L5) | `lead-tooling` | Normal branch + one review, same as everyone else — no special reason for `scripts/` to skip discipline the way contracts justifiably does |
| P1 — Generator + Harness (P1.1–P1.8) | `p1-generator` | One branch for both — they merge as one unit (see the diagram below), matching R6's stub-then-build shape for a single track |
| P1 — Frontend (P1.9–P1.12) | `p1-frontend` | Started fresh once the API skeleton and at least one real backend route exist, merges last — **should not share a branch with `p1-generator`**, different prerequisites, different review context |
| P2 — Ingestion, Features, Report, Storage (P2.1–P2.8) | `p2-ingestion` | One branch for the whole stage |
| P3 — Module A (P3.0–P3.3) | `p3-module-a` | — |
| P4 — Module B (P4.0–P4.3) | `p4-module-b` | — |
| P5 — Fusion, Explainability, Identity, CAPA (P5.1–P5.9) | `p5-fusion` | One branch for the whole stage |

All off a shared `develop`, created from `main` as Lead's literal first action in `L1` (Part 10) — `main` otherwise stays untouched until it's merged into exactly once, in `L5`, once `L4`'s final integration checkpoint confirms `G7`: this is what turns `main` into "the thing actually submitted and demoed," verified working, rather than a branch that drifts in and out of sync with no clear meaning. Previously left as the unresolved phrase "at phase gates" — that's fixed here, not still open.

**Merge order, following the dependency chain in Part 9, not an arbitrary choice — and rolling, not a single batch at the end:**

```
Lead (contracts + api/ skeleton)
  → P1 — Generator + Harness
    → P2 — Ingestion + Features + Storage schema + routers
      → P3 and P4, either order — both required, genuinely parallel, no shared files
        → P5 — Fusion, Explainability, Identity, CAPA, routers
          → P1 — Frontend (merges last, against every route above)
```

**This diagram shows dependency order, not "wait until the very end" — a contradiction an earlier pass left standing, worth naming plainly rather than quietly correcting.** The diagram is correct; `L4`'s old description ("merge in Part 8's fixed order," gated on `G6`, the *last* gate) implied all merging happens in one batch after literally everything including the frontend is done. It can't: `P3.3` reads `config/harness_thresholds.yaml`, written by P1 in `P1.7` — for P3's own branch to see that file, P1's branch must already be in `develop` by then, and `P3.3` happens long before `G6`. The same is true wherever a session's stated prerequisite is a session on someone *else's* branch: `P2.3` needs P1.4's real `LotDataset`, `P3.1`/`P4.1` need P2.4's real `FeatureFrame`, and so on — Part 10's own prerequisite chain already says exactly when each of these has to be true.

**The actual rule**: a branch's ready commits get merged into `develop` as soon as *any* downstream session's stated prerequisite needs them — checked against Part 10, not against the coarser gate table. This means a track can merge more than once as it accumulates work (P1's `p1-generator` branch merges once after `P1.4`, so P2 can build against real `LotDataset`, and again after `P1.8`, so P3.3 can read the harness thresholds) — a branch merging in stages as it produces things others need, not one atomic event. This rolling merge work is what `L2` ("ongoing integration") actually spends most of its time on, not a separate activity — see `L2`'s description in Part 10. `L4` is the *final* integration checkpoint once everything, including the frontend, is in — not the first time anything gets merged.

Daily rebase regardless of position in the order; conflicts caught daily are minutes, caught weekly are hours — this instruction only makes sense under rolling merges, which is what it was always describing.

**PR checklist, self-certified:**

- [ ] Matches the feature spec in `essential-features.md` / `non-essential-features.md` — same approach, same cited evidence
- [ ] Does not reintroduce anything explicitly ruled out (`non-essential-features.md`'s "Explicitly excluded" list — KDE, TSFMs, LLM-in-the-loop explanations, DL-from-scratch)
- [ ] Every field consumed/produced matches `contracts.py` exactly, or a `CONTRACT_CHANGES.md` entry exists for the gap — on the frontend, every API call goes through the generated client, never a hand-written `fetch`
- [ ] 7.3's checklist for this stage is fully covered
- [ ] No edits outside this person's owned directory

---

# Part 9 — Phase Gates

Replaces a day-by-day calendar with explicit readiness gates — a team may close several sessions in one sitting or spread one across several; what matters is which prerequisite is actually met, not which day it is.

| Gate | Opens when | Closes when (exit criteria) |
|---|---|---|
| **G0 — Contracts frozen** | Team assembled | Lead's `contracts.py` + `api/main.py` skeleton signed off by all five; both lockfiles install clean; empty `pytest` *and* empty `vitest` green on all six machines |
| **G1 — Stubs up** | G0 | Every track (including the frontend's first placeholder screens) has written its first-session stub against the frozen contract — every downstream person can start building immediately. Each person has also run `scripts/seed.py` locally (L1) so they can actually log in against their own SQLite file, not just compile against the contract. |
| **G2 — Generator real** | G1 | P1's Generator passes its full 7.3 row; real `LotDataset` available to P2 |
| **G3 — Ingestion + Features real** | G2 | P2's Ingestion and Features pass their 7.3 rows; real `FeatureFrame` available to P3/P4; P2's storage repository API is callable |
| **G4 — Modules real** | G3 | Module A and Module B each independently pass their full 7.3 row, including the golden test for Module A |
| **G5 — Backend routes real** | G4, plus P2's repository API from G3 | Fusion, Explainability, Identity (incl. JWT), and CAPA all pass their 7.3 rows; every route in Part 5.6 returns real data, not a stub |
| **G6 — Frontend real** | G5 for whichever route each screen depends on (screens can close incrementally, not all-at-once) | All 7 screens pass the Frontend row of 7.3; full login-to-report flow works against real data |
| **G7 — Integration** | G6 | Lead has merged in Part 8's order, full integration suite green, golden test passes, every 7.3 row passes in combination, `CONTRACT_CHANGES.md` backlog resolved |
| **G8 — Demo-ready** | G7 | `scripts/build_demo.sh` produces a single working process; full run-through rehearsed at least twice; every claim in the PPT traces to a number the harness (E5) actually produced |

The Harness (E5 steps 4–7) and most of the frontend's later screens (G6) have no strict ordering against each other beyond their own listed prerequisites — see Part 10 for exactly which.

---

# Part 10 — Per-Person Work Packets, by Session

Each section below is written to be read on its own — with `AGENTS.md` and `context.md` open alongside it, a developer should not need anything else to start. Every session names its prerequisite explicitly; a session with no prerequisite listed can start as soon as its gate (Part 9) is open.

## Lead — Contracts, Integration, Demo/PPT

**Owns:** `contracts.py`, `api/`, `CONTRACT_CHANGES.md`, `BLOCKERS.md`, the merge into `main`, `scripts/`, the demo script, the PPT.

- **Session L1 — Contracts + API skeleton** *(prereq: none — gates G0)*: **Bootstrap, before anything else — never stated anywhere until this pass**: at true session zero, only `main` exists (whatever a fresh repo starts with). Lead's actual first git action is on `main`: create `develop` from it (`git checkout -b develop`, `git push -u origin develop`) — this is the one time Lead is genuinely "on `main`," and it lasts about as long as that one command. Every real L1 task below happens on `develop`, matching Part 8's sanctioned exception; `main` stays untouched until L5 (see Part 8's note on when `main` actually gets merged into, previously left as the unresolved phrase "at phase gates"). Then: draft `contracts.py` as Pydantic `BaseModel`s (transcription from Part 5, not new design). Draft `api/main.py`: empty `FastAPI()` instance, CORS for the Vite dev origin, a `/health` route. **Also scaffold a minimal `frontend/`** — just `npm create vite -- --template react-ts` with zero real components and one trivial passing Vitest test, nothing built out yet: a gap found checking this exit criterion against reality, not a prior audit pass — without this, `package.json`/`package-lock.json` wouldn't exist until P1.9, and G0's own exit criterion below would be impossible to satisfy that early. P1.9 later builds this out; it doesn't create it from nothing. Circulate for same-session sign-off from all five. Confirm both lockfiles install clean and both test suites (empty `pytest`, and Vitest with its one trivial test) run green everywhere. **Also write `scripts/seed.py`** (can be drafted now, but only runs successfully once P2.1's `accounts` table and `save_account` function exist): inserts the two named accounts (E10) with `argon2-cffi`-hashed PINs. Because SQLite is a local file, not a shared server, **every person runs this locally** as part of their own session-0 setup, not just the Lead once — add "run `scripts/seed.py` clean" to the exit criteria everyone checks before their first real session, alongside the two test-suite checks.
- **Session L2 — Ongoing integration** *(prereq: L1; runs continuously once opened)*: **merge each branch's ready commits into `develop` as soon as any downstream session's Part 10 prerequisite needs them — this is most of what "ongoing integration" actually is, not a separate activity from it** (Part 8's corrected merge-order section has the full reasoning and the concrete example of why this can't wait for a single batch merge). Alongside that: review `CONTRACT_CHANGES.md`/`BLOCKERS.md` at fixed checkpoints (Part 6's concrete cadence — start of every Lead session, plus twice daily minimum); batch `contracts.py` updates and regenerate the OpenAPI schema/TS client in the same pass (Part 6); register each router into `api/main.py` as it lands; spot-check PRs against the Part 8 checklist.
- **Session L3 — Dev tooling** *(prereq: at least one real router exists)*: `scripts/dev.sh` (two-process dev loop) and `scripts/build_demo.sh` (single-process demo build, Part 5.6's CORS shortcut). **Also `scripts/evaluate.py`** — a thin CLI wrapper invoking P1's `harness/` functions on demand (never reimplementing E5's logic), used to regenerate the PPT's comparison numbers whenever the underlying models change.
- **Session L4 — Final integration checkpoint** *(prereq: G6 open)*: **not the first time anything merges — by this point, every branch's ready work has already been rolling-merged throughout L2.** This session confirms nothing was missed (every branch's `HEAD` is actually in `develop`, not just its earlier commits), runs the full integration suite end to end one more time against the complete, assembled system, and resolves whatever's left in the `CONTRACT_CHANGES.md` backlog.
- **Session L5 — Demo rehearsal + PPT** *(prereq: L4 — G7)*: **Merge `develop` into `main` here — the one time this happens (Part 8)** — this is what makes `main` mean "verified, ready to submit," not a branch that's merged into casually or repeatedly. `scripts/demo.py` — a CLI walkthrough seeding one demo lot via `generator/` and printing a console summary, a rehearsal aid distinct from `build_demo.sh` (which starts the actual servers) — useful for checking the pipeline end to end without the UI in the loop. At least two full run-throughs via `build_demo.sh`, run **from `main`**, not `develop`, so the rehearsal actually tests what will be submitted; PPT drawing directly from `context.md`'s evidence trail and `essential-features.md`'s differentiation reasoning.

## P1 — Generator, Harness, Frontend

**Owns:** `generator/`, `harness/`, `frontend/`. **Features:** E1, E5, E6 (implementation).

*Generator track:*
- **Session P1.1** *(prereq: G0)*: **First: confirm your own clean install (Part 3's acceptance gate — both lockfiles, `pytest` and Vitest both green) and that you actually reviewed and signed off on `contracts.py` during L1 — specifically `LotDataset` (what you produce) and `ScreeningConfig` (what you read). If either didn't happen yet, do it now, before writing any generator code — this was previously only stated in Lead's L1 description and Part 9's G0 gate, not here where P1 would actually see it.** Then: E1 steps 1–3 (lot/die baselines, defect assignment) + determinism test.
- **Session P1.2** *(prereq: P1.1)*: E1 steps 4–6 (power-law healthy drift, Arrhenius defect trajectories, severity correlation) + healthy-vs-defective divergence test.
- **Session P1.3** *(prereq: P1.2)*: E1 steps 7–9 (offset correction, noise, elapsed-time field, 5 held-out families) + all-families-present test.
- **Session P1.4** *(prereq: P1.3 — closes G2)*: E1 step 10 (KS realism test vs. `context.md` 1.4/3.3). Generator's 7.3 row fully green. Real `LotDataset` handed to P2.

*Harness track:*
- **Session P1.5** *(prereq: P1.4 — own data only, no cross-person dependency)*: E5 steps 1–2 (three named baselines, held-out sets with per-archetype minimums).
- **Session P1.6** *(prereq: P1.5)*: E5 step 3 (golden test scaffolded — even failing against current stubs, it must exist as a shape early).
- **Session P1.7** *(prereq: P3.2, P4.3)*: E5 steps 4–6 (scoring, combination-strategy bake-off) — **deliberately depends on P3.2, not P3.3**: a circular dependency existed here on an earlier pass (P1.7 needed P3.3, but P3.3 needs P1.7's derived thresholds per 5.1) — broken by recognizing the bake-off only needs Module A's *scoring* (steps 1–6, a continuous severity score, no thresholds applied yet), not its *thresholded* output (steps 7–8, which is what P3.3 adds). First thing to hand off if the frontend track is running behind, since it gates nothing downstream except P3.3.
- **Session P1.8** *(prereq: P1.7)*: E5 step 7 (PPT comparison tables), handed to Lead.

*Frontend track (a separate branch — Part 8):*
- **Session P1.9 — Scaffold** *(prereq: Lead L1)*: builds out the minimal skeleton L1 already created (not a from-scratch `npm create vite` — that already happened) into the real app shell: `react-router-dom` routing for all 7 screens as placeholders, generated client wired to an env-configurable base URL, `AuthContext` holding the JWT in memory.
- **Session P1.10 — Login + Ingest** *(prereq: P5.4 for real `/auth/login`, P2.5 for real ingestion routes — build against mocks until then)*: both screens wired to real routes where they exist. Screenshot-verified against E6 before closing.
- **Session P1.11 — Lot Dashboard + Part Detail** *(prereq: P5.3 for the Lot Dashboard's `GET /lots/{lot_id}`, P5.7 for Part Detail's `GET /parts/{component_id}` — the two screens can be wired in either order within this session since their routes land in different P5 sessions)*: the two heaviest screens — Part Detail carries E4's full explanation payload. Screenshot-verified.
- **Session P1.12 — Project Browser, History, Settings** *(prereq: P2.8 for Project Browser/History, P5.8 for Settings — corrected from an earlier pass that named P5.7, which doesn't actually build the Settings endpoints; `GET/POST /settings*` land in P5.5 and the worklist/corrective-status endpoints land in P5.8, so P5.8 is the binding one)*: remaining three screens. Screenshot-verified. Closes G6 once P1.10–P1.12 are all green.

**Must-pass:** Generator's 7.3 row at P1.4. Frontend row of 7.3 at P1.12.

**Flag:** P1 carries the most sequential load on the team — see Part 2. If P1.9 onward is visibly behind schedule, hand off P1.7–P1.8 first.

## P2 — Ingestion, Features, Report, Storage

**Owns:** `ingestion/`, `features/`, `report/`, `storage/`. **Features:** E7, E8, E9, E11.

- **Session P2.1** *(prereq: G0)*: **First: confirm your own clean install and that you reviewed/signed off on `contracts.py` during L1 — specifically `LotDataset` (your input) and `FeatureFrame` (your output). If not done yet, do it now before building.** Then: stub `FeatureFrame`; a stub `POST /lots` route returning a canned response (so P1's frontend has something to hit early); E11 steps 1–3 (`accounts`/`projects` tables, indexes — pulled forward since routers need a working DB early) **plus the `save_account` and `save_project` repository functions specifically** (not just the table schemas) — `save_account` is what `scripts/seed.py` needs to exist before anyone can log in locally at all, and `save_project` is what a new lot's first ingestion needs; the remaining repository functions (`save_analysis_run`, `save_disposition_signoff`, `save_confirmed_outcome`, `log_event`) stay in P2.6, where they were already scoped.
- **Session P2.2** *(prereq: P2.1 — buildable against synthetic fixtures, no need to wait on P1's real data)*: E7 steps 1–2 (upload+metadata, demo-lot button) → steps 3–5 (incremental merge-by-part-ID, lot status, validation with visible errors).
- **Session P2.3** *(prereq: P1.4)*: E7 steps 6–11 (normalization, quality checks, offset correction, cross-lot scope enforcement, unrecognized-parameter handling, attribution) against real data. Ingestion's 7.3 row green.
- **Session P2.4** *(prereq: P2.3 — closes G3 together with P2.6)*: E8 steps 1–5 (deltas, robust stats, <30 fallback, z-scores, joint feature vector). Features' 7.3 row green. Real `FeatureFrame` handed to P3/P4.
- **Session P2.5** *(prereq: P2.3, P2.4, Lead L1, P5.1 for the orchestrator stub)*: `ingestion/router.py` — replaces P2.1's stub route. `POST /lots` and `POST /lots/{lot_id}/checkpoints` now call `fusion.run_full_pipeline` (5.7 — stub or real, whichever exists) after a successful save, then `storage.save_analysis_run(...)` to persist the result, then `storage.log_event("analysis_run", ...)`. This wiring is what makes G3's exit criterion ("P2's storage repository API is callable") actually mean something end-to-end, not just that the functions exist in isolation.
- **Session P2.6** *(prereq: P2.1 — must land before P5.4 needs it)*: E11 steps 4–8 (`project_data`+diff, `events`, `disposition_signoffs`, `confirmed_outcomes`, full repository API).
- **Session P2.7** *(prereq: P2.4, P2.6)*: E9 steps 1–3 (report template, Analysis History section, `fpdf2` render) → steps 4–6 + `report/router.py`.
- **Session P2.8** *(prereq: P2.6)*: `storage/router.py` — projects, events, disposition-signoffs read routes.

**Must-pass:** Ingestion + Features 7.3 rows, plus every P2 route validating against its Pydantic contract.

## P3 — Module A

**Owns:** `module_a/`. **Features:** E2. No router — output consumed by P5 in-process.

- **Session P3.0 — Stub** *(prereq: G0 — a gap found while tracing this for explanation, not the prior two audit passes: P5.1 already said it "builds directly against P3/P4's own first-session stubs," but P3.1 as originally written required P2.4, so no session actually produced that stub at G0)*: **First: confirm your own clean install and that you reviewed/signed off on `contracts.py` during L1 — specifically `FeatureFrame` (your input) and `ModuleAResult` (your output).** Then: a `ModuleAResult`-shaped fixture with fixed fake scores, matching the frozen contract — lets P5.1 start immediately, per R6, without waiting on P2.4.
- **Session P3.1** *(prereq: P2.4)*: E2 steps 1–2 (robust z-scores, per-checkpoint MCD) + MCD-boundary test → step 3 (pooled cross-lot Isolation Forest, cold-start-safe) + cold-start test.
- **Session P3.2** *(prereq: P3.1)*: E2 step 4 (ECOD) + contamination-default test → steps 5–6 (percentile-normalize + max-combine; direction-awareness cap — **the flagged pitfall**: don't lot-relative Isolation Forest, don't remove the cap) + below-median-capped test.
- **Session P3.3** *(prereq: P3.2, and P1.7 for the harness-tuned thresholds step 8 actually applies — P3.3 finishes after P1.7, not in lockstep with P4.3 anymore)*: E2 steps 7–8 (explainable tags, harness-tuned thresholds). Golden test passes for real. Module A's 7.3 row fully green. `ModuleAResult` handed to P5, in-process. Closes G4 once P4.3 has also closed (independently, no shared files — see below).

**Must-pass:** unchanged. **Depends on:** P2's `FeatureFrame` contract (G0) to stub; real output (P2.4) to move past it; P1.7's harness-derived thresholds (new, via 5.1) to complete step 8 — this is Module A's only dependency on P1 beyond the initial contract, and it's one-directional (P1.7 needs P3.2's scoring, P3.3 needs P1.7's thresholds; neither waits on the other's *final* output). No dependency on P4 at any point.

## P4 — Module B

**Owns:** `module_b/`. **Features:** E3. No router — output consumed by P5 in-process.

- **Session P4.0 — Stub** *(prereq: G0 — same fix as P3.0, same reason)*: **First: confirm your own clean install and that you reviewed/signed off on `contracts.py` during L1 — specifically `FeatureFrame` (your input) and `ModuleBResult` (your output).** Then: a `ModuleBResult`-shaped fixture with fixed fake values, matching the frozen contract — lets P5.1 start immediately, per R6, without waiting on P2.4.
- **Session P4.1** *(prereq: P2.4)*: E3 step 1 (three physics baselines) + correctness tests → step 2 (global LightGBM quantile model per part number).
- **Session P4.2** *(prereq: P4.1)*: E3 step 3 (MAPIE CQR, lot-boundary-respecting calibration) + interval-ordering test → steps 4–5 (safety slope, `EARLY_REJECT` flagging).
- **Session P4.3** *(prereq: P4.2)*: E3 steps 6–7 (physics-disagreement gap, full field recording) + out-of-scope-parameter test. Module B's 7.3 row fully green. `ModuleBResult` handed to P5, in-process. Independent of Module A's timeline entirely — closes its half of G4 as soon as P4.2 is done, regardless of where P3/P1.7 are.

**Must-pass:** unchanged. **Depends on:** P2's `FeatureFrame` contract (G0) to stub; real output (P2.4) to move past it. No dependency on P3.

## P5 — Fusion, Explainability, Identity, CAPA

**Owns:** `fusion/`, `explain/`, `identity/`, `capa/`. **Features:** E4, E10, E12, E13.

- **Session P5.1** *(prereq: G0 — builds directly against P3.0's and P4.0's stubs)*: **First: confirm your own clean install and that you reviewed/signed off on `contracts.py` during L1 — specifically `ModuleAResult` and `ModuleBResult` (your inputs) and `RiskAssessment`/`LotDisposition` (your output).** Then: stub `RiskAssessment` + `LotDisposition`, **and a callable stub of `fusion.run_full_pipeline` (5.7)** returning fixed `AnalysisResults` — a data-shape stub alone isn't enough here, since P2.5 needs an actual function to call, per R6.
- **Session P5.2** *(prereq: P3.3, P4.3)*: E12 steps 1–2 (two-tier verdict, explainability gate + composability) + gate/composability tests.
- **Session P5.3** *(prereq: P5.2)*: E12 steps 3–6 (PDA rollup, early-rejects count, forecast PDA for In-Progress lots, two separate ranked lists) + wording/counting tests. **Also wires `fusion/router.py`'s `GET /lots/{lot_id}` now** — `LotSummaryResponse` is fully computable as soon as this session closes, no reason to make the Lot Dashboard wait for Explainability too.
- **Session P5.4 — Identity + auth** *(prereq: P2.6 — on P1's critical path, prioritize)*: E10 steps 1–2 (two named accounts, hashed PINs, login requirement) plus `create_access_token`/`get_current_account` (JWT). **Also wires `identity/router.py`'s `POST /auth/login` now** — this, not a later session, is what actually unblocks P1's Login screen; building only the JWT functions here without the route would leave P1 with nothing callable.
- **Session P5.5** *(prereq: P5.4)*: E10 steps 3–7 (Accept/Hold/Reject with rationale, two-distinct-account REJECT sign-off, same mechanism on `config_change`, timing flag, concurrency lock) + dual-sign-off test. **Also wires `identity/router.py`'s `POST /parts/{id}/disposition`, `GET /settings`, `POST /settings/propose`, `POST /settings/signoff`** — the dual-sign-off mechanism config-change reuses is built in this session, so the Settings endpoints belong here, not deferred.
- **Session P5.6** *(prereq: P5.5)*: E10 steps 8–9 (immutable records, history surfaced) + E13 steps 1–3 (`confirmed_outcomes` table, explicit match definition, separate FN/FP rates). No new route yet — `confirmed_outcomes` has no read endpoint of its own until P5.8, and `PartDetailResponse.confirmed_outcomes` (5.6) needs this session's query function before P5.7's aggregator can return it.
- **Session P5.7 — Explainability** *(prereq: P5.3, P5.6)*: E4 steps 1–4 (TreeSHAP, MCD decomposition, z-score-is-its-own-explanation, ECOD per-dimension) → steps 5–10 (sentence template, confidence qualifier, lot-level rollup, generalized severity-cap note, unavailable-forecast note, staleness note) + all-four-mechanisms test. **Also wires `fusion/router.py`'s `GET /parts/{component_id}` aggregator now** — needs P5.3 (fusion data) and P5.6 (confirmed-outcome query) as well as this session's own explanations, which is why both are listed as prerequisites, not just P5.3.
- **Session P5.8 — CAPA completion** *(prereq: P5.6)*: E13 steps 4–8 (Settings worklist, DPA work-order recommendation, third Settings value + ceiling, live-computed status, corrective `config_change`) + minimum-count test. **Also wires `capa/router.py`'s `POST /parts/{id}/confirmed-outcome`, `GET /settings/worklist`, `GET /settings/corrective-status`, `POST /lots/{id}/dpa-work-order`** — this is the last P5 route P1's frontend needs, which is why P1.12 (Settings screen) depends on this session, not an earlier one.
- **Session P5.9 — Router integration check** *(prereq: P5.3, P5.4, P5.5, P5.7, P5.8 — closes G5)*: not first-time route-building — every route above was already wired in the session that produced its underlying logic. This session runs the full 7.3 checklist and route-contract validation across all of P5's routes *together*, since a route working in isolation during its own session is not the same guarantee as it working after every other P5 session has also landed. **A gap found on this re-verification pass, not the prior one: an earlier version of this document bundled all of P5's router-building into this one session — meaning P1.10, P1.11, and P1.12 would each have stalled waiting for the very last P5 session regardless of what prerequisite they claimed, since none of their needed routes existed before it. Fixed by moving each route's construction into the session that already builds its logic, above — this session is now verification only, not construction.**

**Must-pass:** Fusion, Explainability, Identity/CAPA 7.3 rows — still the largest checklist — plus route-contract validation and a JWT round-trip test.

**Flag:** P5.4, P5.7, and P5.8 are each directly on a different part of P1's frontend critical path now (Login, Lot Dashboard/Part Detail, and Settings respectively) — not a single P5.9 bottleneck as an earlier pass had it. Worth the Lead watching all three, not just the last one.

---

# Part 11 — Blockers & Escalation

A shared `BLOCKERS.md`, append-only, checked by the Lead at the same fixed checkpoints as `CONTRACT_CHANGES.md` (Part 6). Anyone genuinely stuck (not just a contract gap — R6's stub-and-log pattern already covers that) logs it with what they tried; the Lead triages at the next checkpoint. Applies identically to frontend blockers (a route not landing on schedule, a generated-client regeneration that didn't pick up a change) — same file, same process, not a separate frontend-specific escalation path.

---

# Part 12 — Definition of Done (Project Level)

The project is done when: every essential feature (`essential-features.md`, E1–E13) passes its Part 7.3 checklist in the integrated build, not just standalone — the Frontend row included, verified by screenshot against E6's screen inventory, not just "the code exists"; the golden test passes; the full pipeline runs end to end through the actual UI (login → ingest → dashboard → part detail → disposition → report) on the seeded demo dataset with no crashes, via `scripts/build_demo.sh`'s single-process build; the demo has been rehearsed at least twice; and every claim in the PPT traces to a number the harness (E5) actually produced.
