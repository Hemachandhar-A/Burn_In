# System-level benchmark (session I2b Part 1) - PRE-REGISTRATION

Committed BEFORE any system-level run. All data synthetic. Date: 2026-10-04.

## Rules (verbatim from the session brief)

Methods, on the published-protocol complete lots (seed 2026, the five families, the same lots as harness/results/p18; ground truth = the generator's defect label per part):
- S-new   the FUSED system with absolute scoring (V1F + Module B + explainability gate + fusion rules; same code path as fusion.run_full_pipeline);
- S-old   the FUSED system with the previous scoring (MODULE_A_SCORING=rank);
- A-new   Module A alone with V1F (reference);
- D-tuned the cost-tuned fixed delta;
- P-tuned the cost-tuned dynamic PAT (parameters from the fairness check, tuned on seed 6101).

Flagged = part verdict is not PASS (WATCH or REJECT); ALSO report REJECT-only. Metrics: flag rate, recall, precision, false alarms, missed, cost per part at FN:FP = 10:1, with 95% bootstrap CIs over lots.

GATE G-flip (must hold to proceed to Part 2): cost(S-new) <= cost(S-old) + 0.01 AND recall(S-new) >= recall(S-old) - 0.03. If it fails: STOP after the report; do NOT flip the default.

TRIGGER T1: recall(S-new) lower than recall(D-tuned) by more than 0.03 AND cost(S-new) higher than cost(D-tuned) by more than 0.03, both with separated 95% CIs -> the report recommends building the layered option (a specification delta limit as an extra, independent leg) as a FOLLOW-UP session. T1 does NOT block Part 2 and the layered option is NOT built in this session.

TRIGGER T2: cost(S-new) within 0.03 of cost(D-tuned) or lower -> keep the system; state it in the claims. Report 'neither' if neither fires, with the numbers.

## Implementation notes fixed in advance
- Lots: `harness.held_out.generate_held_out_sets(seed=2026)` (5 families), each lot run through `fusion.run_full_pipeline(dataset, ScreeningConfig())` once per scoring mode, in separate processes. Module B is identical in both runs, so S-new minus S-old isolates the scoring change.
- Baselines (D-tuned, P-tuned) and A-new are read from the saved published-protocol part files (`docs/evidence_data/live_benchmark/parts_live.csv.gz`, `docs/evidence_data/adoption/parts_absolute_live.csv.gz`, tuned cuts `docs/evidence_data/adoption/v1f/baseline_tuned_thresholds.json`); the part keys are checked against the fresh run.
- The S-methods judge every part; a baseline judges only the parts it could evaluate (its `_evaluable` column), as in the fairness table.
- Bootstrap: `harness.variants.lot_bootstrap_metrics` (1000 reps, resampling lots).

## RESULT (run 2026-10-04; data: docs/evidence_data/adoption/system_level/)

Fused pipeline, 9779 parts, 521 defective, 127 lots, seed 2026, five families. 95% CIs over lots (1000 bootstrap reps).
Baselines judge only their evaluable parts. Nothing in the pre-registration was changed after the run.

| method | flag rate | recall [95% CI] | precision | false alarms | missed | cost/part [95% CI] |
|---|---|---|---|---|---|---|
| S-new (WATCH+REJECT) | 0.275 | 0.964 [0.946, 0.979] | 0.187 | 2185 | 19 | 0.243 [0.212, 0.276] |
| S-new (REJECT only) | 0.260 | 0.954 [0.935, 0.972] | 0.195 | 2048 | 24 | 0.234 [0.202, 0.267] |
| S-old (WATCH+REJECT) | 0.353 | 0.956 [0.935, 0.976] | 0.144 | 2957 | 23 | 0.326 [0.297, 0.355] |
| S-old (REJECT only) | 0.258 | 0.939 [0.914, 0.963] | 0.194 | 2035 | 32 | 0.241 [0.209, 0.275] |
| A-new (Module A alone, V1F REVIEW) | 0.090 | 0.923 [0.903, 0.945] | 0.544 | 403 | 40 | 0.082 [0.069, 0.095] |
| D-tuned (fixed delta) | 0.072 | 0.979 [0.966, 0.990] | 0.729 | 190 | 11 | 0.031 [0.018, 0.047] |
| P-tuned (dynamic PAT) | 0.088 | 0.898 [0.872, 0.924] | 0.546 | 389 | 53 | 0.094 [0.078, 0.112] |

Cost per part by family (WATCH+REJECT): altered_correlation S-new 0.207 / S-old 0.274 / A-new 0.072; baseline 0.200 / 0.298 / 0.074;
different_noise_regime 0.377 / 0.429 / 0.094; higher_defect_prevalence 0.258 / 0.374 / 0.137; wider_drift_exponent 0.174 / 0.273 / 0.064.

Gates, exactly as pre-registered:
- **G-flip: HOLDS.** cost(S-new) 0.243 <= cost(S-old) 0.326 + 0.01; recall(S-new) 0.964 >= recall(S-old) 0.956 - 0.03. The default may be flipped.
- **T1: did not fire.** recall(S-new) is 0.015 below D-tuned (needs > 0.03); cost is 0.212 higher; the CIs are not separated on recall.
- **T2: did not fire.** cost(S-new) is 0.212 above D-tuned (needs within 0.03 or lower). Outcome: **neither**.
- **Module B's effect:** cost(S-new) - cost(A-new) = +0.161 per part. The fused system's false-alarm load comes mostly from the Module B forecast leg
  (WATCH/REJECT parts whose forecast, not Module A, flags them); Module A alone costs 0.082. This does not block the flip (the scoring change
  helps the fused system by 0.083 per part) but it is a finding to disclose: the SYSTEM does not match a cost-tuned fixed delta or Module A alone on
  false-alarm cost on synthetic data, and its recall is no higher than D-tuned's.
