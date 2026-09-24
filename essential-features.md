# Essential Features — SIH 26170 Burn-In Anomaly Detection System

This document specifies every **must-build** feature for the prototype. For the full research trail, evidence, and system-wide reasoning behind any decision referenced here, see [`context.md`](./context.md) — this document deliberately keeps rationale brief and links back rather than re-arguing it.

Each feature below follows the same shape: what it is, how to build it, how practical it is to build within the hackathon timeline, and why it made the essential (not stretch) list.

---

## E1 — Physics-Grounded Synthetic Data Generator

**What it is.** A configurable Python generator producing wide-format CSV lots of synthetic burn-in parts: per-part Iddq, leakage current, and propagation-delay readings at 0h/24h/(96h)/168h, plus hidden ground truth (`is_defective`, `defect_type`) kept separate from the production-facing schema.

**How to build it.**
1. Sample per-lot baseline center/spread per parameter from a lognormal distribution (lot-to-lot variation).
2. Sample each part's baseline from its lot's distribution (die-to-die variation).
3. Assign defect status per part (healthy majority; 1–8% defective, randomized per lot).
4. Generate healthy-part trajectories via power-law drift, `value(t) = baseline + A·tⁿ`, with `n` randomized in [0.15, 0.30] and `A` randomized per part.
5. Generate defective-part trajectories by adding an Arrhenius-scaled defect term with a randomized activation energy; some defect archetypes activate only after the 24h checkpoint.
6. Apply a shared "defect severity" correlation factor across the three parameters for defective parts only; keep healthy-part baseline noise close to independent across parameters.
7. Apply tester-offset correction (via simulated reference parts), quantization, and proportional Gaussian measurement noise.
8. Store elapsed time as an explicit numeric field per reading (not an assumed fixed schedule), so irregular checkpoint timing degrades gracefully downstream.
9. Implement five named, structurally distinct generator configurations for held-out validation: baseline / wider drift-exponent range / higher defect prevalence / different noise regime / altered parameter-correlation structure.
10. **Realism validation test**: extract comparable statistical parameters (degradation-rate distribution shape, noise-to-signal ratio, time-to-knee fraction) from both the generator's output and the real reference data already cited ([`context.md` Part 1.4/3.3](./context.md#33-the-generators-physical-grounding)), and compare with a Kolmogorov–Smirnov test (`scipy.stats.ks_2samp`), reporting the actual statistic and p-value. Part of the generator's own test suite, not a separate subsystem — see [`context.md` Part 3.4](./context.md#34-building-trust-without-real-validation-data--four-concrete-mechanisms) for why this replaces an earlier qualitative-only check.

**Practicality.** Pure NumPy/pandas/SciPy, no GPU dependency, runs in seconds per lot. Build first — every other feature and every model in this system depends on this one's output schema. Estimated 1–2 days for one person, testable incrementally lot-by-lot.

**Why essential.** No real dataset exists for this problem — see [`context.md` Part 3](./context.md#part-3--why-synthetic-data-and-how-to-trust-it) for the full search record and physical grounding for every parameter above. Every downstream metric is only as trustworthy as this generator.

---

## E2 — Module A: Outlier Detection Ensemble with Cost-Sensitive Threshold

**What it is.** The "dynamic outlier detection system" the problem statement asks for: a per-part severity score combining three detectors, flagged against two tuned thresholds (REVIEW, REJECT).

**How to build it.**
1. Compute robust z-scores per parameter per checkpoint: `(value − lot_median) / (lot_IQR / 1.35)`, lot-relative.
2. Fit a Minimum Covariance Determinant (MCD) estimator **per checkpoint** (3 features: one per parameter at that checkpoint) — not jointly across all checkpoints — using `sklearn.covariance.MinCovDet`, compute robust Mahalanobis distance per part, lot-relative. See [`context.md` Part 4.2](./context.md#42-module-a--outlier-detection) for why this dimensionality is pinned explicitly rather than left implicit.
3. Fit an Isolation Forest (`sklearn.ensemble.IsolationForest` or PyOD's implementation) on **pooled cross-lot history for the same part number** — deliberately not lot-relative, to catch campaign-level drift the other two detectors cannot see. On a part number's first-ever lot (no history yet), this detector contributes nothing rather than degrading unpredictably.
4. **Fourth candidate, ECOD** (`pyod.models.ecod.ECOD`), tested alongside the above three in the harness bake-off, not assumed a winner — parameter-free score computation (still takes a `contamination` value for thresholding, same as the others), deterministic, already in the PyOD dependency already used for Isolation Forest. See [`context.md` Part 4.2](./context.md#42-module-a--outlier-detection).
5. Percentile-normalize each detector's score within its own reference population, then combine via **maximum** as the default severity score.
6. **Direction-awareness**: a below-median (benign-direction) deviation is capped at WATCH-eligible severity, never REJECT-eligible on that basis alone, regardless of magnitude — the one exception (a pre-aged/recycled-part signature) is a stretch capability (`non-essential-features.md`), not built by default, so the cap applies unconditionally until that capability exists.
7. Tag each detector's contribution as explainable (z-score, MCD) or not (Isolation Forest, ECOD) — this tag feeds E12's verdict rule, so a REJECT is never issued on an unexplainable signal alone.
8. Apply two tuned thresholds (REVIEW, REJECT) from the evaluation harness (E5) rather than a fixed percentile. A part's overall severity is its **worst parameter's** severity — the natural consequence of step 5's maximum combination, not separate logic.

**Practicality.** Each detector is a handful of lines with scikit-learn/PyOD; the combination and threshold-tuning logic is the part needing genuine care and testing against the harness. Roughly 1 day.

**Pitfall, worth reading even if you skip everything else in `context.md`:** two things here look like inconsistencies an agent might "clean up," and both are deliberate. First, steps 1–2 are lot-relative while step 3 is pooled cross-lot — don't make Isolation Forest lot-relative to match the others; that removes the one signal built specifically to catch campaign-level drift. Second, step 6's cap looks like it's suppressing a real signal — it isn't; it's preventing an unexplainable-direction deviation from reaching REJECT, and removing it reopens a gap that was found and fixed on review (`context.md` 4.2).

**Why essential.** This is the literal Module A requirement. The ensemble design, the maximum-combination choice, the per-checkpoint MCD dimensionality, and the deliberate cross-lot vs. lot-relative asymmetry in Isolation Forest's reference population are all evidence-backed decisions — see [`context.md` Part 4.2](./context.md#42-module-a--outlier-detection) and [Part 6.1](./context.md#61-combining-module-as-three-detectors-into-one-severity-score).

---

## E3 — Module B: Drift Predictor and Calibrated Safety Slope

**What it is.** A regression model predicting Value_168h from `(Value_0h, Value_24h, [Value_96h])`, plus a calibrated safety slope for early-rejection flagging.

**How to build it.**
1. Implement three physics baselines that any deployed model must beat: persistence (168h = 24h), linear extrapolation, and power-law extrapolation fit from the current lot's healthy parts.
2. Train one **global** gradient-boosted quantile regression model per part number (**LightGBM** with quantile loss — resolved over XGBoost per `IMPLEMENTATION_PLAN.md` Part 3: native quantile objective, native NaN handling for a missing 96h reading, fast on CPU-only small-medium tabular data) — not separate per-lot models — using the feature vector `[Value_0h, Value_24h, (Value_96h), lot_median_0h, lot_median_24h, elapsed_hours]`.
3. Wrap the model with conformalized quantile regression (**MAPIE** — resolved over `crepes`, since it directly implements the CQR paper already cited below) calibrated globally per part number, pooling across lots. The calibration split respects lot boundaries; see [`context.md` Part 4.4](./context.md#44-calibrating-the-safety-slope--the-statements-one-undefined-term) for why the within-trajectory time-leakage failure mode doesn't apply to this architecture, and what still does.
4. Define the safety slope as the calibrated upper quantile of healthy-part drift rate.
5. Flag `EARLY_REJECT` when a part's predicted drift rate exceeds the safety slope.
6. **Physics-vs-model disagreement**: report the gap between the physics baseline's prediction (already computed in step 1) and the live model's prediction as an additional confidence signal — free to compute, since both numbers already exist for every part.
7. Record predicted value, calibrated interval, drift rate, physics-disagreement gap, threshold used, and flag outcome for every part.

**Practicality.** Gradient-boosting training is trivial on CPU; the CQR wiring needs more care but is well-documented in both suggested libraries. Roughly 1 day.

**Why essential.** This is the literal Module B requirement, and MAE is a named judging metric. The power-law baseline (not a naive straight line) and the CQR-based safety slope definition directly resolve the problem statement's one undefined term — see [`context.md` Part 4.3–4.4](./context.md#43-module-b--drift-prediction).

---

## E4 — Explainability Layer

**What it is.** The mechanism that turns model output into language a QA inspector would accept, per the statement's explicit judging criterion.

**How to build it.**
1. For Module B (gradient boosting): compute exact TreeSHAP values (`shap.TreeExplainer`) per flagged part. Rendered in Part Detail (E6, screen 4) as the sentence template below.
2. For Module A's MCD component: compute a per-parameter contribution decomposition of the Mahalanobis distance (not SHAP — a distinct technique appropriate to a covariance-based method). Rendered as its own chart in Part Detail (E6, screen 4), not folded silently into the sentence text.
3. For Module A's z-score component: no separate explanation step needed — the z-score value is already the explanation, shown in Part Detail's z-score table (E6, screen 4).
4. **For ECOD**: its own algorithm already computes a per-dimension tail probability per parameter before aggregating them into one score — expose those per-dimension values directly as ECOD's contribution chart in Part Detail, the same pattern as MCD's decomposition, not a new technique.
5. Combine all three model-driven mechanisms into a QA-facing sentence template, e.g.: *"Part X: leakage at 24h is 4.2 robust-σ above lot median (median = 10 µA, value = 45 µA). Predicted 168h drift exceeds the calibrated safety slope by 38%. Primary driver: 24h delta."*
6. Attach a confidence qualifier derived from the CQR interval width (e.g., "high confidence" vs. "borderline — recommend retest") **and the physics-vs-model disagreement gap** (E3 step 6) as a second, independent confidence signal shown alongside it.
7. Roll per-part explanations up into a short **lot-level summary** (e.g., "3 of 77 parts flagged, concentrated in leakage current, 2 crossing REVIEW only") — shown in the Lot Dashboard's summary panel (E6, screen 3), a template over already-computed per-part outputs, not a new model.
8. **Severity-cap note, generalized to cover both reasons a part's severity can be capped**, not just one: the explainability gate (E12's Isolation-Forest-only cap) or direction-awareness (E2's below-median cap) — worded for whichever reason actually applied. A hidden cap protects the system's logic but not the reviewer's understanding of it, for either reason alike.
9. When a parameter falls outside the trained three (E7 step 10), show an explicit "drift prediction unavailable" note in Part Detail in place of the trajectory chart, rather than leaving the space blank or misleadingly empty.
10. When a reopened project (E6, screen 5) has a newer analysis run than the one a disposition was signed off against, show a **staleness note** in Part Detail naming exactly what changed — sourced from the stored diff (E11), not a bare flag: which module activated, which prediction resolved into an actual, and which verdicts moved.

**Practicality.** SHAP is close to plug-and-play with tree models; the template layer is string formatting over already-computed values. Roughly 0.5 day.

**Why essential.** Explainability is an explicit, named evaluation criterion, not a nice-to-have. See [`context.md` Part 4.5](./context.md#45-explainability) for why three distinct explanation mechanisms are needed rather than one blanket label.

---

## E5 — Evaluation Harness Against Named Industry Baselines

**What it is.** The offline testing framework that benchmarks the system against real industry methods, tunes every threshold, and produces the evidence for both the PPT and the shipped model defaults.

**How to build it.**
1. Implement the three named baselines from [`context.md` Part 1.6](./context.md#16-what-industry-already-does-about-this--the-closest-existing-answer): static absolute limits, fixed delta limits (space-spec style), and AEC-Q001 static/dynamic PAT (robust mean ± 6 robust sigma).
2. Generate test sets across all five held-out generator families (E1), with an explicit **minimum count of each defect archetype** in every held-out test set — decoupled from however many lots the live demo dataset contains, since threshold-tuning and per-archetype accuracy claims are only as stable as the smallest archetype's sample count.
3. **Golden test, named explicitly**: a lot with median leakage 10 µA and a part at 45 µA against a 50 µA limit must be flagged. This is the problem statement's own worked example — the single most direct, checkable compliance test available, and every independently-reviewed peer approach converged on encoding it.
4. Score Module A: report recall-weighted metrics against a locked cost function — a stated False-Negative:False-Positive ratio, default 10:1 — and report F2, other metrics, and **recall at a fixed flag-rate** for monitoring only, not for tuning.
5. Score Module B: MAE and CQR interval coverage, against the physics baselines.
6. Test the Module A combination-strategy question empirically: maximum-combination vs. weighted-average vs. a supervised meta-model trained on the synthetic ground-truth labels (a legitimate option here specifically because we hold labels, unlike a real deployment) — the winner on held-out families becomes the shipped default.
7. Produce comparison tables/charts for the PPT's differentiation-versus-industry-baseline slide.

**Practicality.** Mostly composition of E1–E3's already-built pieces; the held-out-family discipline and the baseline implementations need deliberate design. Roughly 1 day.

**Why essential.** This is what turns "we built a model" into "we built something demonstrably better than industry practice" — directly answering the differentiation weakness common to prior SIH attempts on this same statement, none of which benchmarked against real industry methods. See [`context.md` Part 2.3](./context.md#23-open-source-sih-peer-attempts) and [Part 6.1](./context.md#61-combining-module-as-three-detectors-into-one-severity-score).

---

## E6 — Application Shell: The Complete Screen Inventory

**What it is.** Every screen in the shipped application, named once, here, as the single source of truth other features point to rather than re-describe — the fix for a pattern found on audit where multiple features referenced "the dashboard" without any feature actually listing what it contained (see [`context.md` Part 5.12](./context.md#512-a-gap-found-by-checking-every-feature-against-an-actual-screen-list-several-had-none)).

**How to build it — seven screens behind one navigation shell.**
1. **Login.** Select one of the two named accounts (E10), enter PIN. On success, the returned JWT is held in memory only (React Context) for the session's subsequent requests — never persisted — so a hard refresh returns to this screen; a disclosed trade-off (`context.md` Part 8.1), not a bug.
2. **Ingest.** Lot-file CSV upload, incremental checkpoint upload, the metadata form, and the "load synthetic demo lot" button (E7) — all attributed to the logged-in account.
3. **Lot Dashboard.** Auto-selects Early-Check (In-Progress, Module B only) or Full Disposition (Complete, both modules) by lot status — see [`context.md` Part 7.1](./context.md#71-architecture). Contains: the Lot Summary panel (metadata, overall verdict, flagged-part count, PDA result, E4's lot-level explanation summary, and N1's trend chart if built); the two severity-ranked lists — same flagged parts, different sort order, never fused (see [`context.md` Part 6.3](./context.md#63-combining-module-a-and-module-b-for-reviewer-triage--deliberately-not-combined)); a **Generate Report** button (triggers E9); and, on Complete lots, a **Generate DPA Work Order** action (E13 step 5) — a lot-level action, distinct from the Settings screen's cross-lot worklist below.
4. **Part Detail**, opened from either ranked list. Trajectory chart, z-score table, an **MCD contribution chart** and an **ECOD contribution chart** (each its own visual, using values both detectors already compute internally), the SHAP-driven sentence and confidence qualifier, the **physics-vs-model disagreement gap** (E3 step 6) as a second confidence signal, N10's case-based matches if built, and three conditional notes: a **severity-cap note**, generalized to whichever reason applied — the explainability gate or direction-awareness (E2 step 6) — never a single wording for both; an **unavailable-forecast note** for any parameter outside the trained three (E7 step 10); and a **staleness note**, backed by the stored diff, when a newer analysis run exists than the one a shown disposition was made against. Disposition actions (E10), and — on a past disposition — the action to **record a confirmed outcome** (E13, its own record, not an edit to the disposition), live here.
5. **Project Browser.** Every project on record; opening one reloads screens 3–4 from the most recent `project_data` row for that project (E11) — each analysis run is its own stored row, not an overwritten one.
6. **History.** The full event and disposition log, identical for both accounts — no filtering by who's logged in (see [`context.md` Part 5.14](./context.md#514-log-visibility-must-be-symmetric-or-the-identity-mechanism-doesnt-do-its-job)). `analysis_run` entries carry the stored diff, not just a timestamp.
7. **Settings.** Three live-editable values under dual sign-off (E10): the FN:FP cost ratio, the PDA threshold, and the confirmed-outcome false-negative rate ceiling (E13). A proposed change is visually distinguished from a finalized one, reusing the disposition workflow's own pending state. A **worklist** of dispositions awaiting a confirmed outcome (tracking only — generation happens per-lot on screen 3), and a **live-computed corrective status** (recalculated on view, not a stored alert) appear here (E13).

**Practicality.** Built as a React + TypeScript single-page app consuming a FastAPI backend over REST — resolved as the primary build, not a conditional stretch (`context.md` 7.13 has the full reasoning for the revision). Roughly 2–2.5 sessions once the backend routes each screen depends on are real, most of it screen-by-screen wiring against an already-typed, generated API client rather than hand-written data fetching. Owned by P1 (`IMPLEMENTATION_PLAN.md` Part 2), not P5 — every screen still only displays what E1–E5 and E10–E12 already compute, the resplit changes who builds the display layer, not what it shows.

**Why essential.** A working, usable interface is expected in the Software category. Every screen here maps to a specific requirement or fix documented elsewhere — this entry exists so a builder never has to infer where a feature belongs.

---

## E7 — Flexible Lot Ingestion

**What it is.** The data-intake layer: file upload, metadata capture, validation, and schema normalization.

**How to build it.**
1. Primary path: CSV lot-file upload plus a metadata form (part number, lot ID, manufacturer, date code, test date, per-parameter units).
2. Secondary path: a "load synthetic demo lot" button, so the system is demonstrable without a file on hand.
3. **Incremental ingestion**: uploading a new checkpoint file for a lot already on record merges it into that lot's history, matched by part ID, rather than requiring one pre-assembled file — this mirrors how real burn-in data actually arrives, in separate readout events over the campaign (see [`context.md` Part 5.4](./context.md#54-a-procedural-gap-found-by-re-checking-the-standard-data-arrives-per-checkpoint-not-per-lot)).
4. Lot status field (In-Progress vs. Complete) — auto-updates as checkpoints accumulate, or user-set.
5. Schema validation with visible, specific error messages (not silent failure); fuzzy column-name matching with a confirmation step for ambiguous matches.
6. Unit normalization to a canonical unit per parameter before any downstream processing.
7. Data-quality checks: missing values, out-of-datasheet-range flags, duplicate part IDs.
8. Optional tester-offset correction if reference/control parts are present in the uploaded lot.
9. Scope enforcement: all downstream cross-lot pooling (E2's Isolation Forest, E3's global model) stays within the same part number.
10. Unrecognized-parameter handling: a numeric column outside the three trained parameters is passed to Module A (E2) as a generic statistical check (z-score/MCD need no physics grounding to function), but Module B (E3) reports drift prediction as unavailable for it rather than attempting an uncalibrated forecast — see [`context.md` Part 5.9](./context.md#59-a-schema-robustness-question-found-on-review-what-happens-with-a-parameter-we-never-modeled).
11. Attribution: every ingestion event is tagged with the logged-in named account (E10), the same identity mechanism used for disposition sign-off — closes a gap where uploaded data previously had no recorded source.

**Practicality.** A column-mapping and validation function; roughly half a day, mostly careful error-message writing and the checkpoint-merge logic. The pre-ingestion editable sandbox discussed during design is a **private development tool**, used while building and testing Module A/B — it is not part of this stage, and is not surfaced in the shipped application (see [`context.md` Part 5.8](./context.md#58-a-pre-ingestion-data-sandbox--decided-as-a-private-dev-tool-deliberately-not-part-of-the-shipped-product)).

**Why essential.** The statement gives no fixed input format, and whether 96h is available at inference time is genuinely ambiguous from the statement text — this is a stated, documented assumption (see [`context.md` Part 8.1](./context.md#81-simplifications-by-area)), not an oversight, and the ingestion layer is built to degrade gracefully either way.

---

## E8 — Feature Engineering Layer

**What it is.** The transformation step between raw ingested readings and model-ready inputs.

**How to build it.**
1. Compute delta features per parameter (Δ24h, Δ96h if present), and emit **one `FeatureFrame` per (component, parameter) pair** — each frame carries its own `parameter` and `part_number` fields (so Module B can select its per-part-number model), `robust_z` keyed by checkpoint label (`"0h"`, `"24h"`, `"96h"`), and `elapsed_hours` as a dict keyed the same way, holding each checkpoint's actual elapsed hours (irregular checkpoints are allowed, `context.md` 5.9).
2. Compute lot-level robust statistics (median, IQR/1.35) per parameter per checkpoint.
3. Implement the small-lot fallback: **fewer than 30 parts** (the exact AEC-Q001 minimum, not an approximation) falls back to a pooled cross-lot reference for that part number, with a visible UI flag stating this happened — never a silent substitution; 30 or more parts uses lot-relative statistics directly.
4. Compute per-part robust z-scores at each available checkpoint.
5. Assemble the joint feature vector for MCD (E2) and the input vector for Module B (E3).

**Practicality.** Straightforward pandas transformations; well under half a day once E1's schema is fixed.

**Why essential.** Every downstream module depends on this layer's output being correct and consistently shaped; the small-lot fallback specifically prevents a common, silent failure mode (unstable robust statistics on too few parts) documented in the AEC-Q001 sample-size guidance — see [`context.md` Part 1.6](./context.md#16-what-industry-already-does-about-this--the-closest-existing-answer).

---

## E9 — Lot Screening Report Generator

**What it is.** The exportable document that is the system's actual deliverable, mirroring the real industry "data package" concept.

**How to build it.**
1. Populate a template with: report reference ID, part number, lot ID, date code, manufacturer, test date, methodology summary, quantity screened/flagged, PDA result, full delta-data table, per-flagged-part explanation and disposition, overall lot disposition, reviewer/date block.
2. Add an **Analysis History section**, present in every report: each run, what triggered it, and what changed from the run before, sourced from the stored diff (E11) — "1 run, no revisions" for a lot analyzed once, a real changelog otherwise; capped at the most recent 10 runs in the printed PDF, with a note pointing to the JSON export or History screen for the full record.
3. Render to PDF with **`fpdf2`** — resolved over `weasyprint` per `IMPLEMENTATION_PLAN.md` Part 3, specifically to avoid a system-dependency install risk (Pango/Cairo) across five people's machines with no debugging time to spare.
4. Attach the raw CSV as the underlying electronic data record alongside the PDF.
5. Export the same structured content as JSON alongside the PDF/CSV — this JSON is the same object stored as `project_data` (E11) for reload, not a separately maintained copy.
6. Triggered by the **Generate Report** button on the Lot Dashboard (E6, screen 3) — the location that was missing until the screen inventory made it explicit.

**Practicality.** A templating exercise over data already computed by E2–E6; roughly 0.5–1 day, most of it layout polish.

**Why essential.** In real screening workflows, the actual filed deliverable is this document, not a live dashboard — see [`context.md` Part 5.3](./context.md#53-the-deliverable-is-a-document-not-a-screen). This was promoted from a stretch idea to essential specifically because of that realization.

---

## E10 — Disposition Workflow & Identity

**What it is.** The human-in-the-loop decision step that turns a model flag into an authorized action, and the thing E4's explanations are actually written for — built around named accounts rather than a self-selected role, after an earlier role-dropdown design turned out not to actually prevent one person satisfying both sign-offs.

**How to build it.**
1. Seed exactly two named accounts at creation time, each with a **fixed role** (e.g., A. Sharma — Quality Engineer; R. Mehta — Reliability Engineer) and a lightweight PIN, hashed before storage. Role is set once, at account creation — never self-selected at login or at the moment of disposition.
2. Require login as one of these accounts before any ingestion or disposition action; every subsequent action is attributed to that account ID (shared with E7's ingestion attribution). **With the FastAPI+React stack (`context.md` 7.13):** on a successful PIN check, issue a short-lived JWT (`PyJWT`, HS256) encoding `account_id` and `role`; a FastAPI dependency verifies it on every protected route. No server-side session table — the token is self-verifying and stateless, matching the rest of this feature's already-disclosed non-production security scope.
3. Per flagged part (or lot), present Accept / Hold for retest / Reject as explicit actions, each requiring a written rationale.
4. **REJECT requires sign-off from two distinct account IDs**, not two role labels — the specific fix for the loophole a label-only check leaves open (see [`context.md` Part 5.6](./context.md#56-cross-functional-disposition--from-a-role-dropdown-to-named-accounts-and-why-the-difference-matters)).
5. Extend the identical two-distinct-account mechanism to `config_change` events (e.g., changing the FN:FP cost ratio or PDA threshold), proposed and finalized from the **Settings** screen (E6, screen 7) — reusing this code path rather than building a second one, since a configuration change affects every future lot, a larger blast radius than any single disposition (see [`context.md` Part 5.11](./context.md#511-extending-the-same-dual-authorization-mechanism-to-configuration-changes)).
6. Add a non-blocking **timing flag**: if two sign-offs on the same part land under two minutes apart, note it in the log — never block the action, since a live demo can legitimately have fast back-to-back approvals.
7. Add a **concurrency lock** around the disposition write itself, so two reviewers acting on the same part within moments of each other cannot produce an inconsistent write — a correctness fix, not a gaming concern.
8. Store each decision as a new, immutable record — a correction creates an additional record rather than editing the previous one.
9. Surface the decision history in the part/lot detail view.

**Practicality.** A login form, two seeded accounts, and a database row; roughly half a day given E6 and E9 already exist — the dual sign-off needs a small state machine (pending second sign-off vs. finalized), and the concurrency lock is a few lines around the write itself. No real authentication is built — the PIN is explicitly a deterrence/auditability speed bump, not security, a deliberate, disclosed scope line (see [`context.md` Part 8.1](./context.md#81-simplifications-by-area)).

**Why essential.** This directly operationalizes the explainability criterion: an explanation that a human then acts on and signs off is a materially stronger answer to "can the model justify its classification to a QA inspector" than a displayed paragraph alone, and the named-account dual sign-off is a closer, and now actually-working, match to how real nonconforming-material review operates. See [`context.md` Part 5.2 and 5.6](./context.md#52-the-disposition-decision-is-always-human-authorized).

---

## E11 — Persistent Storage: Global Log & Project State

**What it is.** The storage layer behind identity (E10), ingestion attribution (E7), the audit trail, and E6's Project Browser — a single global store, not one log per project, once it became clear that N1 and N10 both need to query across projects, not within one (see [`context.md` Part 5.10](./context.md#510-where-logs-actually-live--one-global-store-not-per-project-silos)).

**How to build it.**
1. Use SQLite as the committed default (not conditional on time remaining), with `project_id` as an indexed column on every relevant table, plus an index on `account_id`.
2. `accounts` table: account_id, display name, role, PIN hash — set once at account creation (E10).
3. `projects` table: project_id, lot_id, part_number, created_at, created_by — one row per lot's metadata.
4. **`project_data` table: analysis_run_id (primary key), project_id, raw_ingested_data, results_json** (features, every Module A detector's score and explainability tag, Module B's prediction/interval, explanations, verdict — identical in shape to E9's JSON export), **plus a computed diff against the immediately prior run for this project**. One new row per `analysis_run`, never an overwrite — "current results" is the most recent row, a query, not a stored flag. **This is a correction to an earlier version of this design, not the original plan**: the first version updated a single row per project, which let a disposition go stale relative to data the reviewer never actually saw (see [`context.md` Part 5.15](./context.md#515-analysis-runs-must-be-append-only-too--and-what-what-changed-actually-needs-to-contain)). The diff itself computes three things, not a generic "values changed": whether a module activated for the first time (e.g. Module A running once a lot completes), any Module B prediction that resolved into an actual reading, and any verdict that moved.
5. `events` table, append-only: event_id, project_id, account_id, event_type (`ingest`, `checkpoint_add`, `analysis_run`, `config_change`), timestamp, payload — for `analysis_run` events, the payload is the same diff stored in `project_data`. **No "edit" event type exists** — a correction always produces a new event, never an overwrite.
6. `disposition_signoffs` table, append-only, kept separate from `events`: project_id, part_id, **analysis_run_id** (which snapshot this decision was made against), account_id, verdict, rationale, timestamp — separated specifically so REJECT's two-distinct-account rule (E10) can be checked with a simple per-part query.
7. **`confirmed_outcomes` table, append-only, its own table rather than fields on `disposition_signoffs`**: confirmed_outcome_id, project_id, part_id, **analysis_run_id** (which run's verdict this confirms or refutes), account_id, confirmed_outcome, note, recorded_at. **A correction to an earlier version of this design**, which put nullable fields directly on `disposition_signoffs` — an edit-after-creation on the one table where immutability matters most, contradicting the append-only rule this entry exists to enforce (see [`context.md` Part 5.17](./context.md#517-the-feedback-loop-built-in-full--visibility-and-a-corrective-step-not-visibility-alone)). Links to `analysis_run_id`, not to the disposition itself, because the feedback loop measures whether the *model's* verdict tier was right, not whether the human's decision was — those are different questions. No dual sign-off required: this records an external fact, not a judgment call.
8. Surface `events`/`disposition_signoffs` as the History screen, `projects` as the Project Browser list, and the latest `project_data` row per project as what populates screens 3–4 on reload (E6, screens 5–6).

**Practicality.** SQLite has no separate service to stand up; six simple tables plus two indexes. Roughly 1 day — the increase from earlier estimates is specifically the diff computation (a comparison between two stored JSON snapshots, run once at write time) and wiring `analysis_run_id` through disposition sign-off, confirmed outcomes, and report generation.

**Why essential.** Screening records must be retained and *reopenable*, not just written once — see [`context.md` Part 5.7](./context.md#57-why-a-screening-record-needs-to-be-reopenable-not-just-logged). Making every table genuinely append-only, with no exceptions, is what keeps a signed-off decision permanently anchored to the exact data it was made against — without `analysis_run_id`, a reopened project could silently show a disposition next to numbers the reviewer never saw. This is still a minimum viable version, not a production-grade audit ledger — no retention/backup strategy, and passive views (who merely opened a project) are deliberately not logged — see [`context.md` Part 8.1](./context.md#81-simplifications-by-area) for the explicit scope lines drawn here.

---

## E12 — Fusion & Verdict: Lot Disposition Logic

**What it is.** The Stage 5 logic that turns Module A's and Module B's separate outputs into a per-part verdict and a lot-level disposition recommendation — the step between the two models and everything the reviewer sees.

**How to build it.**
1. Apply the two-tier verdict table per part: neither module past REVIEW → PASS; exactly one module past REVIEW (not REJECT) → WATCH; either module past REJECT, or both past REVIEW together → REJECT — see [`context.md` Part 6.2](./context.md#62-combining-module-a-and-module-b-into-one-part-level-verdict) for the guard-band precedent this follows. A part's overall severity is its worst parameter's, per E2's max-combination.
2. **Explainability gate on REJECT:** if Module A's severity score is driven solely by the unexplainable detector (Isolation Forest, per E2's explainability tag), cap **Module A's own tier** at REVIEW before the fusion table runs — a REJECT must be corroborated by an explainable detector (z-score or MCD). This composes correctly with rule 1's last row without a special case: if Module B independently also crosses REVIEW, "both cross REVIEW together" still fires REJECT, legitimately, because Module B supplies its own explainable corroboration. This is a disclosed trade-off (single-reviewer WATCH instead of dual-sign-off REJECT for cross-lot-only signals), not a free improvement — see [`context.md` Part 6.2](./context.md#62-combining-module-a-and-module-b-into-one-part-level-verdict). **The cap must be visible wherever it materially affected the outcome** — Part Detail (E4 step 8) shows the note whether the result was a held-down WATCH or a REJECT that relied on Module B alone; a hidden cap protects the system's logic but not the reviewer's understanding of it. The same tier logic respects E2's direction-awareness cap (below-median deviations never reach REJECT-eligibility on their own).
3. Roll up to a lot-level PDA check: failures ÷ total parts submitted for burn-in, against the default 5% threshold (adjustable).
4. **Early-rejected parts (from Module B, before 168h) count toward the PDA failure tally**, not just parts that fail after completing the full campaign — this follows directly from the real PDA formula's own wording ("submitted for burn-in," not "completed burn-in") and closes a real gaming loophole where early rejection could otherwise make a lot look artificially clean. See [`context.md` Part 5.5](./context.md#55-a-procedural-question-the-design-had-left-silently-unanswered-do-early-rejects-count-toward-pda).
5. **Run the same PDA rollup on In-Progress lots**, using Module B's early per-part predictions instead of final measured outcomes, producing a distinctly-labeled forecast — `LOT_ON_TRACK` / `LOT_AT_RISK` / `STOP_RUN_RECOMMENDED` — never the same wording as the Complete-lot's measured verdict, so a forecast is never mistaken for a final figure. `STOP_RUN_RECOMMENDED` fires only when the **lower bound** of the forecast's calibrated interval already exceeds the PDA limit — see [`context.md` Part 5.18](./context.md#518-a-gap-found-by-re-reading-our-own-pda-logic-it-only-ever-runs-after-the-fact).
6. Produce two separate severity-ranked lists (Module A concerns, Module B concerns) for reviewer triage — deliberately not fused into one ranking.

**Practicality.** Mostly composition of logic already computed by E2/E3; the verdict table and PDA rollup are a few dozen lines. Roughly half a day for the base rollup, plus a further half day to extend it to In-Progress lots and design the forecast-specific wording — most of it making sure the early-reject counting rule and the forecast/final distinction are applied consistently everywhere a PDA number is shown (dashboard, report).

**Pitfall:** it's tempting to only count a part toward PDA once it *fails* after completing the full 168h — don't; an early-rejected part still counts (step 4), because it was "submitted for burn-in" per the real PDA formula's own wording, and skipping this reopens a gaming loophole that was specifically found and closed on review (`context.md` 5.5). Separately, the explainability gate (step 2) composes with the verdict table in one specific, non-obvious way: if Module A is capped but Module B independently crosses REVIEW too, the combined result is still REJECT — that's correct, not a bug to "fix" by also capping the combined verdict.

**Why essential.** This is the literal bridge between the two named modules in the problem statement and the lot-level disposition a real QA process actually needs — without it, Module A and Module B are two disconnected scores, not a screening decision. The early-reject counting rule specifically closes a correctness gap found by re-reading the real PDA formula's own wording, not an invented requirement. The early forecast is the single highest-value addition found across a full review of independent peer approaches to this same problem — it answers "will this lot bust PDA" before the chamber-time it would save is already spent.

---

## E13 — Feedback Loop: Visibility & Corrective Action (CAPA)

**What it is.** The mechanism by which a part's real-world eventual outcome — confirmed after the fact, outside the system — feeds back into the product: both showing how the model's verdicts have tracked reality (visibility) and flagging when they haven't been tracking it well enough to warrant a human decision (corrective). Promoted from a stretch idea (the former `non-essential-features.md` N9) to essential once both halves were committed. Two problems in the first version of this design are corrected below, not left standing.

**How to build it.**
1. `confirmed_outcomes` as its own append-only table (E11), not fields on `disposition_signoffs`: confirmed_outcome_id, project_id, part_id, **analysis_run_id**, account_id, confirmed_outcome (Confirmed Good / Confirmed Defective / Unknown), note, recorded_at — recordable from Part Detail (E6, screen 4) on any past project. Linked to `analysis_run_id` rather than the disposition itself, because this measures whether the **model's verdict tier** (PASS/WATCH/REJECT, E12) was right, not whether the human's final decision was — a reviewer can already override the model for their own reasons, and those are different questions. No dual sign-off required — this records an external fact, not a judgment call.
2. **Define the match explicitly**, comparing confirmed outcome against the model's verdict tier: Confirmed Defective + PASS = a miss; WATCH or REJECT = caught. Confirmed Good + REJECT = a false alarm; PASS or WATCH = fine.
3. Compute **false-negative and false-positive rates among confirmed outcomes separately** — not a single blended accuracy figure. A blended score would contradict E5's own harness design, which treats F2 and similar metrics as "for monitoring only, not for tuning" specifically because a blended number can hide a bad false-negative rate behind a good false-positive rate — the exact risk the whole 10:1 cost asymmetry (E2) exists to prevent.
4. A **worklist** on the Settings screen (E6, screen 7): "N dispositions awaiting a confirmed outcome," linking into each — tracking only, so the loop fills in deliberately rather than only when someone happens to reopen the right project by chance; without this, the trend would only ever reflect whichever handful of outcomes someone stumbled into recording, not a real signal.
5. **DPA-sample recommendation, giving the confirmed-outcome mechanism domain-specific content**: on the Lot Dashboard (E6, screen 3) for a Complete lot, a **Generate DPA Work Order** action recommends up to 3 parts most worth sending for destructive physical analysis (the real ISRO-practice mechanism that actually produces a confirmed outcome, per [`context.md` Part 5.19](./context.md#519-what-confirmed-outcome-actually-means-for-us-made-concrete)) — the highest-severity part, the highest-uncertainty part nearest the WATCH/REJECT boundary, and one control part from the unflagged population. Each recommendation carries a one-line reason, matching E4's explanation discipline. This is a lot-level generation action, distinct from the Settings worklist above, which only tracks pending confirmations across every lot.
6. A third live-editable Settings value (E10, alongside the FN:FP ratio and PDA threshold): a confirmed-outcome **false-negative rate ceiling**, defaulting to **5%**, active only once at least **10 confirmed outcomes** exist (so a couple of early cases can't trigger a statistically meaningless status).
7. When the FN rate among confirmed outcomes crosses the ceiling, show a **live-computed status on the Settings screen** — recalculated whenever the screen is viewed, not a stored, stateful alert that needs dismissing. The false-positive rate is shown alongside for context, never as a trigger. The status does not change anything by itself, and is purely view-triggered — the system has no push or notification layer.
8. Any resulting threshold change is an ordinary `config_change`, going through the same two-distinct-account dual sign-off already built for Settings (E10) — corrective action reuses the existing authorization path rather than getting a new one.

**Practicality.** Low-moderate. One extra table plus a form and a worklist query (visibility), a rate check plus a Settings-screen status (corrective), and a small selection rule over already-computed severity/uncertainty scores (DPA recommendation) — all build on infrastructure E2/E3/E10/E11 already provide. Roughly a day, most of it the worklist, the FN/FP-split computation, and the DPA selection rule.

**Pitfall, and this one is worth taking seriously because it already happened once:** an earlier version of this exact feature put `confirmed_outcome` fields directly on `disposition_signoffs`, filled in later — which broke that table's append-only guarantee the moment a real-world outcome arrived after the fact. If a rebuild of this feature ever "simplifies" by folding these fields back onto the disposition record, it's reintroducing a bug that was already found and fixed once (`context.md` 5.17). Keep `confirmed_outcomes` as its own table, always.

**Why essential.** The same FAA guidance cited elsewhere in this document (`context.md` Part 5.2, 5.7) is explicit that real oversight means detecting adverse trends **and** determining corrective action — CAPA names this pairing directly, and a system that only displays a trend number satisfies half of it. Deliberately, the corrective step never auto-adjusts a threshold — it surfaces a status that a human acts on, consistent with the human-authorized-decision principle this entire design follows (see [`context.md` Part 5.2 and 5.17](./context.md#52-the-disposition-decision-is-always-human-authorized)). Honest limit: there is no real field-failure data to demonstrate this against in a hackathon setting, which caps how convincing a live demonstration of this specific feature can be, independent of whether it's correctly built.
