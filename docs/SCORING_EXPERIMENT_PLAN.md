# Module A scoring experiment: pre-registration (session S6X)

Written and committed BEFORE any variant is run. Later changes go in the "Deviations" section at the end, appended,
never edited in place. This session changes NO shipped behaviour: every new option defaults to today's behaviour,
nothing is wired into `fusion/`, and the default benchmark output must stay byte-identical.

Machine: Windows 11 Home (10.0.26100), Python 3.11.17, uv 0.12.22. Repo base: tag `demo-v1.1` (700ac73), branch
`scoring-experiment`, worktree `../burnin-scoring`. The only run before this document was written: the golden test
(4 passed) and the default `scripts.evaluate` (the "defaults unchanged" baseline).

## 0. Question

In the live configuration (Isolation Forest inactive) Module A at REVIEW flags 18% of parts whatever the generator
setting (sensitivity sweep, `docs/EVIDENCE_MEASUREMENTS.md`), and at 1% prevalence its cost (0.173) is worse than static
limits (0.108). Hypothesis (to be verified, not assumed): each detector's raw score is turned into a rank-percentile
WITHIN the lot (`module_a/detect.py`, `_pct`: `rankdata(arr) / n`), so the top slice of every lot looks extreme even when
the lot is clean. Does a different score calibration and/or combination rule remove the flag-rate floor without losing
the recall advantage, and is any variant justified for real use?

## 1. Orientation facts (Part 0c), with where they live

* Per-detector raw scores (`module_a/detect.py::_detect_single_lot`): robust z = `abs(max(f.robust_z.values(), key=abs))`
  (worst checkpoint; `robust_z` = (x - lot median at the checkpoint) / (IQR/1.35), `features/compute.py::_robust_stats`);
  MCD = `sqrt` of `MinCovDet(random_state=42).mahalanobis`, fitted per checkpoint on the lot's per-component robust-z
  matrix (columns = parameters, so 3 dimensions), kept as the MAX over checkpoints, only when lot_size >= 30; ECOD =
  PyOD `ECOD(contamination=0.1).decision_scores_`, fitted per parameter on the lot's `[value_0h, value_24h]` matrix.
* Conversion to a within-lot rank percentile: `_pct(arr) = rankdata(arr) / n` over ALL frames (component x parameter) of
  the lot; absent detectors are all 0.0 and so rank to about 0.5.
* Combination: `np.maximum.reduce` over the four detector percentiles (frame level); a part's score is its worst
  parameter's (`harness/scoring.py::part_detector_scores`).
* Tiers: `config/harness_thresholds.yaml` (loaded as `HarnessThresholds`): REVIEW 0.9556, REJECT 0.9643 (percentile
  scale). `combined >= reject` -> REJECT (below-median direction capped to REVIEW), `>= review` -> REVIEW, else PASS.
* Threshold tuning (`harness/bakeoff.py::derive_thresholds`, `harness/scoring.py::tune_threshold`): cost-sensitive search,
  REJECT at FN:FP 10:1, REVIEW at 20:1. **The shipped thresholds were tuned on seed 2026 over the five held-out
  families pooled, i.e. on the same parts the published benchmark (`harness/results/p18`) then evaluates.** So the
  published Module A numbers are in-sample for the thresholds. That is a pre-existing limitation, not corrected here,
  and it is the reason this experiment uses a separate tuning side.
* **Tuning vs held-out separation (written down so it cannot drift).** Both sides use all five generator families but
  disjoint, independently seeded lots:

  | side | seed | lot ids | lots per family | used for |
  |---|---|---|---|---|
  | TUNING | 6101 | `SC-TUNE-<family>-<i>` | 100 | thresholds (REVIEW 20:1, REJECT 10:1) of every variant, and the frozen ECOD anchor (below) |
  | EVALUATION | 6202 | `SC-EVAL-<family>-<i>` | 150 | every reported headline number |
  | CLEAN (P1) | 6404 | `SC-CLEAN-<family>-<i>` | 40 | P1 clean-lot flag rate (prevalence 0) |
  | ROBUSTNESS | 6303 | `SC-ROB-<setting>-<i>` | 150 | prevalence 1%, 3% and noise x2 on the baseline family (settings copied from `scripts/sensitivity.py`) |

  Seeds 6101/6202/6303/6404 differ from the harness seed 2026 (shipped thresholds), 5101 (sensitivity), 7001
  (Module B MAE) and 0..13 (Module B training). Lots are a pure function of (seed, lot id, part number)
  (`generator/lot.py::_lot_seed`), so the sides are disjoint by construction. The code asserts that no lot id and no
  (seed, id) pair appears on two sides. Thresholds are written to a file by the tuning step; the evaluation step reads
  the file and never calls the tuner. Fixed-size lots are used, not the archetype-minimum sets of `harness/held_out.py`,
  so every variant sees exactly the same number of lots. A secondary check re-tunes leaving one FAMILY out (tune on
  the other four families' tuning lots, evaluate on the left-out family's evaluation lots); it is reported as S6,
  informational, not a gate.

## 2. Variants (all use the live detector set: robust z, MCD, ECOD; no Isolation Forest)

### Stage A: calibration of each detector's score into a comparable severity

* **V0, rank-percentile within the lot (today; the control).** Mechanism: severity = the part's rank share inside its own
  lot, so a fixed share of every lot is "top" by construction, and nothing can say "this whole lot is clean".
  Failure mode: a floor on the flag rate that no threshold tuning can remove; the cost-optimal threshold lands where the
  genuinely defective parts sit, which in a clean lot still flags the top slice. V0 is reported twice: with the shipped
  thresholds ("today") and re-tuned on the tuning side (the like-for-like control for S3 and S5).
* **V1, absolute, assumption-based.** severity = -log10(p).
  * z: two-sided normal tail, p = 2(1 - Phi(|z|)).
  * MCD: p = chi-square upper tail of the squared Mahalanobis distance with df = number of dimensions in that checkpoint's
    matrix (the 3 parameters); p is computed per checkpoint and the smallest p kept (equivalent to the existing max
    over checkpoints when df is constant). Small-sample caveat: MinCovDet's reweighted distances on a lot of 77 parts in
    3 dimensions are only approximately chi-square (the finite-sample correction is not exact), and robust z scalars
    use the worst of up to four checkpoints, so p is slightly optimistic by a small multiple (not corrected).
  * ECOD: the analytic mapping (null of a sum of independent tail terms) is NOT used, decided now, because (i) its two
    dimensions are the 0h and 24h readings of one parameter, strongly positively correlated, so the terms are not
    independent, and (ii) the ECDF is the lot's own, so the most extreme part of ANY lot scores about d*log(n)
    whatever its distance: the score saturates with lot size and an absolute probability cannot recover magnitude.
    Per the brief this triggers the fallback: ECOD is mapped by the conformal p-value of V2 against a FROZEN anchor
    (the ECOD scores of the first 8 TUNING-side lots of the same family, per parameter). This makes V1 not fully
    assumption-based: its ECOD leg needs a shipped reference table. Recorded as a limitation, not hidden. If the anchor
    holds fewer than N_min reference parts, ECOD is left out of V1 for that lot and the fact is reported.
  Mechanism: a normal-tail / chi-square p needs no history and does not depend on how the rest of the lot looks, so a clean
  lot has few small p's. Failure mode: it assumes Gaussian healthy parts; the heavy-tailed noise family and lognormal-like
  parameters (leakage, iddq) will produce small p's for healthy parts (false alarms), which tuning can only trade off.
* **V2, reference-calibrated (conformal p-value).** p = (1 + #{reference scores >= the part's score}) / (1 + N_ref), the
  reference being the pooled raw scores of the K EARLIER lots of the same family, current lot excluded (same history
  semantics as `max_history` in `harness/scoring.py` on branch `evidence-measurements`; copied, not depended on). Per
  detector: z and ECOD per parameter, MCD per component. The reference is unlabeled and contaminated by whatever defects
  those lots held, as in real use. Cold start: fewer than `N_min = 300` reference PARTS (unique components) -> that
  detector falls back to V1 for that lot. Evaluated at K = 2, 5 and 10. Lots have 77 parts, so K = 2 (154 parts) can
  never reach N_min and is identical to V1 by the cold-start rule (reported, kept in the table for completeness); K = 5
  reaches N_min once 4 earlier lots exist (308 parts). Mechanism: no distribution assumption, and a clean lot's top
  part is only as extreme as the reference says it should be. Failure mode: needs history; a customer's first lots are
  V1; the history must come from the same process (a process shift makes the reference stale); severity saturates at
  log10(1 + N_ref), so it cannot rank extreme parts against each other.

### Stage B: combination, using the winning calibration from Stage A (C0 fixed during Stage A)

* **C0, maximum** of the detector severities (today). Maximises recall; the false-alarm probabilities of the three
  detectors add up (union bound). Failure: more detectors = more false alarms.
* **C1, mean** of the AVAILABLE detectors' severities, equal weights, no learned weights. Cancels independent noise.
  Failure: can average away a defect that exactly one detector sees (z sees a level shift, MCD a joint shift, ECOD a
  tail the others miss), the opposite of the problem statement's "inside limits but anomalous" case.
* **C2, hybrid:** C1's mean, plus an override: if any single detector's p <= 1e-4 (severity >= 4) the part is at least
  REVIEW regardless of the mean. Tries both. Mechanical fact recorded in advance: under V2 the smallest reachable p is
  1/(1 + N_ref), which exceeds 1e-4 for every K tested here (N_ref <= ~2,300 frames), so the override CANNOT fire
  under V2 and C2 would equal C1 there; it can fire under V1. If V2 wins Stage A, C2 is run anyway and reported as such.

If the Stage-A winner is V0 (rank), only C0 is defined (rank percentiles have no probability for the override, and the
mean of percentiles is not part of the brief); Stage B is then reported as not applicable.

Out of scope: the supervised meta-model (needs labels a deployment lacks).

## 3. Mechanism (property) tests, written as unit tests BEFORE the benchmark runs; applied to every variant

* **P1 clean-lot flag rate.** On generated lots with NO defective parts (generator prevalence range (0, 0), supported),
  the share of parts at or above REVIEW is at most 5% for V1/V2 variants (V0 expected to fail: its value is recorded).
  Formal value: measured in the experiment script on the CLEAN side with the TUNED REVIEW threshold. V2's clean-lot
  history is the earlier clean lots of the same sequence. A unit-test version uses an a-priori severity cutoff of 3.0
  (p <= 1e-3) on a small baseline-family clean sample, so the test does not depend on tuning. Consequence accepted in
  advance: the tuned REVIEW threshold optimises cost, not flag rate, so a variant can fail P1 at its tuned threshold
  even if its scores are well calibrated; S1 is then FAIL for that variant and that is the reported result.
* **P2** a planted large outlier (the golden fixture's GOLDEN-045 pattern: median 10 uA, a part at 45 uA, limit 50) is
  still at REJECT. Unit test: golden part has the maximum severity of its lot and at least severity 4.0 (p <= 1e-4)
  for V1/V2-cold-start; script: severity >= the tuned REJECT threshold.
* **P3 monotonicity:** increasing an outlier's deviation never lowers its severity (non-decreasing over a ladder of
  deviations).
* **P4 scale invariance:** multiplying all values of one parameter by a constant leaves severities unchanged
  (tolerance 1e-6).
* **P5 permutation invariance:** shuffling the order of parts leaves each part's severity unchanged (tolerance 1e-6).
  `MinCovDet` draws random subsets whose composition can depend on row order; if that causes failures it is a finding
  about the existing detector, recorded with the observed max absolute difference as a deviation entry, not hidden by
  loosening the tolerance silently.

## 4. Thresholds

For every variant REVIEW (FN:FP 20:1) and REJECT (10:1) are re-tuned with the repo's own `harness.scoring.tune_threshold`
(the cost-sensitive optimiser, unchanged) on the TUNING side only, parts pooled over the five families, V2 evaluated
sequentially so its reference is the earlier tuning lots. No hand tuning. For C2, REVIEW flags `(score >= T) or override`;
T is tuned over the parts the override did not already flag (their cost is constant in T). REJECT is tuned on the
score alone and reported pre-cap, as in `harness/comparison.py`.

## 5. Evaluation

Live configuration, EVALUATION side, thresholds read from the tuned file and fixed. Per variant and for the baselines
(static limits, fixed delta, static PAT, dynamic PAT, with their published operating points): headline table at REVIEW
and REJECT: flag rate, recall, precision, false alarms, missed, cost per part (FN:FP 10:1, as `harness/comparison.py`),
with 95% bootstrap CIs over lots (1000 resamples of whole lots, seed 20261003). 150 lots per family, five families, the
same lots for every variant. Per-family cost is reported for S5.

Robustness (finalists only): the finalists are V0 re-tuned (control), the variant selected in Stage B, and the Stage-A
winner if different; plus static limits as the S4 comparator. Run at defect prevalence 1% and 3% and at noise x2, baseline
family, 150 lots each, thresholds FIXED at the nominal tuning-side values.

## 6. Success criteria for adopting a variant (all must hold, otherwise: keep the current scoring and disclose)

* S1 P1 to P5 pass.
* S2 held-out recall at REVIEW >= 0.75.
* S3 held-out cost per part at REVIEW <= 0.22 (today 0.239; DPAT 0.219).
* S4 at 1% prevalence the cost per part at REVIEW <= that of static limits at 1% prevalence.
* S5 no held-out family has a cost at REVIEW more than 0.03 higher than under V0 (re-tuned V0, same protocol; the
  comparison against shipped-threshold V0 is also printed).
* S6 (informational) the same S2 to S5 under leave-one-family-out thresholds.

Selection rule: among variants meeting S1 to S5, the lowest held-out cost at REVIEW; two costs within 0.005 are a tie,
and a tie goes to the simpler variant (simplicity order: V0 < V1 < V2 with larger K < V2 with smaller K, where K=2 is
V1 by the cold-start rule; C0 < C1 < C2). Stage A winner is chosen with C0 fixed; Stage B uses that winner. If NO Stage-A variant meets S1 to S5,
Stage B still runs on the lowest-cost variant that passes S1 (else the lowest-cost non-V0 variant), labelled "best, not
passing", and the verdict is decided by S1 to S5 as written. All variants, losers included, are reported.

## 7. Stop conditions

Golden test fails; default output changes; the tuning protocol cannot be separated from the evaluation families (it can:
section 1); or a variant would need a change outside the allowed files.

## 8. Allowed edits

`module_a/` (optional `scoring` argument, default = today's behaviour exactly), `harness/` (optional parameters),
`scripts/`, `tests/unit/{module_a,harness,scripts}`, `docs/`. Not touched: `fusion/`, `frontend/`, `api/`, `storage/`,
`identity/`, `capa/`, `explain/`, `report/`, `contracts.py`.

## Deviations (append only)

