# Evidence plan (session M1) - pre-registered before any measurement

Written and committed BEFORE the Module B MAE, live-configuration benchmark or sensitivity runs. Only
"Deviations" at the bottom may be appended later, each with a reason. Everything here is measurement on
synthetic data; no shipped behaviour changes.

## Pass criteria (verbatim from the session brief)

M1 PASS: Module B's pooled MAE beats the best naive baseline by at least 10%, and loses to it on no held-out family by more than 10%. Whatever the outcome, report it.

M3 CONFIG CHECK: on 5 lots, Module A severities from the app pipeline (fusion.run_full_pipeline with no prior_frames) equal those of the harness LIVE path to within 1e-9. DECISION RULE: if the absolute difference in cost per part between the benchmark configuration and the live configuration is below 0.01 at both REVIEW and REJECT, state "no material difference"; otherwise state "the Isolation Forest matters" and give both sets of numbers.

M5 CLAIMS (thresholds stay at their shipped values; nothing is re-tuned): C1 Module A recall exceeds static limits, static PAT and dynamic PAT at EVERY setting. C2 Module A cost per part beats static limits at EVERY setting. C3 Module A's flag-rate floor persists (flag rate stays at or above 10%) even at 1% prevalence. C4 dynamic PAT precision stays above 0.9 at every setting. Report which hold and where each breaks.

## Operationalisation (fixed now, before running, so the verdict cannot be tuned to the result)

The criteria above leave a few measurement choices open. They are fixed here:

1. "Pooled MAE" for M1 is the **relative MAE**: |predicted_168h - measured_168h| / |measured_168h|, averaged over
   every part and every parameter (iddq, leakage, prop_delay), because absolute errors in uA, nA and ns cannot be
   pooled. Absolute MAE per parameter is reported alongside.
2. The score target is the **measured** 168h reading (what a judge's hidden Value_168h is). Error against the
   noise-free true 168h (generator sidecar, never a model input) is reported as a secondary column.
3. The PASS verdict is judged on the **0h+24h-only mode**, the mode the problem statement asks for. The
   0h+24h+96h mode is reported next to it; if the two disagree the report says so.
4. "Best naive baseline" = the baseline with the lowest pooled relative MAE (chosen on the pooled data, per mode)
   among the four brief baselines (a) persistence, (b) linear, (c) fixed power law n = 0.22, (d) lot-median
   relative drift, PLUS (e) the app's own lot-fitted power law (module_b.baselines), added as a stricter
   comparator. The verdict is reported against the best of (a)-(e) (strict) and, separately, the best of (a)-(d).
   The strict one decides.
5. "Beats by at least 10%": model pooled relative MAE <= 0.90 x best-baseline pooled relative MAE.
   "Loses on a held-out family by more than 10%": model family relative MAE > 1.10 x that family's best baseline.
   Held-out families are wider_drift_exponent, higher_defect_prevalence, different_noise_regime,
   altered_correlation. The `baseline` family is the model's training distribution (in-distribution, not held
   out); it is reported but is not part of the held-out clause.
6. 40 lots per family (default lot size), seed 7001, lot ids `M1-<family>-NNNN`. Bootstrap 95% CIs: 1000
   resamples of lots with replacement, bootstrap seed 20261003.
7. M5: the sensitivity runs use Module A in the LIVE configuration (no prior_frames) as primary; the same number
   of lots per setting for every setting; thresholds from `harness.bakeoff.load_harness_thresholds()` unchanged.
   A claim "holds" only if it holds at the point estimate at every one of the 11 settings (baseline + 10); the
   CI is reported but a point estimate that breaks counts as a break.

## Deviations

(none yet)
