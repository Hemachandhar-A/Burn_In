# Scoring comparison: current (percentile + max) vs V1 (absolute calibration + max)

Recorded 2026-10-04. Repository state when written: main = `e1c249b`, tag `demo-v1.2`. V1 exists only as an off-by-default switch (branch `scoring-experiment`, merged into main with the default unchanged).

## How to read this document

Every statement carries one of these evidence tags. Nothing is stated without one.

| Tag | Meaning | How much to trust it |
|---|---|---|
| **[S]** | Written in the project spec (`context.md`) | As reliable as the spec |
| **[V]** | Arithmetic I re-did on published numbers | Exact; anyone can repeat it |
| **[D]** | Mathematical derivation under stated assumptions | Exact if the assumptions hold |
| **[M]** | Measured by an agent run on **synthetic** data and reported to me | Real measurements, but I have not re-run them and they come from our own generator |
| **[L]** | Published literature, found by search | Only for the point it supports |
| **[U]** | Unknown / not yet tested | No claim made |

I have not read the code. Anything about how the code works comes from the spec or the agents' reports.

---

## 1. The two flows

| | Current | V1 |
|---|---|---|
| Per-detector score | Percentile rank of the raw score **among the lot's scores** | Absolute tail probability `p`: z-score → normal tail; MCD squared distance → chi-square tail (df = dimensions used) |
| Combination | Maximum over detectors | Maximum over detectors (unchanged) |
| Severity | Percentile in [0, 1] | `s = -log10(p)` |
| REVIEW threshold | percentile 0.955628 (disclosed 20:1 judgement call) **[S]** | `s = 2.956`, i.e. `p ≈ 1.1×10⁻³` (about 1 in 904) **[V]** |
| REJECT threshold | percentile 0.964286 (locked 10:1) **[S]**, which is exactly 27/28 **[V]** | `s = 3.419`, i.e. `p ≈ 3.8×10⁻⁴` (about 1 in 2,624) **[V]** |
| Source of thresholds | cost-sensitive search on the shipped families | repo's cost-sensitive optimizer on tuning seed 6101 only **[M]** |

Sources: current flow `context.md` 6.1 and lines 588–589 **[S]**; V1 `module_a/scoring.py` and `docs/SCORING_EXPERIMENT_RESULT.md` **[M]**.

**The combination rule is not what differs.** The spec chose the maximum on purpose: a miss is catastrophic, and no detector may suppress another **[S]** (6.1). The documented E5 bake-off gave max 0.344, weighted average 0.191, meta-model 0.146 cost per part; max was shipped because the meta-model's fitted ECOD coefficient was negative (−7.7), which violates no-suppression, and a weighted average leaves the "which detector alone drove the score" gate undefined **[S]** (line 588). Under absolute calibration the experiment also found mean-combination worse than max (clean-lot flag rate 7.4%, cost 0.119 vs 0.096) **[M]**.

---

## 2. The cost model (verified)

The benchmark's cost per part at the locked FN:FP ratio of 10:1 is

> **C = (10·FN + FP) / N**, where FN = missed defects, FP = false alarms, N = parts.

**[V] Check against the published benchmark** (N = 9,779 held-out parts, 521 defective, prevalence 5.33%):

| Method | Flagged | False alarms | Missed | TP + missed | (10·missed + FA)/N | Reported cost |
|---|---|---|---|---|---|---|
| Static limits | 21 | 0 | 500 | 521 ✓ | 0.5113 | 0.511 |
| Fixed delta | 2,344 | 1,823 | 0 | 521 ✓ | 0.1864 | 0.186 |
| Static PAT | 666 | 433 | 288 | 521 ✓ | 0.3388 | 0.339 |
| Dynamic PAT | 317 | 9 | 213 | 521 ✓ | 0.2187 | 0.219 |
| Module A, REVIEW | 2,378 | 1,940 | 83 | 521 ✓ | 0.2833 | 0.283 |
| Module A, REJECT | 1,998 | 1,588 | 111 | 521 ✓ | 0.2759 | 0.276 |

All six rows reproduce, and each row's true positives plus missed defects equal exactly 521. So the cost model is the one the benchmark uses, and the published table is internally consistent.

Writing π for prevalence, r for recall and α for the false-alarm rate on healthy parts:

> **C = 10·π·(1 − r) + (1 − π)·α**   **[D]**

---

## 3. Result 1: the cost-optimal rule is "flag when P(defect) > 1/11"

**[D]** For one part with posterior defect probability q, flagging costs `(1 − q)·1` (a false alarm if healthy) and not flagging costs `q·10` (a miss if defective). Flag when `10q > 1 − q`, i.e.

> **q > 1/11 ≈ 0.0909**

This holds for any detector. It says the threshold must act on a quantity that **means the same thing in every lot**: how likely this part is to be defective given the evidence. The prevalence enters the posterior, so the optimal cut in a score depends on π, but the *meaning* of the score must not depend on what else is in the lot.

---

## 4. Result 2: a detector beats "flag nothing" only above a break-even prevalence

**[D]** Flagging nothing costs `10π`. A detector with recall r and healthy-part false-alarm rate α costs `10π(1 − r) + (1 − π)α`. It is cheaper than doing nothing iff

> `(1 − π)·α < 10·π·r`  ⟺  **π > α / (10·r + α)**

Equivalently its precision must exceed 1/11 (9.09%).

| Flow | α (clean-lot flag rate) **[M]** | r (held-out recall) **[M]** | Break-even prevalence |
|---|---|---|---|
| Current | 0.186 | 0.741 (0.90 gives 2.0%) | **2.4%** |
| V1 | 0.048 | 0.913 | **0.52%** |

**[V] Consistency with the sensitivity sweep.** At 1% prevalence the current flow's predicted cost is `0.10(1 − r) + 0.99·α`, which is 0.17–0.21 for r in 0.78–0.98 and α in 0.17–0.186. The sweep reported **0.173** at REVIEW, against 0.100 for doing nothing and 0.108 for static limits. Both the prediction and the sweep put Module A above "flag nothing" at 1% (below its 2.4% break-even), and the sweep found Module A cheaper than static limits at 3% prevalence, above the break-even. V1's predicted cost at 1% is 0.05–0.07 and the scoring experiment measured **0.048** [M].

This is a consequence, not a tuning accident: **while α stays near 18%, the current flow cannot beat "flag nothing" in any lot with prevalence below about 2.4%.**

---

## 5. Result 3: what a percentile threshold does

**Assumption, not verified in code [U]:** the percentile is computed among the lot's own scores (the scoring-experiment agent described it as "rank-percentile within the lot", and the clean-lot measurement agrees). The spec's note that the maximum score is a grid of about 47 distinct values above 0.90, roughly 0.0022 apart **[S]**, means roughly 455 rank levels, which suggests ranks over a pooled set of the lot's scores (for example 77 parts × 6 scores = 462), not 77. The argument below holds for either; only the count K of scores changes.

**[D]** Let u be a score's percentile rank. Over the scores of a lot, the ranks are uniformly spread by construction, whatever the values are. A threshold at percentile τ therefore flags a **fixed share 1 − τ of those scores**, in a clean lot and a contaminated lot alike. With K scores per part entering the maximum, the fraction of *parts* flagged lies between (1 − τ) and min(1, K·(1 − τ)).

| Threshold | Share of scores flagged | Part range if K = 9 (assumption; K not confirmed for V1) |
|---|---|---|
| REVIEW, τ = 0.955628 | 4.44% (1 in 22.5) | 4.4% to 39.9% |
| REJECT, τ = 0.964286 | 3.57% (1 in 28) | 3.6% to 32.1% |

**[M]** The measured clean-lot flag rate under the shipped REVIEW threshold is 18.6%, inside that range. Detector choice and correlations decide where; the floor itself is built into the percentile.

**[M]** Re-tuning the percentile threshold with the cost optimizer does not remove it: the re-tuned current flow flags **34.3%** of clean lots (REVIEW 0.899, REJECT 0.934) and costs 0.329. The optimizer prefers to flag more, because a rank cannot separate "extreme" from "merely top of this lot".

A rank is also lot-relative in the other direction: a part with the same absolute deviation gets a lower percentile in a lot with many defects. The threshold therefore does not mean "defective with probability q" in any fixed sense, which Result 1 requires.

---

## 6. Result 4: what an absolute probability threshold guarantees, and what it does not

**[D]** If a healthy part's score has the assumed null distribution, its p-value is Uniform(0, 1), so `P(p < ε) = ε` for every lot, whatever its size or contamination (probability integral transform). With K scores in the maximum, the union bound gives

> **α ≤ K·ε**

| Threshold | ε | α ≤ K·ε with K = 16 (confirmed in Session I2a, see §11) |
|---|---|---|
| REVIEW, s = 2.956 | 1.107×10⁻³ | α ≤ 0.0177 (about 1.8%) |
| REJECT, s = 3.419 | 3.81×10⁻⁴ | α ≤ 0.0061 (about 0.6%) |

The false-alarm rate is **controlled by the threshold, not by the lot**, which is what the percentile cannot do.

**[M] Observed clean-lot flag rate for V1 is 4.8%** in the scoring experiment (V1-C2: 2.1%) and 4.2% through the app at 77 parts (§11). With K = 16 the nominal bound is about 1.8%, so the bound is exceeded about 2.4-fold. So V1 is **better calibrated than the percentile, not exactly calibrated** (superseded wording in an earlier draft assumed K = 9 and a fivefold excess; K = 16 was confirmed afterwards). Known reasons the null is not exact:

- The robust z-score uses a scale estimated from the same lot (IQR/1.35 **[S]**), which makes the statistic heavier-tailed than a normal for modest n. I have not measured the size of this effect **[U]**.
- **[L]** The chi-square approximation to MCD robust distances is known to be poor, even in quite large samples, and leads to too many outliers being nominated; Hardin & Rocke (2005) give an improved F approximation (J. Computational and Graphical Statistics 14:928–946). The direction (more flags than nominal) agrees with our observation. The magnitude for our case is not established.
- Heavy-tailed noise breaks the Gaussian null. **[M]** The heavy-tailed-noise family already shows a 6.7% clean-lot flag rate under V1.

---

## 7. Record of every comparison made

All numbers below are **[M]** (agent-reported, synthetic data) unless marked otherwise.

### 7.1 Published benchmark (Isolation Forest active). N = 9,779, 521 defective. Source `harness/results/p18/comparison.md`

| Method | Flag rate | Recall | Precision | Cost/part |
|---|---|---|---|---|
| Static limits | 0.002 | 0.040 | 1.000 | 0.511 |
| Fixed delta | 0.240 | 1.000 | 0.222 | **0.186** |
| Static PAT | 0.068 | 0.447 | 0.350 | 0.339 |
| Dynamic PAT | 0.032 | 0.591 | 0.972 | 0.219 |
| Module A, REVIEW | 0.243 | 0.841 | 0.184 | 0.283 |
| Module A, REJECT | 0.204 | 0.787 | 0.205 | 0.276 |

Module A recall at the same flag budget: 0.307 vs dynamic PAT 0.591 and 0.833 vs fixed delta 1.000. The fixed-delta baseline encodes the defect shape by construction.

### 7.2 Isolation Forest on/off (branch `evidence-measurements`)

| REVIEW | Flag rate | Recall | Cost |
|---|---|---|---|
| Forest active (published) | 0.243 | 0.841 | 0.283 |
| Forest inactive (what the live app runs) | 0.183 | 0.814 | 0.239 |

Cost difference 0.045 (95% CI 0.032–0.057) at REVIEW and 0.034 at REJECT; 577 more false alarms for 2.7 recall points. Config check: the app pipeline and the harness live path agree to 0.0 on 385 parts. Four of five families show the extra cost with a CI that excludes zero; the forest only gains recall on `higher_defect_prevalence` (+5.8 points, cost CI includes zero). The generator has no campaign-level drift, so the forest's design intent is untested, not refuted.

### 7.3 Sensitivity sweep, current scoring (150 lots per setting, 10 settings, live configuration)

- Module A REVIEW recall 0.784–0.978: beats static limits, static PAT and dynamic PAT at every setting (C1 holds).
- Cost beats static limits at 9 of 10 settings; at 1% prevalence 0.173 (REVIEW) / 0.146 (REJECT) vs 0.108 (C2 breaks).
- Flag rate 17–20% at every setting (C3 holds); dynamic PAT precision ≥ 0.957 (C4 holds).
- Module A is never the cheapest method: fixed delta at 8 settings, dynamic PAT at 2.

### 7.4 Scoring experiment (branch `scoring-experiment`; five families × 150 lots; thresholds tuned on seed 6101, evaluated on 6202, clean-lot check 6404, robustness 6303)

| Variant | Clean-lot flag (P1) | Flag rate | Recall | Cost/part [95% CI] | S1–S5 |
|---|---|---|---|---|---|
| V0 today (shipped thresholds) | 0.186 | 0.183 | 0.741 | 0.301 [0.280, 0.322] | n/a |
| V0 re-tuned | 0.343 | 0.335 | 0.918 | 0.329 [0.320, 0.338] | S1 S3 S4 fail |
| **V1 absolute, max** | **0.048** | 0.099 | 0.913 | **0.096 [0.089, 0.104]** | all pass |
| V1-C1 mean | 0.074 | 0.117 | 0.907 | 0.119 [0.111, 0.127] | S1 fails |
| V1-C2 hybrid | 0.021 | 0.073 | 0.881 | 0.093 [0.084, 0.101] | all pass (tie band) |
| V2 conformal, K=2 | identical to V1 (154 reference parts < 300 minimum, falls back) | | | | |
| V2 conformal, K=5 | 0.345 | 0.328 | 0.923 | 0.319 [0.311, 0.327] | S1 S3 S4 fail |
| V2 conformal, K=10 | 0.323 | 0.305 | 0.911 | 0.304 [0.295, 0.313] | S1 S3 S4 fail |

Same lots, baselines: dynamic PAT 0.273, fixed delta 0.150, static limits 0.601. At 1% prevalence: V1 0.048, V0 0.338, static limits 0.090. Leave-one-family-out thresholds for V1: recall 0.909, cost 0.097, all families pass. Selection rule picks V1 (C2 is within the 0.005 tie band, so the simpler variant wins). Post-hoc, exploratory: MCD alone costs 0.091 and z-score alone 0.137; V1 without ECOD is identical to V1, so ECOD never decides a flag.

**Consistency check [V]:** from `C = f + π(10 − 11r)` with f the held-out flag rate, the reported (f, r, C) tuples imply π ≈ 0.064 for the current flow and π ≈ 0.070 for V1; the V1 value is very sensitive to rounding (its coefficient 11r − 10 is about 0.04), and 0.064 lies inside its rounding range (0.046–0.093). Both are consistent with one common prevalence near 6.4%, within the generator's 1–8% prior.

**Not comparable with 7.1:** this run's mix gives the current flow a cost of 0.301 vs 0.239 in the published benchmark. Compare variants inside a run only.

### 7.5 Module B accuracy (branch `evidence-measurements`; training seeds 0–13, evaluation seed 7001, lot-id and seed overlap 0)

| | Module B | Persistence (168h = 24h) |
|---|---|---|
| Pooled relative MAE vs measured 168h | **4.88%** (95% CI 4.52–5.27) | 5.25% |
| Edge | 7.0% (8.0% at 150 lots) | |
| Defective parts only | 27.8% | 30.7% |
| `different_noise_regime` family | loses by 10.6% (40 lots), 6.9% (150) | |
| Interval coverage | 0.78 pooled (0.55 on the noise family) | target 0.90 |

Pre-registered criterion M1 (beat the best naive baseline by 10% and lose on no family by more than 10%) **fails**.

### 7.6 Module B out-of-range guard (branch `fixes-guard-signoff-units`)

False-block rate on in-distribution parts: 0.364%, 0.017%, 0.788%, 0.390%, 0.022% across the five families (100 lots each). Scale sweep: ×10⁻³ to ×10⁻¹ and ×10² to ×10³ are declined; **×10 passes** the guard (73 of 77 and 61 of 77 Module B REJECTs), because the lot-median window must tolerate about 8× normal lot-to-lot spread. The safety slope is an absolute number, so no physics-only fallback was allowed.

---

## 8. What the mathematics supports, and what it does not

**Supported [D][V][M]:**
1. A percentile threshold fixes the share of flagged scores independently of the data; this gives the 18.6% clean-lot flag rate its mechanism and implies the current flow cannot beat "flag nothing" below about 2.4% prevalence.
2. An absolute probability threshold has a lot-independent false-alarm rate, `α ≤ K·ε`, if the assumed null is right.
3. On synthetic data with pre-registered separate seeds, V1 had lower cost, higher recall and fewer false alarms than the current flow, with non-overlapping confidence intervals.

**Not supported:**
1. That V1 is better on **real** lots. Both flows are untested on real data **[U]**. The Gaussian null that V1's guarantee rests on is an assumption.
2. That V1's p-values are exactly calibrated. The observed 4.8% against a nominal bound near 1% (if K = 9) shows they are not.
3. That V1's cost numbers carry over to the published benchmark protocol **[U]** until it is re-run (Session I2a).
4. That V1's thresholds (tuned on synthetic labels at a 10:1 cost) are right for a customer. They need re-tuning on confirmed outcomes.

---

## 9. Open items and the test that settles each (Session I2a)

| Open item | Test |
|---|---|
| V1 on the published protocol | Re-run the published families (seed 2026) with V1; pre-registered rule: cost ≤ 0.22, recall ≥ 0.75, no family >0.03 worse, clean-lot flag ≤ 5% through the app |
| Sensitivity of V1 | Full 10-setting sweep, claims C1, C2, C5 (flag rate at 1% prevalence ≤ 6%), C6 (clean-lot flag at noise ×2 ≤ 8%), C7 (cost no worse than current by more than 0.03) |
| Calibration of V1 | **Add to Part 2c:** per detector and lot size, on clean lots, the share of p-values below 10⁻², 10⁻³ and 10⁻⁴ against the nominal share; confirm K |
| Small lots (< 30 parts, no MCD) | Clean-lot check at lot sizes 15 and 30 through the app |
| Downstream effects of the severity change | Consumer inventory; monotone transform keeps ranks and the UI working |
| Real data | Not available. The two public datasets checked (SECOM, NASA MOSFET aging) do not match burn-in lots |

## 10. Decision on the evidence so far

- **Better method on the evidence available:** V1, for the false-alarm problem.
- **Safe to ship today:** the current build (tag `demo-v1.2`), because V1 is not yet verified end to end.
- **Honest wording:** "On synthetic held-out data, absolute calibration reduced false alarms in clean lots from 18.6% to 4.8% while raising recall. This has not been tested on real data."


---

## 11. Update after Session I2a (branch `scoring-adoption`, HEAD 25148b3; 12 commits on demo-v1.2; nothing merged)

### 11.1 K is confirmed: 16 scores per part enter the maximum **[M]** (file:line reported by the agent)

12 z-scores (3 parameters × 4 checkpoints; `features/compute.py:133-142`, `module_a/scoring.py:181`) + 4 MCD scores (one per checkpoint; `scoring.py:149,160`) + 0 ECOD (NaN without an anchor, `scoring.py:243,255`). The 16 scores are correlated. So under V1 the ECOD leg is not merely non-deciding: it contributes no score at all.

Union bounds with K = 16 **[D]**: REVIEW α ≤ 16 × 1.107×10⁻³ = 0.0177; REJECT α ≤ 16 × 3.81×10⁻⁴ = 0.0061. Per leg: z leg (12 scores) ≤ 0.0133; MCD leg (4 scores) ≤ 0.0044.

### 11.2 Clean-lot flag rate through the app, by lot size and leg **[M]** (100 lots for n ≤ 40, 40 lots above)

| n | combined | z leg | MCD leg | Nominal bound, combined |
|---|---|---|---|---|
| 15 | 0.068 | 0.068 | not run | |
| 20 | 0.058 | 0.058 | not run | |
| 30 | **0.157** | 0.047 | 0.147 | 0.0177 |
| 40 | 0.114 | 0.032 | 0.109 | |
| 50 | 0.080 | 0.029 | 0.072 | |
| 60 | 0.058 | 0.026 | 0.050 | |
| 77 | 0.042 | 0.028 | 0.032 | 0.0177 |
| 100 | 0.039 | 0.028 | 0.030 | |
| 150 | 0.027 | 0.020 | 0.018 | |

At n = 77: observed 0.042 against a bound of 0.0177 (2.4×); z leg 0.028 against 0.0133 (2.1×); MCD leg 0.032 against 0.0044 (7.3×). **[V]** (arithmetic on the reported values.)

### 11.3 Calibration of individual scores: observed share with p < 1e-3, as a multiple of nominal 0.001 **[M]**

| n | z leg, generator | z leg, pure Gaussian data | MCD leg, generator | MCD leg, pure Gaussian data |
|---|---|---|---|---|
| 15 | 13.0× | 12.5× | n/a | n/a |
| 30 | 7.9× | 6.5× | 75.8× | 80.5× |
| 77 | 5.5× | 3.0× | 20.0× | 11.2× |
| 150 | 4.0× | 1.7× | 10.4× | 4.1× |

Reading **[D][M]**: the small-sample over-confidence appears on pure Gaussian data too, so it comes from the estimators (consistent with Hardin & Rocke 2005 for MCD), not from the generator. Above about 50 parts the generator's heavier tails add a residual that a finite-sample correction would not remove. **Consequence: V1's `p` is not a true probability.** It is a monotone severity index whose thresholds were tuned at about 77 parts, where the miscalibration happens to be absorbed. The wording "more extreme than about 1 in 10^s healthy parts" is therefore overstated by roughly one order of magnitude at the REVIEW threshold and must not be shown to users unless a calibration fix (F3) makes it true.

### 11.4 Published protocol (9,779 parts, seed 2026, live configuration, V1 thresholds from tuning seed 6101, 95% CIs over lots) **[M]**

| Method | Flag rate | Recall | Precision | Cost/part |
|---|---|---|---|---|
| Static limits | 0.002 | 0.040 | 1.000 | 0.511 |
| Fixed delta | 0.240 | 1.000 | 0.222 | 0.186 |
| Static PAT | 0.068 | 0.447 | 0.350 | 0.339 |
| Dynamic PAT | 0.032 | 0.591 | 0.972 | 0.219 |
| Current scoring, REVIEW | 0.183 | 0.814 | 0.237 | 0.239 [0.208, 0.270] |
| **V1 absolute, REVIEW** | 0.090 | 0.923 [0.902, 0.945] | 0.544 | **0.082 [0.069, 0.096]** |
| V1 absolute, REJECT | 0.077 | 0.912 | 0.627 | 0.076 |

Pre-registered verdict (`docs/ADOPTION_PLAN.md`, committed before the runs): R1 (cost ≤ 0.22) holds, R2 (recall ≥ 0.75) holds, R3 (no family more than 0.03 costlier) holds (every family is cheaper, by 0.116 to 0.459), **R4 (clean-lot flag ≤ 5% at lot sizes ≥ 30 through the app) fails at n = 30 (0.157)**. Hence "not ADOPT-READY"; recommendation "ADOPT WITH CHANGES". The R4 test is kept as a strict xfail; its 20-lot draw gave 0.2233.

Heavy-tailed-noise family, clean lots: V1 0.0714 vs current 0.199; baseline family 0.0446 vs 0.189. Cost on the heavy-tail family: V1 0.094 vs current 0.210.

**Caveats that apply to this table:** (a) the baselines are the standard fixed-rule versions; V1's thresholds were cost-tuned on the generator, so the comparison is asymmetric until the baselines are tuned the same way (not yet done); (b) V1 beating fixed delta on cost reverses the earlier ranking and deserves suspicion until (a) is done; (c) the families are the same generator structure as the tuning data; (d) nothing here is real data.

### 11.5 Other results of the session **[M]**

- Golden fixture under `absolute`: GOLDEN-045 is the only REJECT; lot disposition ACCEPT, PDA 0.01299 (1 of 77), instead of HOLD, PDA 0.03896. The decoys G-028, G-037, G-057 and G-066 no longer flag, consistent with their being healthy parts that a rank threshold flags by construction.
- Six tests fail under `MODULE_A_SCORING=absolute` (default mode: 1981 passed, 1 xfailed, 0 failed): 1 stub-signature (D), 3 decoy-dependent (B), 2 pin the old numbers, e.g. PDA 0.0649 becoming 0.0779 (A); 0 real defects (C).
- Default behaviour unchanged with the switch unset: benchmark headline diff empty; DEMO-COMPLETE-01 REJECT / 0.0779; DEMO-EARLY-01 LOT_AT_RISK / 0.1429; golden and LIVE-01 tests pass; only visible difference is `severity_log10p: null`.
- PDF component-ID overflow found and fixed (column widths 42/20/18 mm, with a test); sign-offs after REJECT_FINAL are still accepted (DISCLOSURES #34, #35).

### 11.6 What the new numbers change in the argument

- Result 2 (break-even prevalence) now has the measured published-protocol inputs: V1 α ≈ 0.04 at n = 77, r = 0.923 gives π* = α/(10r + α) ≈ 0.4%; the current scoring α = 0.186 gives about 2%. **[D]**
- The weak point of V1 moved from "flags too much" to "thresholds are only valid near the lot size they were tuned at, and its probabilities are not real probabilities".
- Candidate fixes: F1 raise the MCD floor to about 77 parts and use the z leg only below it: the diagnostic shows the z leg alone is at or below 4.7% for n = 30 to 150 (0.047, 0.032, 0.029, 0.026, 0.028, 0.028, 0.020), so F1 with a floor near 77 would meet the clean-lot criterion at those sizes by construction, at the price of dropping the multivariate detector below 77 parts, and its recall at small n is unmeasured. F3 (simulated finite-sample null for both legs) addresses the cause and would make the rarity wording defensible; effort is larger. F2 is awkward with the reweighted estimator.


---

## 12. Update after Session I2c (branch `scoring-adoption`, HEAD 4013ef7)

### 12.1 What V1F is **[M]**
V1 with one change: in absolute mode the MCD leg runs only when the lot has at least 77 parts (`MCD_MIN_PARTS_ABSOLUTE = 77`, `module_a/settings.py`); below that only the z-score leg runs (K = 12 instead of 16). Thresholds are unchanged (REVIEW 2.956, REJECT 3.419; tuned on seed 6101). At n ≥ 77 V1F equals V1 exactly (max score difference 5.7×10⁻¹⁴, identical flags), so every published-protocol number in §11.4 applies to V1F for 77-part lots. V1F is a **post-hoc** variant (created after the n = 30 failure); its small-lot behaviour was therefore validated on fresh seeds (7102 clean lots; 7103–7105 lots with defects), without re-tuning.

### 12.2 F-R4: clean-lot flag rate through the app, fresh seeds **[M]**
| n | 15 | 20 | 30 | 40 | 50 | 60 | 77 | 100 | 150 |
|---|---|---|---|---|---|---|---|---|---|
| V1F | 0.100 | 0.073 | **0.044** | 0.038 | 0.028 | 0.035 | 0.038 | 0.036 | 0.024 |

Criterion (≤ 5% for n ≥ 30) holds on the point estimates; at n = 30 the upper end of the CI is 0.052, i.e. marginal. n = 15 and 20 have no criterion and are not fine (10.0% and 7.3%), though better than the current scoring's 18.6%.

### 12.3 F-R5: small lots with defects (prevalence 3%, 5%, 8% pooled; five families; fresh seeds) **[M]**
| n | V1F cost | Current-scoring cost | V1F recall |
|---|---|---|---|
| 30 | 0.094 | 0.251 | 0.892 |
| 50 | 0.105 | 0.256 | 0.868 |
| 60 | 0.088 | 0.237 | 0.885 |

The CI of the cost difference excludes zero at every n; the lowest recall in any of the nine n × prevalence cells is 0.856. F-R5 holds. Dropping the MCD leg below 77 parts did not hurt in this generator.

### 12.4 F-R6: the baseline-fairness check **[M]**
Each baseline's single threshold was cost-tuned on tuning seed 6101 with the repo's optimizer, then evaluated on the published protocol (seed 2026).
| Method | Cost/part [95% CI] | Recall |
|---|---|---|
| Fixed delta, cost-tuned | **0.031 [0.018, 0.048]** | 0.979 |
| V1F, REVIEW | 0.082 [0.069, 0.096] | 0.923 |
| Dynamic PAT, cost-tuned | 0.094 [0.077, 0.112] (not distinguishable from V1F) | |
| Static PAT, static limits, cost-tuned | worse than V1F | |
| All four baselines with default parameters | worse than V1F | |

Derived with the verified cost model (§2) and the published prevalence 5.33% **[V]**: the tuned fixed delta has a false-alarm rate α ≈ 2.1% at recall 0.979; V1F has α ≈ 4.3% at recall 0.923 (±0.003 from rounding). So V1F loses to a tuned fixed delta mainly on recall and by about a factor of two on false alarms. A plausible reason, **not tested**: the generator defines defects through drift, so the 0h-to-168h delta is almost the label.

**Consequence for claims:** "Module A is cheaper than the industry baselines" is true only against default-parameter baselines (and against tuned static limits and static PAT); it is **not** true against a cost-tuned fixed delta, and it is a tie with a tuned dynamic PAT.

### 12.5 Sensitivity sweep on V1F (10 settings × 150 lots, live configuration, thresholds fixed) **[M]**
C1, C2, C5, C6, C7 hold at all 10 settings, for REVIEW and REJECT. C6 was evaluated on the 13 zero-defect lots at noise ×2 (flag rate 0.045), because the registered wording was ambiguous; that is a small post-hoc interpretation. The tuned fixed delta beats V1F at every setting. At lot size 30 V1F recall is 0.839 and its cost is level with tuned dynamic PAT.

### 12.6 Wording and suites **[M]**
- The rarity phrasing is removed in absolute mode: DPA reasons now read like "severity index 5.1; flag threshold 2.96". Hits fixed: `module_a/settings.py` (`rarity_phrase`), `capa/logic.py:298-301` and `:334-336`, two absolute-mode tests. No hits in `explain/`, `report/`, `frontend/src`.
- Switch unset: 1995 passed, 0 failed; default benchmark headline diff empty. `MODULE_A_SCORING=absolute`: 6 failed, 1989 passed, the same six tests as before (1 stub signature, 3 decoy-dependent, 2 pin old numbers).

### 12.7 Pre-registered verdict and what is still not known
ADOPT-READY (V1F) by the pre-registered rule: F-R4 and F-R5 hold, R1–R3 hold (n = 77 behaviour is unchanged), C1/C2 hold everywhere, and F-R6 reversed the ranking against fixed delta, which the rule counts as a result, not a failure.
Still **unknown [U]**: real-data behaviour; whether the explanation views (which still refit an MCD at 30–76 parts) are consistent with a z-only score; whether a cost-tuned fixed delta keeps its advantage when thresholds are transferred to a family it was not tuned on (leave-one-family-out for the baselines has not been run); the fused A+B system compared with the baselines.

---

## 13. Method-by-method comparison: the industry baselines against Module A scoring

Evidence tags as in the header. Costs are cost per part at FN:FP = 10:1 on the published protocol (9,779 parts, 521 defective, prevalence 5.33%) **[M]**; "flag nothing" costs 10π = 0.533 **[V]**.

| Method | How it works | Advantages | Disadvantages | Default-parameter result | Cost-tuned result |
|---|---|---|---|---|---|
| **Static absolute limits** | Pass/fail against fixed datasheet limits **[S]** | Universal, trivially auditable, zero tuning, near-perfect precision | Blind to parts that pass every limit but are peer outliers or drifting (the problem statement's premise **[S]** 1.5) | recall 0.040, precision 1.000, cost 0.511 (only 4% better than flagging nothing) | worse than V1F **[M]** |
| **Fixed delta limits** (space-spec style) | Limit on the change of a reading between checkpoints **[S]** | Targets drift directly; no population assumptions; easy to explain; one number per parameter | A limit in absolute units per parameter and per product, set from judgement or labelled history; blind to lot context (a lot-wide shift trips all or none); single-parameter; no forecast | recall 1.000, precision 0.222, flag rate 0.240, cost 0.186 | **cost 0.031 [0.018, 0.048], recall 0.979** |
| **Static PAT** (AEC-Q001) | Robust mean ± 6 robust sigma (IQR/1.35) from a pooled reference population, updated periodically **[S]** | Industry standard; explainable; catches peer outliers | Needs a maintained reference population; not lot-specific (lot-to-lot shifts cause misses or false rejects); 6σ is very conservative | recall 0.447, precision 0.350, cost 0.339 | worse than V1F **[M]** |
| **Dynamic PAT** (AEC-Q001) | The same limits recomputed per lot **[S]**; a case study reports >2% fewer false rejects than static per-lot limits **[S]** | Adapts to each lot; standard; very high precision | Needs ≥ 30 parts **[S]**; one snapshot per checkpoint, no trajectory, no multivariate view; conservative | recall 0.591, precision 0.972, cost 0.219 | cost 0.094 [0.077, 0.112] |
| **Previous Module A scoring** (percentile + max) | Percentile of each detector's score within the lot, max **[S]** | Catches most defects; per-part explanations | Flags a fixed share of every lot by construction (18.6% of clean lots) **[M]**; worse than flagging nothing below ~2.4% prevalence **[D]** | recall 0.814, precision 0.237, cost 0.239 (live config) | n/a |
| **Module A, V1F** (absolute tail probabilities + max, MCD leg for ≥ 77 parts) | z-score and MCD distance turned into tail probabilities, severity s = -log10 p, max | Lot-relative; scale-free scores; multivariate leg; flag load follows the lot (4% of clean lots); per-part explanations | p-values are uncalibrated (an index, not a probability); thresholds tuned near 77 parts; Gaussian assumption; multivariate leg off below 77 parts; tuned on synthetic labels | recall 0.923, precision 0.544, flag rate 0.090, cost **0.082** [0.069, 0.096] | n/a |

**Where V1F's z-score leg sits relative to DPAT [D]:** V1F's REVIEW threshold p = 1.107×10⁻³ corresponds to a two-sided |z| of 3.26, and REJECT (p = 3.81×10⁻⁴) to |z| of 3.55. The standard DPAT cut of 6σ has a two-sided p of about 2×10⁻⁹ (s ≈ 8.7). So V1F's z-score leg is the DPAT statistic with a much tighter cut chosen by the cost optimizer, plus a multivariate MCD leg. **[U, inference]** A large part of V1F's gain over *default* DPAT may therefore come from the cut, not from a new statistic; that fits cost-tuned DPAT (0.094) tying V1F (0.082). Test: read the cost-tuned multiplier of DPAT in `docs/evidence_data/adoption/v1f/fairness_table.csv`; if it lands near 3 to 4 sigma the inference is confirmed.

**What the evidence supports [M][V]:** V1F is much better than the previous scoring and than every default-parameter baseline, ties a cost-tuned dynamic PAT, and is beaten by a cost-tuned fixed delta on this synthetic data (where defects are drift by construction). The advantages that do not rest on this benchmark (explanations per part, scale-free lot-relative scores, a multivariate view, a forecast and governance workflow around it) are design properties, not measured wins.

---

## 14. V1F against a fixed delta limit, for the project's three judged needs

Needs from `context.md` 1.8 **[S]**: (1) a cost-asymmetric anomaly-detection score that punishes missed defects; (2) drift-prediction accuracy (MAE against the hidden 168h value); (3) explainability to a QA inspector. The premise in 1.5 **[S]**: a part can pass every absolute limit and still be "moving toward the line faster than its peers", which a fixed threshold cannot see.

### 14.1 What was measured (synthetic data, published protocol)
| | Fixed delta, default | Fixed delta, cost-tuned | V1F |
|---|---|---|---|
| Flag rate | 0.240 | not reported | 0.090 |
| Recall | 1.000 | 0.979 | 0.923 |
| Cost per part | 0.186 | **0.031** [0.018, 0.048] | 0.082 [0.069, 0.096] |
| Implied false-alarm rate on healthy parts [V] | 0.2 (1,823 of 9,258) | about 0.021 | about 0.043 |

The tuned delta limit also beat V1F at every setting of the 10-setting sweep, including the shifted drift-exponent settings, with thresholds fixed from the baseline tuning seed **[M]**. So the sweep gives **no evidence** that V1F is more robust than a delta limit to changes in healthy drift.

### 14.2 Where V1F is better, and how solid each point is
| Point | Status |
|---|---|
| Much cheaper than a *default* delta limit (0.082 vs 0.186; flags 9% vs 24%) | Measured **[M]** |
| Thresholds in scale-free units (the same two numbers for every parameter), where a delta limit needs one limit per parameter and per product | Design property; whether it transfers across products is **untested [U]**; whether the harness's fixed delta is absolute or relative is **unknown [U]** (read the baseline definition in `harness/`) |
| Compares each part with its own lot, so a lot-wide shift does not flood false alarms or silently pass | Design property; the sweep did not show an advantage **[M]** |
| Multivariate view (catches an unusual combination of parameters even if each delta is within limits) | Plausible; in the scoring experiment the MCD leg alone cost 0.091 against 0.137 for the z leg alone **[M]**, but a tuned delta still wins overall |
| A label-free starting point: the tuned REVIEW cutoff (s = 2.956, p = 1.1×10⁻³) is close to the round value s = 3 **[V]**, so a day-one default needs no confirmed outcomes; a delta limit has no such default | Inference **[U]**; performance at s = 3 not measured |

### 14.3 Where a fixed delta is better
- Cost and recall on this data (criterion 1): 0.031 against 0.082, recall 0.979 against 0.923 **[M]**. A plausible reason, untested: the generator defines defects through drift.
- Simplicity and auditability: a single number a QA inspector can read, and the "space-spec style" convention **[S]**.
- No distributional assumptions and no uncalibrated probabilities.

### 14.4 By need
| Need | Better on our evidence | Note |
|---|---|---|
| 1. Cost-asymmetric detection | Tuned fixed delta (0.031 vs 0.082 on synthetic data) | Both need labels to tune. If judged on unfamiliar data with no tuning labels, the ranking is unknown. |
| 2. Drift-prediction MAE | Not a Module A question | Module B (4.88% vs 5.25% for persistence). |
| 3. Explainability to a QA inspector | Neither clearly | A delta limit is the simplest to state; V1F gives peer context and per-parameter contributions, which suit the spec's premise but require statistical literacy. |
| Premise 1.5 (faster than peers) | V1F by design | Not shown to matter in our generator. |

### 14.5 The comparison that decides it has not been run
The shipped system is not Module A alone. Module B applies a calibrated drift-rate limit (the conformal 0.95 quantile of healthy drift per hour, `safety_slope`) to a forecast, and fusion rejects if either module crosses its REJECT level. That is a delta-style detector inside the system. The fair test is **system-level**: the fused verdict of Module A (V1F) plus Module B against a cost-tuned fixed delta, on the same lots. Until then, the stand-alone ranking (tuned delta first) must not be read as a ranking of the system.


## 15. Adoption record (Session I2b, 2026-10-04): absolute scoring (V1F) is the default

Appended after sections 1-14; nothing above is changed. Branch `adopt-v1f` (from `scoring-adoption` 4013ef7); the fallback `demo-v1.2` is untouched.

### 15.1 Before / after anchors (synthetic generator; pipeline output, no DB)

| Anchor | demo-v1.2 (rank, old seed) | demo-v2 (default absolute, new seed) | Same old seed under absolute |
|---|---|---|---|
| DEMO-COMPLETE-01 | seed 5: REJECT, PDA 0.0779, 15 of 77 flagged, top DEMO-COMPLETE-01-0004 | seed 2: REJECT, PDA 0.0779, 7 of 77 flagged (6 Module A REJECT), top DEMO-COMPLETE-01-0052 | seed 5: REJECT, PDA 0.0649, 6 flagged, top -0004 |
| LIVE-01 (full lot) | seed 32: COMPLETE, REJECT, PDA 0.0649, 13 flagged | seed 2: COMPLETE, REJECT, PDA 0.0649, 7 flagged (at 0h+24h: LOT_AT_RISK, 1 Module B REJECT) | seed 32: REJECT, PDA 0.0779, 6 flagged |
| DEMO-EARLY-01 | IN_PROGRESS, LOT_AT_RISK, PDA 0.1429, 11 flagged | unchanged (Module B only; Module A never runs in progress) | unchanged |
| Golden fixture through `POST /lots` | HOLD, PDA 0.03896, 3 REJECT parts (GOLDEN-045 and two decoys) | ACCEPT, PDA 0.01299, GOLDEN-045 the only REJECT, rank 1 | n/a |

New demo seeds were chosen by scanning seeds 1 to 80 with the same generator path as `POST /lots/demo`: `docs/evidence_data/adoption/system_level/scan_complete_seeds_1_80.txt` and `scan_live_seeds_1_80.txt`.
Coincidence worth knowing: the PDA values 0.0779 and 0.0649 appear in both columns because they are 6/77 and 5/77, with different lots.

### 15.2 The six tests that failed under absolute scoring, and how each was repaired

| Test | Class | Old expectation | New expectation and why it is right |
|---|---|---|---|
| `test_g5_gate.py::test_row6_severity_cap_note_fires_for_both_reasons_with_distinct_wording` | D (test double) | stub `patched(frames)` | `patched(frames, **kwargs)`; the pipeline now passes `scoring=...`; the test's purpose (two cap-note wordings on GOLDEN-045) is independent of the mode |
| `test_g5_routes.py::test_full_flow_across_routes` | B (decoys) | second REJECT part of the golden lot | the in-progress lot's Module B REJECT part; the flow tests route sequencing, not which detector flags |
| `test_load_demo_lots.py::test_golden_lot_through_the_route_is_hold` | B | HOLD, 3 REJECT, 0.03 < PDA < 0.05 | `..._is_accept_by_default`: ACCEPT, PDA = 1/77, one REJECT (GOLDEN-045); the HOLD expectations live on in `..._is_hold_in_rank_mode` |
| `test_text.py::test_explanation_summary_on_the_golden_lot` | B | "5 of 77 parts flagged, spread across ..." | "1 of 77 parts flagged, concentrated in leakage."; the old text is kept as a rank-mode test |
| `test_live_lot_anchor.py::test_live_lot_three_uploads_anchor` | A (old numbers) | 13 flagged | 7 flagged (new LIVE seed); the legacy numbers are pinned in `test_anchors_both_modes.py` |
| `test_config_check.py::test_pipeline_and_harness_live_path_agree_on_two_small_lots` | A | harness path without scoring | harness path with `module_a_scoring_config()`; parametrized over both modes |

The golden test `tests/integration/test_golden_module_a.py` passed unedited (GOLDEN-045 is still flagged REJECT, rank 1). New tests: default-mode and rank-mode anchors (`test_anchors_both_modes.py`), mode-aware PDF text, MCD/ECOD view labels (Vitest and backend).

### 15.3 System-level result and decision

See `docs/SYSTEM_LEVEL_BENCHMARK.md`: G-flip holds (system cost per part 0.326 -> 0.243, recall 0.956 -> 0.964); T1 and T2 did not fire; Module B adds 0.161 per part to Module A alone. The default was flipped on that basis.
