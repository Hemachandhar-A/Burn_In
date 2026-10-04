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
