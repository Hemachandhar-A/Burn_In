# Solution overview: from raw data to a decision, and the scoring decision

Written 2026-10-04, before Session I2b. Tags: **[S]** spec, **[M]** measured by an agent on **synthetic** data, **[V]** arithmetic re-done by the assistant, **[J]** judgement, **[U]** unknown. Detail and evidence: `SCORING_COMPARISON.md`, `DECISION_RECORD_DETECTION_APPROACH.md`, `SESSION_DECISIONS.md`.

## 1. The decision

**Use the new scoring (V1F: absolute tail probabilities) as the default in the shipped system, replacing the old percentile scoring, provided Session I2b's gate passes. If the gate fails, stay on the old scoring and tag `demo-v1.2` stays the submission.** Today the shipped, verified build is `demo-v1.2`, which still uses the old scoring.

Why the new scoring (measured, pre-registered, separate seeds, synthetic) **[M]**:
- Published protocol, Module A alone: cost per part 0.082 [0.069, 0.096] against 0.239 for the old scoring; flag rate 0.090 against 0.183; recall 0.923 against 0.814.
- Clean (defect-free) lots: about 4% of parts flagged (at most 0.044 for lots of 30 to 150 parts) against 18.6%.
- Every family is cheaper under the new scoring; the old scoring never leads under any weighting in the decision matrix (0 to 1.2% first place).

Why the old scoring has this flaw **[D][V]**: a percentile threshold flags a fixed share of every lot by construction (REVIEW 4.44%, REJECT 3.57% = 1 in 28 of the scores), so clean lots are flagged whatever they look like. A detector beats "flag nothing" only if prevalence exceeds α/(10r + α): about 2.4% for the old scoring against about 0.5% for the new one.

What this decision does **not** claim: that Module A or the system beats the industry baselines (a cost-tuned fixed delta costs 0.031 against 0.082 on synthetic data; a tuned dynamic PAT ties), that severity is a probability (the p-values are uncalibrated; it is an index), or that anything works on real data (untested).

## 2. The solution from start to end

**Stage 0 - Data (offline, no dataset was provided [S]).** A synthetic generator, grounded in published physics: lognormal baselines nested lot to die; healthy drift as a power law t^n with n in 0.15 to 0.30; Arrhenius-activated defects (1 to 8% prevalence, shared severity factor); 77 parts per lot (the zero-failure sample-size derivation); checkpoints 0h, 24h, 96h, 168h; three parameters (Iddq, leakage, propagation delay); tester offsets and quantisation. Checked against two published experiments with KS tests (two pass, two marginal, two documented divergences, notably the noise level); five held-out generator families; ground-truth labels kept in a sidecar the models never see.

**Stage 1 - Ingest.** A user uploads a CSV (long or wide layout) through the web app. Validation: non-finite values and invalid lot ids are rejected (HTTP 422); units are normalised to canonical units (leakage to nA); missing 0h or 24h data is listed as insufficient data; a missing 96h is allowed and flagged. A lot with 0h and 24h is IN_PROGRESS; later checkpoint files merge into it; with all checkpoints it is COMPLETE. Every analysis run stores the full dataset, so a lot can be rebuilt after a restart.

**Stage 2 - Features.** Per parameter and checkpoint: robust median and sigma (IQR/1.35, the AEC-Q001 statistic), robust z-scores, deltas between checkpoints, a joint vector for the multivariate detector. Lots of fewer than 30 parts need a pooled reference (specified, not wired live).

**Stage 3 - Module A (screens a finished lot).** Detectors compare each part with its own lot.
- *Old scoring:* each detector's raw score becomes a percentile within the lot; the maximum is the severity; flag at percentile 0.9556 (REVIEW) or 0.9643 (REJECT).
- *New scoring (V1F):* z-score and MCD distance (MCD only for 77 or more parts) become tail probabilities; severity s = -log10 p; maximum; flag at s of 2.956 (REVIEW) or 3.419 (REJECT), about 3.3 and 3.6 sigma for the z-score leg.
- The isolation forest (needs earlier lots) and ECOD (needs a reference) contribute no live score. A REJECT may not rest solely on them (the explainability gate, which therefore cannot trigger on them now); a below-median direction cap also applies.

**Stage 4 - Module B (forecasts an unfinished lot).** Gradient boosting (LightGBM) with conformalised quantile intervals predicts the 168h value from 0h, 24h (and 96h); the "safety slope" is the calibrated 0.95 quantile of healthy drift per hour (the problem statement's one undefined term). A physics power-law baseline provides a second, disagreement signal. An out-of-range guard declines inputs on an unfamiliar scale and says so (known hole at exactly 10x). TreeSHAP gives the drivers.

**Stage 5 - Fusion.** Per part: PASS, WATCH or REJECT (REJECT if either module crosses REJECT). Per lot: forecast verdicts LOT_ON_TRACK, LOT_AT_RISK, STOP_RUN_RECOMMENDED for unfinished lots; ACCEPT, HOLD, REJECT for finished lots using the Percent Defective Allowable (5%). A finished lot with parts never analysed is never ACCEPT. Parts are ranked per module (rank 1 = most severe).

**Stage 6 - Explanation (judged criterion 3).** Computed at analysis time and stored: a sentence with real numbers and units ("leakage at 0h is 15.8 robust-sigma above lot median (median = 10 uA, value = 45 uA)"), a confidence qualifier, a z-score table, MCD, ECOD and SHAP views, a trajectory chart, and notes (severity cap, unavailable forecast, staleness); a one-line lot summary.

**Stage 7 - Human decision.** Two seeded accounts log in (JWT). Accept, Hold or Reject each need a written rationale; a REJECT needs two distinct accounts (status: awaiting second sign-off, then final, or conflict); a timing flag if two sign-offs land within two minutes; records are immutable and written under a lock; everything lands in an audit history.

**Stage 8 - Feedback loop.** Confirmed outcomes (good, defective, unknown) are recorded; false-negative and false-positive rates are computed separately; the corrective status stays INSUFFICIENT_DATA below 10 confirmed outcomes and compares the false-negative rate with a ceiling (default 5%). A worklist lists dispositions still waiting for an outcome. The three thresholds (FN:FP ratio 10, PDA threshold 5%, FN ceiling 5%) change only through a two-account sign-off.

**Stage 9 - Outputs.** A DPA work order (up to three parts: highest severity, most uncertain near the boundary, one control); a PDF report with a methodology paragraph and units; seven screens (Login, Ingest, Project Browser, Lot Dashboard, Part Detail, History, Settings).

**Stage 10 - Platform and evidence.** FastAPI, SQLite and a React front end served by one process (`bash scripts/build_demo.sh`, about 60 s); all routes except health and login require a token; about 2,000 automated tests and a scripted 14-step rehearsal run twice from a fresh clone of `main`; benchmark against static limits, fixed delta limits, static PAT and dynamic PAT, a sensitivity sweep, and pre-registered experiments; tags `demo-v1.1` and `demo-v1.2` (current submission candidate).

## 3. What is verified and what is not

| Verified (agents, synthetic data) | Not verified |
|---|---|
| Cost, recall and flag-rate figures with CIs; clean-lot flag rates by lot size; sweep verdicts; guard false-block rates; rehearsals | Anything on real burn-in data |
| The cost model reproduces all six published benchmark rows (assistant arithmetic) | The fused system (A + B) against the baselines (to be measured first in I2b) |
| Replacing the old scoring is robust under every weighting tried | Whether a cost-tuned fixed delta beats the system once Module B is counted |
| | Calibration of the new p-values (they are an index) |
| | Behaviour on lot-wide drift (the generator has none) |

## 4. What Session I2b does

(1) Measures the fused system against the tuned baselines and applies a gate (the new scoring must not be worse than the old one at system level); (2) if the gate holds, makes the new scoring the default and repairs the six tests that depended on the old numbers; (3) fixes the explanation views that no longer match the score (MCD below 77 parts, ECOD); (4) re-picks two demo seeds; (5) rewrites the claims and disclosures; (6) rehearses twice from a fresh clone of `main` and tags `demo-v2`. `demo-v1.2` stays as the fallback.
