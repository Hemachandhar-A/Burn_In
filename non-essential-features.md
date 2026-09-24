# Non-Essential (Stretch) Features — SIH 26170 Burn-In Anomaly Detection System

This document specifies features to build **only if time remains** after every item in [`essential-features.md`](./essential-features.md) is working. For the full research trail and system-wide reasoning behind any decision referenced here, see [`context.md`](./context.md).

Features are ordered by priority — build N1 before N2, and so on, if forced to choose.

---

## N1 — Cross-Lot Campaign Monitoring (CUSUM/EWMA)

**What it is.** A statistical process-control layer that tracks reference-part or lot-median drift **across an entire burn-in campaign over time**, not just within one lot — catching slow process drift that a single-lot view cannot see by construction.

**How to build it.**
1. Maintain a running series of reference-part or lot-median readings across successive lots for the same part number.
2. Implement a CUSUM (cumulative sum) and/or EWMA (exponentially weighted moving average) control statistic over this series — both are standard, well-established statistical process control tools purpose-built to catch small, sustained shifts that ordinary control charts are slow to detect ([JMP statistical reference](https://www.jmp.com/en/statistics-knowledge-portal/quality-and-reliability-methods/control-charts/cusum-and-ewma-control-charts)), and both see real use in semiconductor fabrication specifically for this kind of slow process drift ([reference](https://www.visualizing.org/cusum-chart)). See [`context.md` Part 4.2b](./context.md#42b-a-fourth-candidate-considered-for-cross-lot-trend-monitoring-cusumewma) for the full grounding.
3. Surface this as a trend chart in the **Lot Dashboard's summary panel** (E6, screen 3), alongside the existing per-lot view.
4. Flag a campaign-level alert separately from any single lot's Module A/B flags — this is a distinct signal, not a replacement for either module.

**Practicality.** Moderate. The statistical computation itself is short code (a hand-rolled CUSUM/EWMA is a few dozen lines, or use an existing statistical process control library). The larger cost is a convincing multi-lot demo narrative — this feature has little value shown against a single uploaded lot, so it needs either several synthetic demo lots pre-loaded or a live multi-lot walkthrough to land in a presentation.

**Why non-essential, but first in line.** This is not required by the problem statement's Module A/B definitions, which are both part-level and lot-level, not campaign-level. It is high-value chiefly as a "we understood the bigger picture" differentiator if time allows — Isolation Forest's pooled cross-lot reference population (see `essential-features.md` E2) already gives partial campaign-awareness; this feature makes that visible and interpretable rather than adding new detection capability from scratch.

---

## N2 — TabPFN as a Live Module B Challenger

**What it is.** Promoting TabPFN from a harness-only evaluation model (see `essential-features.md` E3 and E5) to an actual second live prediction shown alongside the gradient-boosted model's output.

**How to build it.**
1. Load a pretrained TabPFN checkpoint (already evaluated in the harness, E5).
2. Run it at inference time alongside the primary gradient-boosted model.
3. Display both predictions in the part-detail view, with the harness's own comparison numbers (MAE, calibration) as context for why one or the other is trusted more.

**Practicality.** Moderate. The model logic already exists from E5's harness evaluation — the added work is packaging the model download and CPU inference time so the demo does not stall, and designing a UI element that shows two predictions without confusing a QA-inspector-facing view.

**Why non-essential.** The live model choice was deliberately kept to gradient boosting alone specifically to avoid a model-download dependency at demo time (a logistics decision, not a performance claim — see [`context.md` Part 4.3](./context.md#43-module-b--drift-prediction)). Showing both live is a nice trust-building addition once the core system is stable, not a requirement.

---

## N3 — Equipment/Chamber-Fault Discrimination

**What it is.** A third classification category, alongside "healthy" and "defective": readings that look anomalous because of a **measurement or equipment artifact** (a board issue, a chamber fault, a handling error) rather than because the part itself is bad.

**How to build it.**
1. Extend the synthetic generator (E1) with a distinct fault archetype: an anomaly pattern statistically different from true defect drift (e.g., affecting all parts in a physical test position simultaneously, or appearing as a step-change rather than a gradual drift), labeled separately in ground truth.
2. Train or rule-base a discrimination step that flags "possible equipment artifact" separately from "possible part defect," using cues such as simultaneity across otherwise-unrelated parts in the same test run.
3. Surface this as a third disposition-relevant category in the dashboard (E6) and report (E9).

**Practicality.** Moderate-to-high. This requires its own generator work (a new synthetic fault class with a genuinely different statistical signature from a real defect, not just a relabeling of the existing defect archetypes) plus a real discrimination model or rule set — meaningfully more design effort than N1 or N2.

**Why non-essential, but valuable if reached.** This directly answers a real, commonly-asked QA question the MVP cannot currently answer (see [`context.md` Part 8.2](./context.md#82-is-simplification-the-right-call-here)) — it is one of the two disclosed scope gaps flagged as worth anticipating in judge questions, even though it did not make the essential list under the deadline.

---

## N4 — Defect-Mechanism Classification

**What it is.** Going beyond a binary anomaly flag to a labeled likely mechanism — e.g., "late-activating latent defect" vs. "uniformly elevated part from time zero" — using the distinct defect archetypes already present in the synthetic generator's ground truth.

**How to build it.**
1. Since the generator (E1) already tracks which defect archetype produced a given synthetic part's trajectory, train a simple classifier (or use rule-based logic on the trajectory shape) to predict the likely archetype for a flagged part.
2. Surface this as an additional line in the explanation text (E4) and report (E9): e.g., "trajectory pattern consistent with late-activating defect (elevated only after 24h checkpoint)."

**Practicality.** Moderate. Mostly a labeling/reporting layer over data the generator already produces — the classification model itself is a straightforward multi-class problem once the archetype labels exist, but it adds another model to validate and explain.

**Why non-essential.** Adds interpretive depth beyond what the problem statement explicitly asks for (a flag plus a justification, not a diagnosed root cause) — valuable polish, not a scored requirement.

---

## N5 — Hierarchical/Random-Effects Degradation Model

**What it is.** A statistically rigorous alternative to gradient boosting for Module B: a mixed-effects or Wiener/gamma-process degradation model with explicit per-part random effects and per-lot fixed effects, which is the textbook-correct model class for this kind of nested, repeated-measures degradation data.

**How to build it.**
1. Specify a hierarchical model with a population-level drift trend, lot-level random effects, and part-level random effects, following the classical degradation-path modeling literature.
2. Fit via a statistical modeling library (e.g., `statsmodels` mixed-effects models, or a Bayesian implementation in `PyMC`).
3. Compare its MAE and calibration against the gradient-boosting primary model and TabPFN challenger in the evaluation harness (E5).

**Practicality.** High effort relative to return under this deadline: correctly specifying, fitting, and validating a hierarchical model is meaningfully more involved than the tree-based approach already delivering a fast, defensible result. Treat as a "we identified and considered this" line for the spec document and PPT rather than a build target.

**Why non-essential.** Gradient boosting already meets the accuracy and explainability bar with far less implementation risk under the timeline; this model class is intellectually the "more correct" choice but not the practical one for a hackathon build — see [`context.md` Part 4.3](./context.md#43-module-b--drift-prediction) for the full model comparison.

---

## N6 — STDF Ingestion Adapter

**What it is.** Support for reading **Standard Test Data Format (STDF)** files directly, alongside the primary CSV path — STDF is the real semiconductor industry's standard container format for automated test equipment data, storing lot/wafer/device-level parametric records.

**How to build it.**
1. Use an existing open-source STDF parser library to read lot, wafer, and device-level parametric records.
2. Map STDF's schema onto the system's internal lot/part schema (E7, E8).
3. Offer STDF upload as an alternative to CSV on the **Ingest** screen (E6, screen 2).

**Practicality.** Moderate — open-source parsers exist and do the hard part, so the remaining work is schema mapping, not format parsing from scratch.

**Why non-essential.** Demonstrates production-readiness and industry familiarity, but has limited demo value unless judges specifically probe integration readiness with real test equipment — CSV already satisfies the Software category's working-application bar.

---

## N7 — Auto-Generated PDF QA Report per Flagged Lot (Extended)

**What it is.** *Note: the core version of this feature was promoted to essential — see `essential-features.md` E9.* This entry covers the **extended** polish beyond the essential version: richer formatting, embedded trend charts (not just tables), a cover-page summary suitable for direct filing, and multi-lot batch report generation.

**How to build it.**
1. Extend E9's template with embedded matplotlib/Plotly chart images (predicted-vs-actual trajectories) rather than tables alone.
2. Add a one-page executive-summary cover sheet.
3. Support generating reports for multiple lots in one batch export.

**Practicality.** Low-to-moderate once E9 exists — this is refinement of an already-built template, not new architecture.

**Why non-essential.** The essential version (E9) already satisfies the real-world "data package" requirement identified in [`context.md` Part 5.3](./context.md#53-the-deliverable-is-a-document-not-a-screen); this entry is presentation polish on top of a feature that already works.

---

## N8 — Pre-Ingestion Dev Sandbox (Internal Tool, Not Shipped)

**What it is.** An editable grid over the synthetic generator's raw output, for quickly hand-crafting a specific test case while building Module A/B. **Decided as a private development tool, not a feature of the shipped application** — see [`context.md` Part 5.8](./context.md#58-a-pre-ingestion-data-sandbox--decided-as-a-private-dev-tool-deliberately-not-part-of-the-shipped-product) for the full reasoning behind removing it from the demoed product rather than including it, even attributed. **Independent of the shipped app's tech stack (`context.md` 7.13):** this stays a `streamlit` one-off script regardless of the FastAPI+React decision — it's never deployed, never seen by a judge, and adding it to the locked stack in `IMPLEMENTATION_PLAN.md` Part 3 would misstate it as part of the product. Whoever builds this installs `streamlit` locally, for this script only, not as a project dependency.

**How to build it (as a team script, not an app feature).**
1. Render the generator's output DataFrame with Streamlit's built-in editable-dataframe widget in a standalone local script, which shows a table and returns edited values on interaction ([`st.data_editor` documentation](https://docs.streamlit.io/library/advanced-features/dataframes)).
2. Feed the (possibly edited) DataFrame into Module A/B directly for fast iteration while developing — not through the shipped ingestion path (E7), and not deployed alongside the application judges see.

**Practicality.** Low. A few hours — `st.data_editor` does almost all of the work.

**Why kept, but explicitly out of the product.** The live-demo need this was originally meant to serve — showing the system react to a specific case — is already covered by E7's "load synthetic demo lot" path, using a complete, realistic file exactly as real ingestion would receive one. Keeping the editable version as a private tool preserves the fast-iteration benefit for the team at zero cost to the demoed product's fidelity to real ingestion, rather than trying to have one tool do both jobs.

---

## N9 — *Promoted to essential.* See `essential-features.md` E13.

**What this slot used to cover.** A confirmed-outcome field on past dispositions, plus a trend view — the visibility half of the feedback/CAPA loop. Once the decision was made to build both visibility *and* a corrective step (Part 5.17), there was no longer a partial version left for this document to own — the whole feature moved to essential as **E13**. This entry is kept, empty, so nothing else in either document that once pointed to "N9" resolves to a dead reference.

---

## N10 — Case-Based Retrieval: "Have We Seen This Before?"

**What it is.** A second, complementary explainability channel: given a newly flagged part, retrieve the most similar past flagged parts (by feature-vector distance, not raw values) and show their verdict, disposition, and confirmed outcome if known — a case-based supplement to the statistical explanations in E4.

**How to build it.**
1. Compute distance between a newly flagged part's feature vector (z-scores, Mahalanobis distance, drift rate — the same robust statistics already computed, not raw readings) and every past flagged part's feature vector, read from the latest `project_data` row per project (E11) — the storage gap this depended on is what E11's rewrite closed, and its later append-only correction (`context.md` Part 5.15) means retrieval always reads the most recent snapshot per project, not a stale one.
2. Surface the top 2–3 closest matches in Part Detail (E6, screen 4): part ID, lot, verdict, disposition, and confirmed outcome if E13 has one recorded for it.
3. Label unconfirmed matches as such explicitly ("previously flagged, outcome unconfirmed") rather than implying they were proven correct.

**Practicality.** Low-to-moderate once E11 exists — this is a k-nearest-neighbor lookup over already-computed, already-stored vectors, not a new model or new infrastructure. A few hours.

**Why non-essential, but grounded in a real technique, not a guess.** This isn't a novel idea being tried for the first time — it's an application of **Case-Based Reasoning applied to XAI (XCBR)**, a recognized explainability category built on the premise that a single statistical explanation is often insufficient on its own to build trust, and that similar-past-case retrieval is a natural, human-legible complement to it ([XCBR survey](https://discovery.ucl.ac.uk/10214905/1/Empowering_Explainable_Artificial_Intelligence_Through_Case-Based_Reasoning_A_Comprehensive_Exploration.pdf); [example-based explanations in XAI](https://zilliz.com/ai-faq/what-are-examplebased-explanations-in-explainable-ai)). It's non-essential because of a real cold-start limitation: a hackathon-scale demo won't have many past incidents to retrieve from early on — the same limitation already disclosed for Isolation Forest's cross-lot history (E2). Its value compounds with E13 (now essential), not on its own — see [`context.md` Part 4.5](./context.md#45-explainability) for the full reasoning.

---

## N11 — Analysis Run Comparison

**What it is.** A dedicated screen for browsing the full diff between any two analysis runs of a project, part by part — the interactive layer on top of data the essential tier already produces and stores, not what produces it.

**How to build it.**
1. A run-picker: select any two `project_data` rows for the same project (E11).
2. A side-by-side table: every part, its score/verdict under each run, changed rows highlighted.
3. Reuse the same diff computation E11 already runs at write time (`context.md` Part 5.15) — this screen visualizes stored data, it does not compute anything new.

**Practicality.** Low-to-moderate. The diff itself is free (already computed and stored by the essential tier); the work here is purely the comparison table's UI.

**Why non-essential.** The essential tier (E9's Analysis History, the History screen, and the Part Detail staleness note) already delivers the diff and the explanation everywhere it's needed for correctness and disclosure — see [`context.md` Part 5.15](./context.md#515-analysis-runs-must-be-append-only-too--and-what-what-changed-actually-needs-to-contain). This entry is a nicer way to browse that same information interactively, not a gap in what's already delivered.

---

## N12 — Tamper-Evident Hash-Chained Audit Log

**What it is.** An upgrade to E11's append-only event log: each entry carries a SHA-256 hash of the previous entry alongside its own content, so any historical tampering is detectable rather than merely discouraged by the append-only convention.

**How to build it.**
1. Each `events` row gets an additional `entry_hash` field: `SHA256(previous_entry_hash + canonicalized_json(this_entry))`. Canonicalize (sorted keys, fixed float formatting) before hashing — an uncanonicalized payload is the classic way this kind of chain silently breaks on serialization differences alone, not on real tampering.
2. A genesis entry (fixed, known hash) seeds the chain at database initialization.
3. A `verify()` function walks the chain and reports the first entry whose stored hash doesn't match a fresh recomputation — runnable from a CLI or an admin view, not part of the normal request path.

**Practicality.** Low. A single additional column, one hash computation per write, and a verification script — a few hours on top of E11's already-built append-only design.

**Why non-essential, but worth doing if time allows.** E11's append-only rule already provides *procedural* tamper-resistance — nothing in the application's normal operation can edit a past entry. A hash chain adds *cryptographic* tamper-*evidence* — proof that no row was altered outside the application either, e.g. by direct database access. This is a real, meaningful step up in rigor, but it protects against a threat model (direct database tampering) that isn't what any of the three graded criteria measure, which is why it stays a stretch item rather than essential scope, even though it's cheap.

---

## N13 — Self-Monitoring: Vendor Shift vs. Model Staleness

**What it is.** A drift-detection layer comparing the feature distribution of incoming lots against the distribution the shipped model was trained on, distinguishing a genuine shift at one manufacturer from the model simply going stale over time.

**How to build it.**
1. Store a summary of the training-time feature distribution alongside each model version (E11's `project_data`/model metadata).
2. On each new lot, compute the **Population Stability Index (PSI)** between the incoming distribution and the stored training-time baseline — a standard, well-established drift metric with established thresholds (<0.1 stable, 0.1–0.25 minor shift, >0.25 significant — [reference](https://futureagi.com/glossary/population-stability-index-psi)), plus a KS-test as a second opinion.
3. **The distinguishing step, and the actual differentiator**: condition the comparison on manufacturer/date-code metadata (already captured at ingestion, E7). A shift confined to one manufacturer or date-code range is a **vendor process shift** — real, actionable procurement intelligence, not a system fault. A shift present across all sources is **model staleness** — a signal the shipped model needs review.
4. Surface either finding as a status, never an automatic retrain — same human-authorized-decision principle as E13's corrective step (`context.md` Part 5.2).

**Practicality.** Moderate. The PSI/KS computation itself is a few lines; the metadata-conditioned distinction that makes this useful rather than a generic drift alarm needs its own test design.

**Why non-essential, but a real, previously-identified gap.** This closes a blind spot named earlier in this project's own review process — that the system has no mechanism to notice its own model going stale over time — with a concrete, standard technique rather than leaving it as an acknowledged but unaddressed limitation. Not built by default because it protects against a long-horizon deployment concern, not something a hackathon-scale demo can meaningfully exercise or that the three graded criteria measure directly.

---

## Explicitly excluded, not merely deprioritized

Three categories of work were evaluated and ruled out by evidence, not left off by default — they do not belong on this stretch list at all, and should not be picked up even with extra time, unless new evidence changes the picture:

- **Time-series foundation models** (e.g., Chronos, TimesFM) for Module B — ruled out on a structural context-length mismatch that persists regardless of available time or data volume. See [`context.md` Part 4.3](./context.md#43-module-b--drift-prediction).
- **A deep neural network trained from scratch** for Module A or B — the evidence gathered specifically favors classical/shallow methods in this low-dimensional, small-sample data regime; more build time would not change that underlying data-shape argument. See [`context.md` Part 4.7](./context.md#47-why-this-is-a-statisticalsmall-sample-ml-task-not-a-deep-learning-task).
- **An LLM synthesizing explanations into natural language** — considered specifically as a possible enhancement to N10/E4, ruled out for the live system: it adds a network dependency to an otherwise-standalone pipeline for marginal benefit over a well-written template, and any generative step near the explanation path risks presenting an unverified detail as fact in a safety-critical tool. See [`context.md` Part 4.5](./context.md#45-explainability).
- **Kernel density estimation (KDE) as a fourth Module A detector** — considered on the theory that MCD's elliptical assumption might miss multi-modal defect patterns, then ruled out on reflection: MCD only needs the *healthy* population to be well-estimated, which our lognormal-per-lot generator design already satisfies, so the specific scenario KDE would help with doesn't clearly apply; KDE also has no clean per-feature explanation and its own reliability is borderline at exactly 3 dimensions. See [`context.md` Part 4.2](./context.md#42-module-a--outlier-detection).
