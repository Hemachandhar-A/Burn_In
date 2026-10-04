# Decision record: which detection approach do we ship?

| | |
|---|---|
| Date | 2026-10-03 |
| Status | **Accepted for the build, with a pre-registered review trigger (section 9)** |
| Decision owner | The Lead (this record was drafted by the assistant; the ratings are judgements the Lead must review) |
| Related documents | `SCORING_COMPARISON.md` (all measurements), `decision_matrix.py` (the matrix, re-runnable), `SESSION_DECISIONS.md` |

Evidence tags: **[S]** spec, **[V]** arithmetic re-done on published numbers, **[D]** derivation, **[M]** measured by an agent on **synthetic** data, **[J]** judgement, **[U]** unknown.

---

## 1. Why this record exists

The choice of detection approach was about to be made on one number (cost per part on a synthetic benchmark). A cost-tuned fixed delta limit scores best on that number, so a score-only decision would pick the simplest baseline. This is a mission-critical screening problem, so the decision has to weigh more than the score: explainability to a QA inspector, behaviour on data we have not seen, failure modes, auditability and day-one deployability. This record shows how that was done and why the answer came out as it did.

## 2. What the mission needs

From the problem statement as analysed in `context.md` **[S]**:
1. **Cost-asymmetric detection** (judged criterion 1): a defective part let through costs far more than a false alarm. We use 10:1.
2. **Drift prediction accuracy** (criterion 2): MAE against the hidden 168h value.
3. **Explainability to a QA inspector** (criterion 3): in terms a human reviewer would accept.
4. **The premise (1.5):** a part can pass every absolute limit and still be on a trajectory that marks it as early-life risk. A fixed threshold only asks "did you cross the line", not "are you moving toward the line faster than your peers".
5. **Unknowns that shape the choice:** no real burn-in dataset exists; the judges' data may differ from our generator in scale, noise and defect mechanism.

## 3. Options

| # | Option | Status |
|---|---|---|
| O1 | Fixed delta limit alone (space-spec style) | Baseline in the harness |
| O2 | Dynamic PAT alone (AEC-Q001, robust median ± 6 sigma per lot) | Baseline in the harness |
| O3 | Previous Module A scoring (percentile + max) with Module B | Shipped in `demo-v1.2` |
| O4 | V1F alone: absolute tail probabilities + max, MCD leg for ≥ 77 parts | Built, off by default |
| O5 | **System:** V1F + Module B forecast + explainability gate + fusion | Built and verified when V1F is switched on |
| O6 | Layered: O5 plus a specification delta limit as an extra, independent leg | **Not built, not evaluated** |

## 4. Evidence available

Measured on synthetic data (published protocol: 9,779 parts, 521 defective, prevalence 5.33%) **[M]**; costs at FN:FP = 10:1, flagging nothing costs 0.533 **[V]**:

| | Recall | Healthy-part false-alarm rate α | Cost per part |
|---|---|---|---|
| Fixed delta, cost-tuned | 0.979 | ≈ 0.021 [V] | **0.031** [0.018, 0.048] |
| Fixed delta, default | 1.000 | ≈ 0.20 [V] | 0.186 |
| Dynamic PAT, default | 0.591 | ≈ 0.001 [V] | 0.219 |
| Dynamic PAT, cost-tuned | not reported | not reported | 0.094 [0.077, 0.112] |
| Previous scoring (live config) | 0.814 | 0.186 on clean lots | 0.239 |
| V1F | 0.923 | ≈ 0.043 [V] | 0.082 [0.069, 0.096] |

Other facts that matter here:
- The tuned delta also beat V1F at every setting of the 10-setting sweep, including shifted drift-exponent settings **[M]**. The sweep gives no evidence that V1F is more robust than a delta limit.
- V1F's p-values are uncalibrated (MCD leg about 20× too frequent at p < 10⁻³ at n = 77); it is a severity index, not a probability **[M]**.
- Module B beats persistence by only 7% on MAE and under-covers (0.78 vs 0.90) **[M]**; its out-of-range guard has a known hole at exactly ×10 scale **[M]**.
- The shipped system is not Module A alone: Module B applies a calibrated drift-rate limit to a forecast, and fusion rejects if either module crosses its REJECT level **[S][M]**. The fused system has **not** been benchmarked against the baselines **[U]**.

## 5. Criteria, weights and rubrics

Weights (percent) reflect the mission: miss protection and explainability carry the most weight, because two of the three judged criteria are about them and a miss is the costly error. Rubrics are on a 1–5 scale (5 best).

| # | Criterion | Weight | Rubric |
|---|---|---|---|
| C1 | Miss protection (recall at the operating point) | 20 | 5 ≥ 0.97; 4 ≥ 0.90; 3 ≥ 0.80; 2 ≥ 0.60; 1 below |
| C2 | False-alarm burden (healthy-part false-alarm rate α) | 10 | 5 ≤ 0.01; 4 ≤ 0.03; 3 ≤ 0.05; 2 ≤ 0.10; 1 above |
| C3 | Explainability to a QA inspector | 20 | 5 = per-part sentence + quantitative drivers + uncertainty + notes, tested; 4 = clear per-part statement with context; 3 = exists but weak reason; 2 opaque |
| C4 | Drift forecast with an interval (criterion 2) | 10 | 1 none; 3 present, modest accuracy |
| C5 | Robustness to unfamiliar data and lot shifts, and declares when it cannot judge | 15 | 5 measured robust + declares; 4 robust by design, partly measured, declares; 3 known holes; 2 fails silently on a realistic shift |
| C6 | Method transparency and predictability | 10 | 5 = a few formulas a reviewer can recompute; 3 = documented statistical model; 2 = several interacting components |
| C7 | Day-one deployability without labelled history | 10 | 5 standard parameters, no labels; 4 spec-given limits; 3 defensible default or per-parameter limits; 2 needs customer-history calibration |
| C8 | Covers the premise (faster than peers) and multivariate structure | 5 | 5 peer-relative + multivariate + trajectory; 4 peer + multivariate; 3 peer, single parameter; 2 drift only |

## 6. Ratings and the reasons for them

| Option | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | **Weighted total** |
|---|---|---|---|---|---|---|---|---|---|
| O1 Fixed delta alone | 5 | 4 | 4 | 1 | 2 | 5 | 3 | 2 | 3.50 |
| O2 Dynamic PAT alone | 2 | 5 | 4 | 1 | 4 | 5 | 5 | 3 | 3.55 |
| O3 Previous scoring + Module B | 3 | 1 | 3 | 3 | 3 | 2 | 2 | 5 | 2.70 |
| O4 V1F alone | 4 | 3 | 4 | 1 | 3 | 3 | 3 | 4 | 3.25 |
| **O5 System (V1F + B + gate)** | 4 | 3 | 5 | 3 | 4 | 2 | 2 | 5 | **3.65** |
| O6 Layered (O5 + delta guard) | 5 | 2 | 5 | 3 | 3 | 2 | 2 | 5 | 3.60 |

Reasons (every rating is a judgement against the rubric; evidence in brackets):
- **O1.** C1: recall 0.979 [M]. C2: α ≈ 2.1% [V]. C3: one readable rule with a limit, but no peer context [J]. C4: no forecast. C5: limits are in absolute units, nothing declares a unit or scale error, a lot-wide shift is invisible [J]; the sweep showed robustness to generator-parameter shifts [M], so 3 is defensible (tested below). C6: one number per parameter. C7: spec-given limits exist in procurement [S] but are per parameter and product. C8: drift only, no peers, single parameter.
- **O2.** C1: default recall 0.591 [M]; tuned recall is unreported, so I rated 2 rather than 1 given the tied tuned cost. C2: 9 false alarms in 9,258 healthy parts [V]. C3: a standard, familiar statement ("outside the lot's ±6σ") [S]. C5: lot-relative and scale-free, needs ≥ 30 parts and says so [S]. C7: standard parameters, no labels. C8: peer-relative but single-parameter snapshot [S].
- **O3.** C2: flags 18.6% of clean lots [M]. C3: explanations exist, but "top 4% of this lot" is a weak reason [J]. C4/C8: includes Module B. C7: thresholds tuned on synthetic labels.
- **O4.** Same detector as O5 but without the forecast and the full explanation stack. C2: α ≈ 4.3% [V]. C5: scale-free, small-lot rule, but uncalibrated tails and a 7.1% clean-lot flag rate in the heavy-tailed family [M].
- **O5.** C1: by construction recall is at least that of V1F alone (REJECT if either module crosses), but this has **not been measured** [J]. C3: the most complete explanation stack (sentence, z-score table, MCD/ECOD/SHAP views, uncertainty, notes), implemented and screenshotted [M]. C4: forecast present but only 7% better than persistence. C5: guard declines unfamiliar scales and says so, with a documented hole at ×10 [M]. C6: many interacting parts is a real cost. C7: Module B needs calibration on customer history.
- **O6.** C1: the recall of a union is at least the larger of its parts [D], so ≥ 0.979 if the delta leg is as good as the tuned delta; C2: false alarms add, α ≤ 0.021 + 0.043 = 0.064 [D, upper bound]. Everything else as O5. **Unbuilt and unevaluated.**

## 7. Results and how far to trust them

Base-weight totals: O5 3.65, O6 3.60, O2 3.55, O1 3.50, O4 3.25, O3 2.70. **The top four are within 0.15, which is noise given that ratings are one-point judgements.** Changing a single rating (O1's C5 from 2 to 3) moves O1 from 3.50 to 3.65 and into a tie for first.

Sensitivity to the weights (`decision_matrix.py`):

| Weighting | First place |
|---|---|
| Base | O5 (3.65) |
| Equal weights | O2 (3.62), O5 3.50 |
| Detection-heavy (C1 35, C2 20) | **O1** (3.85) |
| Explainability-heavy (C3 35) | O5 = O6 (3.85) |
| Real-world-heavy (C5 30, C7 15) | O2 (3.80) |
| Synthetic score only (C1 60, C2 40) | **O1** (4.60) |
| Mission example (C1 15, C2 10, C3 15, C4 10, C5 20, C6 10, C7 10, C8 10) | O5 (3.65) |

Monte Carlo over 20,000 random weight vectors (uniform on the simplex); "mission" = random weights with C1 ≥ 15 and C3 ≥ 15 (miss protection and explainability each at least 15%, reflecting the stated criteria); "noise" = each rating randomly moved by ±1 with probability 0.5:

| Option | First, random | Top-2, random | First, mission | Top-2, mission | First, mission + noise | Top-2, mission + noise |
|---|---|---|---|---|---|---|
| O1 | 7.9% | 34.8% | 19.7% | 35.0% | 20.4% | 38.3% |
| O2 | **50.7%** | 62.6% | 11.6% | 23.2% | 12.3% | 26.4% |
| O3 | 0.0% | 0.0% | 0.0% | 0.0% | 0.1% | 0.9% |
| O4 | 0.0% | 0.9% | 0.0% | 0.0% | 6.4% | 17.9% |
| **O5** | 27.3% | **63.5%** | 19.3% | **65.0%** | 30.6% | 57.3% |
| O6 | 14.1% | 38.3% | **49.4%** | **76.8%** | 30.2% | 59.3% |

**What is robust (holds under every weighting and noise run):**
1. O3, the scoring that ships today, is never a leading option (0 to 1.2% first-place), and O5 beats it in 92 to 100% of random draws. **Replacing it is a robust conclusion.**
2. O4 (V1F without the system around it) almost never wins; the system around it matters for the judged criteria.
3. O5 is the most consistently high-ranked of the options that exist today: it is in the top two in 50 to 65% of draws in every run.

**What is not robust:** the choice among O1, O2, O5 and O6. Dynamic PAT wins when miss protection is allowed to carry little weight (random weights: 50.7%) and loses ground (11.6%) once miss protection and explainability are held at 15% each. Because the problem statement says false negatives are penalised "far more", I treat the mission-constrained rows as the relevant ones; that is a judgement the Lead should confirm.

## 8. Scenario view: what happens if reality differs from our generator

Our benchmark is one world (defects are drift by construction **[M]**, noise is Gaussian-like). Three scenarios, with the ranking by expected regret. S2 and S3 are **[J]** and untested.

| Scenario | Likely best | Weak |
|---|---|---|
| S1: defects are drift-like (our synthetic world) | O1 tuned (measured), O6 on recall | O2 (misses), O3 (false alarms) |
| S2: defects also include non-drift anomalies (high initial level, correlated shifts, lot-wide shifts) | O5, O6 | O1 (blind to anything that is not a delta) |
| S3: data arrive in unfamiliar scale or units | O2, O5 (scale-free; Module B declines) | O1 (absolute limits), O6's delta leg unless the canonical units are right |

Worst-case regret is lowest for O6 (a union keeps the delta limit's strength in S1 and the peer-relative view in S2), then O5, with O1 and O2 each having a severe failure in at least one scenario. This is the main reason the layered design is attractive for a critical mission, and also the reason it has to be evaluated before it is trusted: a union adds false alarms and an extra component to maintain.

## 9. Decision

**Ship O5 (V1F + Module B + gate) as the detection design, replacing the previous scoring (O3).** Specifically: switch the default to absolute scoring (Session I2b), keep the legacy scoring available behind a switch, and keep the baselines (fixed delta, PAT, DPAT) in the harness as continuing cross-checks.

**Why O5 and not the options that score better on one number:**
1. **A tuned fixed delta wins the synthetic cost score but is not chosen alone.** Its advantage depends on our generator defining defects through drift and on limits tuned with labels we do not have in real life. It is blind to non-drift anomalies, has no notion of peer context or of being out of range, and offers no forecast. In a mission where the cost of a miss is high and the real defect mechanism is unknown, relying on one rule whose assumption we cannot verify is the larger risk. (S1 is the only scenario in which it wins.)
2. **Dynamic PAT alone is not chosen** because at its standard parameters it misses 41% of defects (recall 0.591) and offers no forecast; its tuned cost ties V1F only by moving its cut towards V1F's (see `SCORING_COMPARISON.md` §13, inference).
3. **The previous scoring is replaced** because it flags a fixed share of every lot by construction (18.6% of clean lots) and is worse than flagging nothing below about 2.4% prevalence **[D][M]**; this is the most robust finding in the matrix.
4. **V1F is chosen over the previous Module A scoring on measured evidence:** published-protocol cost 0.082 against 0.239, flag rate 0.090 against 0.183, recall 0.923 against 0.814, clean-lot flag rate at most 0.044 for lots from 30 to 150 parts **[M]**, with the pre-registered criteria R1 to R3, F-R4, F-R5 and F-R7 passed. F-R6 (baseline fairness) did **not** pass cleanly: it reversed the ranking against a cost-tuned fixed delta, which the rule counts as a result to report, not as a failure.
5. **The system, not Module A alone, is the deliverable:** it is the only option that supplies all three judged criteria (a forecast, a cost-aware detector, and a full explanation).

**Layered option O6 is a pre-registered follow-up, not a present decision.** It cannot be chosen now because it is neither built nor evaluated, and an untested component in a critical system is itself a risk.

**Review trigger (pre-registered).** Run the system-level benchmark: the fused verdict of O5 (flagged = part verdict is not PASS; REJECT-only also reported) on the published-protocol lots, against the cost-tuned fixed delta and tuned dynamic PAT from the fairness check, with 95% bootstrap CIs over lots.
- **T1:** if the system's recall is lower than the tuned delta's by more than 0.03 with separated CIs, **and** the system's cost exceeds the tuned delta's by more than 0.03 with separated CIs, build and evaluate O6 (delta guard leg) in a follow-up session.
- **T2:** if the system's cost is within 0.03 of the tuned delta's, or lower, keep O5 and state that in the claims.
- **T3:** if real data or a judges' dataset become available and a baseline clearly outperforms O5, reopen this record.

## 10. Risks of the decision and how they are handled

| Risk | Mitigation |
|---|---|
| V1F's thresholds are tuned near 77-part lots; its probabilities are uncalibrated | Present severity as an index; MCD leg only for n ≥ 77; document; transfer test on held-out families (optional Part 5 of I2b) |
| Gaussian assumption fails on heavy-tailed real data (clean-lot flag 7.1% in the heavy-tailed family) | Disclosed; recalibrate on customer history (shadow mode) |
| A tuned delta limit beats us on cost | Disclosed in `PPT_NUMBERS.md`; claim limited to "ties tuned DPAT, beats the previous scoring and default baselines"; trigger T1 |
| System complexity | Test suite (1,995 tests in default mode), audit trail, legacy switch, `demo-v1.2` kept as the fallback tag |
| Module B's modest accuracy and out-of-range hole at ×10 | Disclosed (#27, #31); the guard declines other scales |
| Ratings are judgements | Published with rubrics; sensitivity and noise runs; the Lead can edit `decision_matrix.py` and re-run |

## 11. What would change this decision

- A system-level benchmark meeting T1 (build O6).
- Evidence on real or judge-supplied data that a simple rule outperforms the system (reopen under T3).
- A transfer test showing that V1F's thresholds do not transfer across product families better than a tuned delta limit (this removes the scale-free argument).
- A different Lead weighting: if the Lead sets C1 at 35% or more and ignores C3 to C8, the matrix favours the tuned fixed delta (3.85 vs 3.60 for O5), and that should be a conscious choice.

## 12. Limits of this record

- All performance numbers are synthetic; nothing is validated on real lots.
- The ratings were assigned by the assistant using the rubrics above; no second reviewer has seen them.
- O5's recall (C1) and false-alarm rate (C2) are inferred from V1F's and the union logic, not measured at system level.
- The weights are a statement of what the mission values; a different statement gives a different winner (section 7).

## 13. Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Decision owner (Lead) | | Accept / Amend | |
| Reviewer of the ratings | | Agree / Re-rate (attach edited `decision_matrix.py`) | |


## Outcome of the system-level benchmark (Session I2b, 2026-10-04) - appended; nothing above is changed

The pre-registered system-level benchmark (`docs/SYSTEM_LEVEL_BENCHMARK.md`, committed before the run; 9,779 synthetic parts, seed 2026) compared the whole fused system with absolute scoring (S-new) against the same system with the previous scoring (S-old), Module A alone (A-new) and the cost-tuned fixed delta (D-tuned) and dynamic PAT (P-tuned).

| Method | Flag rate | Recall | Cost per part [95% CI] |
|---|---|---|---|
| S-new | 0.275 | 0.964 | 0.243 [0.212, 0.276] |
| S-old | 0.353 | 0.956 | 0.326 [0.297, 0.355] |
| A-new | 0.090 | 0.923 | 0.082 [0.069, 0.095] |
| D-tuned | 0.072 | 0.979 | 0.031 [0.018, 0.047] |
| P-tuned | 0.088 | 0.898 | 0.094 [0.078, 0.112] |

- **G-flip fired in favour (holds):** cost(S-new) 0.243 is below cost(S-old) 0.326 + 0.01, and recall 0.964 is above 0.956 - 0.03.
- **T1 did not fire:** the recall gap to D-tuned is 0.015 (needs more than 0.03). **T2 did not fire:** the system's cost is 0.212 above D-tuned. Result: **neither**; no layered-option follow-up is triggered by the pre-registered rule, but the numbers show the system is far from a tuned delta limit on false-alarm cost.
- Module B adds 0.161 per part to Module A alone (0.243 against 0.082).

**The decision stands:** absolute scoring (V1F) becomes the default, because it makes the system cheaper at no cost in recall; the claims drawn from it are limited to what the tables support (`docs/PPT_NUMBERS.md`, "Module A scoring v2"). It does not show that the system beats a cost-tuned fixed delta, and it does not show that the Module B forecast leg is worth its false alarms; both are disclosed (`docs/DISCLOSURES.md` #38, #39).
