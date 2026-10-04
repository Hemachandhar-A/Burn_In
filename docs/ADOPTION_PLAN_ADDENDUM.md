# Module A absolute scoring, variant V1F: pre-registration (session I2c)

Committed BEFORE any V1F run. Nothing below is edited afterwards; deviations are appended at the end with date and reason.
Machine: Windows 11, Python 3.11.17 (uv), Node 22.21.1. Branch `scoring-adoption` at 25148b3, base tag `demo-v1.2`.
Supplements `docs/ADOPTION_PLAN.md` (which stays in force for R1-R3, C1-C7 definitions).

## The variant

**V1F = V1 with ONE change:** in absolute mode the MCD leg is active only when the lot has n >= 77 parts
(`MCD_MIN_PARTS_ABSOLUTE = 77` in `module_a/settings.py`, the standard lot size from the zero-failure derivation). Below
that only the robust-z leg runs (as it already does below 30). Thresholds unchanged (REVIEW 2.956, REJECT 3.419, tuned on
seed 6101). At n >= 77 V1F is IDENTICAL to V1, so the published-protocol numbers for V1 (flag 0.090, recall 0.923, cost
0.082 [0.069, 0.096]) remain valid for 77-part lots. Rank mode and the default path are untouched.

**Honest label:** V1F is a POST-HOC variant, created after seeing V1's n=30 failure (docs/ADOPTION_RESULT.md). Its small-lot
behaviour is therefore validated on FRESH seeds never used before, from 7101-7106 (7101-7401 range used by I2a tests:
7101 clean-lot tests/diagnostic, 7201 ties, 7301 DPA, 7401 defective lot). Seeds used in this session are listed in the
result. **Thresholds are NOT re-tuned.**

## Pre-registered criteria (verbatim)

* **F-R4:** clean-lot flag rate through the app (`run_full_pipeline`, `MODULE_A_SCORING=absolute`) <= 5% at every n in
  {30, 40, 50, 60, 77, 100, 150}; report n=15, 20 without a criterion. 100 clean lots for n <= 60, 40 lots above, fresh seeds.
* **F-R5 (small lots are no worse than today):** at n in {30, 50, 60} on lots WITH defects (prevalence 3%, 5% and 8%, 60 lots
  per cell, fresh seeds, five families pooled), V1F cost per part at REVIEW <= the current scoring's cost at the same n, AND
  V1F recall at REVIEW >= 0.70. Report both with 95% bootstrap CIs over lots. If F-R5 fails at some n, say so; the floor is
  NOT changed to make it pass.
* **F-R6 (baseline fairness):** V1F is called "cheaper than baseline B" only if its cost CI is below the cost of B with B's
  threshold cost-tuned on seed 6101.
* **F-R7 (sweep):** claims C1, C2, C5, C6, C7 exactly as in docs/ADOPTION_PLAN.md, evaluated for V1F on the full 10-setting sweep.

**ADOPT-READY (V1F)** = F-R4 and F-R5 hold; R1-R3 still hold on the published protocol (they must, since n=77 behaviour is
unchanged: re-verified by running the published protocol for V1F and checking it equals the V1 numbers within CI); C1 and C2
hold at every setting except where explicitly reported; and F-R6 does not reverse the ranking against any baseline (if it
does, the new ranking is reported plainly; it is a result, not a failure).

## Fine print decided now (so it is not decided after seeing results)

* "Fresh seeds" for F-R4: seed 7102 for the clean-lot lots (baseline family, prevalence 0), generated through
  `generator.lot.generate_lot`, ids `I2C-CLEAN-<n>-<i>`. For F-R5: seeds 7103 (3%), 7104 (5%), 7105 (8%); five families
  (`generator.families.FAMILIES`) pooled, 12 lots per family per cell = 60 lots per cell; prevalence is forced through
  `defect_prevalence_range=(p, p)`; lot size n forced through `n_parts`. Seed 7106 is reserved for a repeat if a run crashes.
* "Current scoring's cost at the same n": rank-percentile scoring, live configuration (no pooled reference, Isolation Forest
  inactive), thresholds from `config/harness_thresholds.yaml`, on the SAME lots as V1F (paired).
* Cost per part = (10 * missed + false alarms) / parts (FN:FP 10:1, the project's locked ratio); recall and flag rate at
  REVIEW. F-R5 "cost <=" is judged on the point estimate; the CIs (1000 lot-bootstrap resamples) are reported alongside and a
  case where the CIs overlap is called out as "not distinguishable" rather than as a win.
* F-R4 uses Module A's own tier (`severity_tier != PASS`), as in I2a, not the fused verdict.
* Baseline tuning (Part 2): each baseline's threshold parameter is tuned on seed 6101 with the repo's cost-sensitive
  optimiser (`harness.scoring.tune_threshold`, 10:1) on the same five families; evaluation on the published protocol (seed 2026).
* Sweep (Part 3): settings, 150 lots, live configuration and thresholds fixed as in docs/ADOPTION_PLAN.md.

## Clarifications appended before the F-R4 / F-R5 run (nothing above edited)

* **F-R5 is judged per n, pooled over the three prevalences (180 lots per n: 3 prevalences x 5 families x 12 lots).** The nine
  (n, prevalence) cells are also reported; a cell that fails is named even if the pooled value passes.
* "Cost <=" is judged on the point estimate for V1F vs current (paired, same lots); a paired lot-bootstrap CI of the cost
  difference (V1F - current) is reported, and "not distinguishable" is said if it contains 0.
* F-R4's share is the part-level share with `severity_tier != PASS` from `run_full_pipeline`; its 95% CI is a lot bootstrap.
  The criterion is judged on the point estimate; a CI upper bound above 5% is reported.
* Lot ids carry the family, n and prevalence so no two cells are common-random-number twins.
