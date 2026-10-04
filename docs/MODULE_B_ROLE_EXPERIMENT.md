# Module B's role in finished-lot verdicts (Session I3 Part 1) - PRE-REGISTRATION

Committed BEFORE any run of this experiment. All data synthetic. Date: 2026-10-04. Base: `demo-v2` (830d8f3) plus the docs commit 0ab3152.
After this commit only an "Appended deviations" section may be added; nothing above it is edited.

## Question
For a COMPLETE (finished) lot, what should Module B's forecast do to the part verdict? Context [M]: fusing B into finished-lot verdicts adds
about 21 caught defects and about 1,782 false alarms (docs/DECISION_RECORD_DETECTION_APPROACH.md, sections "Outcome" and 14.3).
In-progress lots are NOT touched by this experiment (DEMO-EARLY-01 must not change).

## Variants (applied ONLY when the lot status is COMPLETE)
Module A's tier is the one the pipeline already uses: the part's worst Module A result (highest severity), with the explainability gate
(A REJECT without `explainable_corroboration` is capped to REVIEW). Module B's input is the part's worst Module B result
(highest drift_rate / safety_slope), as `fusion/pipeline.py` picks it today. The fusion table is `fusion/gate.py`'s, unchanged:
REJECT if either tier is REJECT, or A REVIEW with B REVIEW; WATCH if exactly one is REVIEW; else PASS.

| Id | Name | B's tier on a COMPLETE lot |
|---|---|---|
| (a) | current | REJECT when `exceeds_safety_slope`, else PASS (today) |
| (b) | tiered | REJECT when `lower_bound_exceeds_safety_slope`; REVIEW when only `exceeds_safety_slope`; else PASS |
| (c) | advisory | PASS always (B appears in explanation and notes, does not change the verdict) |
| (d) | off | PASS always (reference: Module A alone decides) |

Stated in advance: (c) and (d) give IDENTICAL part verdicts by construction, so their costs are identical; they differ only in whether the
forecast is shown. In (b) a part with A REVIEW and B REVIEW is REJECT (the existing table applied as written). In (b) `lower_bound_exceeds_safety_slope`
is read from the same worst-B result as `exceeds_safety_slope` (a different parameter of the same part whose lower bound exceeds while the
worst parameter's does not is not looked at; this is the pipeline's per-part pick, kept so the offline combination equals the real one).
Parts whose forecast is unavailable (`exceeds_safety_slope` None) have B tier PASS in every variant.

## Data
- VALIDATION seeds 7301, 7302, 7303, 7304, 7305, disjoint from every seed used so far (6101, 6202, 6303, 6404, 7101-7106, 2026).
- For each seed s and each of the five families (`generator.families.HELD_OUT_FAMILY_NAMES`): `harness.held_out.generate_held_out_set(family,
  seed=s, min_lots=20, min_per_archetype=1, lot_id_prefix=f"V{s}")`. That is 20 lots per (seed, family), 100 lots per family, 500 lots in all, 77 parts each.
- TUNING data for anything tuned: seed 6101 only (Part 4). Nothing is tuned in Part 1: the Module A thresholds stay 2.956 / 3.419 and Module B stays as shipped.
- Per-part inputs are taken ONCE per lot, without running the explanation stack: `features.compute.compute`, `module_a.detect.detect` (with
  `module_a_scoring_config()`), `module_b.predictor.predict`, then the pipeline's own per-part picks. Stored per part: A tier, A explainable_corroboration,
  A cap reason, B exceeds, B lower-bound exceeds, B forecast_unavailable, the label. The four variants' verdicts are computed from those in one pass.
- CHECK: on 5 lots (the first lot of each family of seed 7301), variant (a) from the offline combination must equal the verdicts of
  `fusion.run_full_pipeline` part for part. If not, the experiment stops and the offline code is fixed before any table is read.

## Metrics
Flagged = part verdict is not PASS (also reported: REJECT only). Cost per part = (10 x missed + false alarms) / parts (FN:FP 10:1, the locked ratio).
Recall, flag rate, precision, cost with 95% percentile bootstrap CIs over lots (`harness.variants.lot_bootstrap_metrics`: 1000 reps, seed 20261003).
Also descriptive only (not used in the rule): per-family cost, and the lot-level verdict (ACCEPT / HOLD / REJECT at PDA 0.05, as the pipeline computes it
from the part verdicts) distribution per variant.

## SELECTION RULE (on validation only)
1. Candidates: variants with recall (flagged = not PASS) >= 0.90.
2. Among candidates choose the lowest cost per part; if two are within 0.005 in cost, the simpler wins: (d) > (c) > (b) > (a).
3. ADOPT the chosen variant only if (i) it is not (a) and (ii) its cost CI is separated from (a)'s: upper bound of the chosen variant's cost < lower bound of (a)'s cost.
   Otherwise keep (a) and say so; Part 3 is then skipped.
4. Evaluate (a) and the chosen variant ONCE on the published protocol (`generate_held_out_sets(seed=2026)`, 127 lots, the same lots as the system-level benchmark),
   both flag definitions, with CIs and per-family costs. No re-selection on the published protocol, whatever it shows.

Pre-declared reading of a tie: because (c) and (d) have identical verdicts, the rule names (d) whenever either wins. The product consequence is stated now:
if (d) is named, the implemented default role is `advisory` (the (c) behaviour), because Part 3c requires that a finished lot's notes still show Module B's
forecast as information when B no longer changes the verdict; `off` stays selectable. This is the one place the shipped default is not literally the
variant the rule names, and the report will say so.

## QA visibility (reported for the chosen variant)
Parts flagged in (a) only because of Module B and not flagged under the chosen variant: how many, and how a QA user can still see them (notes on the part,
what the lot dashboard and PDF show).

## Appended deviations
(none yet)

## RESULT (run 2026-10-04; data: docs/evidence_data/module_b_role/; script: scripts/module_b_role_experiment.py)

Nothing in the pre-registration was changed after the run. CHECK passed first: offline variant (a) equals `fusion.run_full_pipeline` on 385 of 385 parts (the first lot of each family, seed 7301).
Validation: seeds 7301-7305, 500 lots (100 per family), 38,500 parts, 2,492 defective. Published protocol: seed 2026, 127 lots, 9,779 parts, 521 defective (the same lots as the system-level benchmark; its (a) and (d) rows equal that benchmark's S-new and A-new rows exactly).
Cost = (10 x missed + false alarms) / parts; 95% CIs by bootstrap over lots (1000 reps).

### Validation, flagged = not PASS
| Variant | Flag rate | Recall [95% CI] | Precision | False alarms | Missed | Cost/part [95% CI] |
|---|---|---|---|---|---|---|
| (a) current | 0.259 | 0.968 [0.961, 0.975] | 0.242 | 7,573 | 79 | 0.217 [0.201, 0.233] |
| (b) tiered | 0.259 | 0.968 [0.961, 0.975] | 0.242 | 7,573 | 79 | 0.217 [0.201, 0.233] |
| (c) advisory | 0.099 | 0.916 [0.901, 0.930] | 0.602 | 1,510 | 209 | 0.094 [0.084, 0.105] |
| (d) off | 0.099 | 0.916 [0.901, 0.930] | 0.602 | 1,510 | 209 | 0.094 [0.084, 0.105] |

(b) equals (a) under "not PASS" because a B-only REVIEW is still WATCH, a flagged part; the two differ in the tier (REJECT only, below). Validation, flagged = REJECT only: (a) flag 0.245, recall 0.963, cost 0.207 [0.191, 0.223];
(b) 0.145, 0.948, 0.117 [0.107, 0.127]; (c) and (d) 0.077, 0.874, 0.102 [0.090, 0.115].
Per-family cost (not PASS) (a)/(b)/(c)=(d): altered correlation 0.190/0.190/0.080; baseline 0.163/0.163/0.074; different noise regime 0.385/0.385/0.080; higher defect prevalence 0.178/0.178/0.156; wider drift exponent 0.169/0.169/0.077.
Lot-level verdicts (descriptive, 500 lots): (a) REJECT 476, HOLD 15, ACCEPT 9; (b) 459/35/6; (c)=(d) 359/100/41.

### Decision (rule applied to the validation table only)
All four variants have recall >= 0.90. Lowest cost: (c) = (d) 0.0935. (c) and (d) are within 0.005, so the tie goes to the simpler, (d) (as stated in advance, the shipped default is then `advisory`: identical verdicts, forecast shown). The chosen variant's cost CI [0.0836, 0.1046] is entirely below (a)'s [0.2014, 0.2332]: separated. **ADOPT.**
Not free: on validation the chosen variant misses 209 defective parts against 79 for (a) (recall 0.916 against 0.968), and 130 more defects reach a finished-lot verdict of PASS; in exchange 6,063 fewer false alarms. At 10:1 that is cheaper; at a cost ratio of about 47:1 the order would reverse (marginal precision of the extra flags is 130 / 6,193 = 2.1%, a flag pays for itself at 1 / (ratio + 1)).

### Published protocol (seed 2026), evaluated once, no re-selection
| Variant | Flagged = | Flag rate | Recall [95% CI] | Precision | False alarms | Missed | Cost/part [95% CI] |
|---|---|---|---|---|---|---|---|
| (a) current | not PASS | 0.275 | 0.964 [0.947, 0.980] | 0.187 | 2,185 | 19 | 0.243 [0.212, 0.276] |
| (d) off = (c) | not PASS | 0.090 | 0.923 [0.902, 0.945] | 0.544 | 403 | 40 | 0.082 [0.069, 0.096] |
| (a) current | REJECT only | 0.260 | 0.954 [0.936, 0.973] | 0.195 | 2,048 | 24 | 0.234 [0.202, 0.268] |
| (d) off = (c) | REJECT only | 0.069 | 0.889 [0.865, 0.915] | 0.689 | 209 | 58 | 0.081 [0.064, 0.098] |
Per-family cost (not PASS), (a) against (d): altered correlation 0.207 / 0.072; baseline 0.200 / 0.074; different noise regime 0.377 / 0.094; higher defect prevalence 0.258 / 0.137; wider drift exponent 0.174 / 0.064.
The chosen variant is cheaper in every family on both protocols. (b) on the published protocol: not PASS identical to (a); REJECT only flag 0.145, recall 0.948, cost 0.123 [0.101, 0.147].
Published lot-level verdicts (127 lots): (a) REJECT 122, HOLD 5, ACCEPT 0; (d) REJECT 86, HOLD 27, ACCEPT 14.

### QA visibility
On the published protocol 1,803 parts are flagged in (a) and PASS under the chosen variant: 21 defective, 1,782 clean. All 1,803 had Module A tier PASS, i.e. they were flagged by Module B alone. A QA user still sees Module B on them: Part Detail shows the forecast, interval and drift (as before) and, new, an information note
("Module B forecast (information only) ... the forecast did not change it") on every finished-lot part whose forecast exceeds the safety slope; the PDF's methodology section states the role and the number of parts carrying such a note. The lot dashboard's flagged count and the lot verdict no longer include them (a part whose only flag was Module B's is PASS).

## Appended deviations
(none)
