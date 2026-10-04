# PPT numbers

## Module A scoring v2 (default from demo-v2)

From demo-v2 the app's default Module A scoring is **absolute scoring (V1F)**: each detector output becomes a tail probability (robust z-score
leg; MCD chi-square leg for lots of 77 or more parts), the part's severity is `s = -log10 p` of its most extreme leg (maximum rule, no
suppression), REVIEW at `s >= 2.956`, REJECT at `s >= 3.419` (thresholds tuned on tuning seed 6101, FN:FP 10:1). The previous scoring (within-lot percentile
+ maximum) stays available as `MODULE_A_SCORING=rank` and its sections below are marked **previous scoring (rank mode)**. The isolation forest and ECOD
contribute **no live score** in either mode (DISCLOSURES). All figures: synthetic data; commands: `python scripts/check_ppt_numbers.py` prints every number
below from the committed tables (`docs/evidence_data/adoption/`). **`s` is a severity index, never a probability.**

### Module A alone, published protocol (seed 2026, 9,779 parts, 521 defective, 127 lots, five families)

| Method | Flag rate | Recall [95% CI] | Cost/part [95% CI] | Source |
|---|---|---|---|---|
| V1F REVIEW (default from demo-v2) | 0.090 (884 flagged) | 0.923 [0.902, 0.945] | 0.082 [0.069, 0.096] | `v1f/fairness_table.csv` |
| V1F REJECT | 0.077 (757) | 0.912 [0.889, 0.935] | 0.076 [0.062, 0.091] | same |
| previous scoring (rank mode, live configuration), REVIEW | 0.183 (1,787) | 0.814 [0.775, 0.859] | 0.239 [0.208, 0.270] | same |
| static limits, default / cost-tuned | 0.002 / 0.151 | 0.040 / 0.610 | 0.511 / 0.327 | same |
| fixed delta, default / cost-tuned | 0.240 / 0.072 | 1.000 / 0.979 | 0.186 / **0.031** [0.018, 0.048] | same |
| static PAT, default / cost-tuned | 0.068 / 0.306 | 0.447 / 0.797 | 0.339 / 0.372 | same |
| dynamic PAT, default / cost-tuned | 0.032 / 0.088 | 0.591 / 0.898 | 0.219 / 0.094 [0.077, 0.112] | same |

"Cost-tuned" means the baseline's single cut was re-tuned with the same cost-sensitive optimiser on the same tuning data (seed 6101) as V1F's thresholds:
static limits at 0.439 of the limit, fixed delta at 2.075 times the default allowance, static PAT at 0.528, dynamic PAT at 0.488 of its 6-sigma limit
(about 2.9 sigma). The dynamic-PAT cut is close in size to V1F's z-score REVIEW cut (two-sided |z| about 3.26), so V1F's z-leg is similar in form to a tuned dynamic PAT.
The harness fixed-delta baseline is RELATIVE (a fraction of the 0h reading; `harness/industry_baselines.py`, `DeltaLimit.relative`), compared at every later checkpoint
against the 0h reading.

### The whole system (V1F + Module B + explainability gate + fusion rules), same lots

Flagged = part verdict is not PASS (WATCH or REJECT). Pre-registered in `docs/SYSTEM_LEVEL_BENCHMARK.md` before the run. Source: `system_level/system_headline.csv`.

| Method | Flag rate | Recall [95% CI] | Precision | False alarms | Missed | Cost/part [95% CI] |
|---|---|---|---|---|---|---|
| S-new: system with V1F (WATCH+REJECT) | 0.275 | 0.964 [0.946, 0.979] | 0.187 | 2,185 | 19 | 0.243 [0.212, 0.276] |
| S-new, REJECT only | 0.260 | 0.954 [0.935, 0.972] | 0.195 | 2,048 | 24 | 0.234 [0.202, 0.267] |
| S-old: system with the previous scoring (WATCH+REJECT) | 0.353 | 0.956 [0.935, 0.976] | 0.144 | 2,957 | 23 | 0.326 [0.297, 0.355] |
| S-old, REJECT only | 0.258 | 0.939 [0.914, 0.963] | 0.194 | 2,035 | 32 | 0.241 [0.209, 0.275] |
| A-new: Module A alone with V1F | 0.090 | 0.923 [0.903, 0.945] | 0.544 | 403 | 40 | 0.082 [0.069, 0.095] |
| D-tuned: cost-tuned fixed delta | 0.072 | 0.979 [0.966, 0.990] | 0.729 | 190 | 11 | 0.031 [0.018, 0.047] |
| P-tuned: cost-tuned dynamic PAT | 0.088 | 0.898 [0.872, 0.924] | 0.546 | 389 | 53 | 0.094 [0.078, 0.112] |

Gates, exactly as pre-registered: **G-flip holds** (cost 0.243 against 0.326 + 0.01; recall 0.964 against 0.956 - 0.03). **T1 did not fire** (recall gap to D-tuned 0.015, below
0.03). **T2 did not fire** (system cost is 0.212 above D-tuned, not within 0.03). Outcome: **neither**. Module B's effect: system cost minus Module A alone = +0.161 per part: the false-alarm load
of the fused system comes mainly from the Module B forecast leg. Cost per part by family (system with V1F / system with previous scoring / Module A alone with V1F): altered correlation 0.207 / 0.274 / 0.072;
baseline 0.200 / 0.298 / 0.074; different noise regime 0.377 / 0.429 / 0.094; higher defect prevalence 0.258 / 0.374 / 0.137; wider drift exponent 0.174 / 0.273 / 0.064.

### Clean-lot flag rate by lot size (through the app, absolute scoring, seed 7102)

n = 15: 0.100; 20: 0.073; 30: 0.044 [0.035, 0.052]; 40: 0.038; 50: 0.028; 60: 0.035; 77: 0.038; 100: 0.036; 150: 0.024 (`v1f/fr4_table.csv`). Lots of 15 to 29 parts flag 7 to 10% of clean parts; thresholds were tuned near 77-part lots.

### Sensitivity sweep (10 settings, 150 lots each, thresholds fixed, `v1f/sweep/`)

C1 (recall above static limits, static PAT and dynamic PAT), C2 (cost below static limits), C5 (flag rate at 1% prevalence at most 6%: REVIEW 0.049, REJECT 0.035), C6 (flag rate on clean lots at noise x2 at most 8%: 0.045) and C7 (cost no
worse than the previous scoring by more than 0.03; V1F is lower at every setting, by 0.11 to 0.22) **hold at all ten settings, for REVIEW and for REJECT**. These are verdicts on a sweep inside one generator, not on real data.

### Claims to make (each supported by the tables above)

1. Module A's false-alarm load is far lower than the previous scoring's, at higher recall: cost per part 0.239 -> 0.082, flag rate 0.183 -> 0.090, recall 0.814 -> 0.923 (Module A alone, synthetic benchmark).
2. Module A with V1F has lower cost per part than all four default-parameter baselines (0.082 against 0.186 to 0.511), and than cost-tuned static limits (0.327) and cost-tuned static PAT (0.372).
3. Module A with V1F is level with a cost-tuned dynamic PAT (0.082 [0.069, 0.096] against 0.094 [0.077, 0.112]; the intervals overlap).
4. The system result, exactly as measured: replacing the scoring lowers the system's cost per part from 0.326 to 0.243 at the same recall (0.956 to 0.964); the system's recall (0.964) is within 0.02 of a cost-tuned fixed delta (0.979) while its cost per part (0.243) is far above it (0.031); the Module B forecast leg adds 0.161 per part to the cost of Module A alone.
5. Cross-lot detection by an isolation forest is **designed** (and on the roadmap, `docs/CROSS_LOT_ROADMAP.md`); it is **not active** in the app.

### Claims NOT to make

- That Module A or the system beats the industry baselines. A cost-tuned fixed delta costs 0.031 against Module A's 0.082 and the system's 0.243 on this synthetic data; tuned dynamic PAT is level with Module A alone.
- That a cost-tuned fixed delta is beaten (T2 did not fire for the system, and Module A alone is 2.6 times more expensive).
- That severity is a probability. `s` is an index; the p-values behind it are not calibrated (the MCD leg is about 20 times nominal at n = 77), and the thresholds are tuned cutoffs.
- That cross-lot (isolation forest) detection is active in the app. It is not: no earlier lots are passed in, and the absolute scoring has no forest leg.
- That ECOD or the isolation forest contributes to a flag (neither produces a live score; the Part Detail ECOD view is labelled "not used for the flag").
- That any number here describes real parts: all numbers are synthetic, from the project's own generator; thresholds were tuned near 77-part lots.

### Previous scoring (rank mode): the sections below are the demo-v1.2 numbers, kept unchanged

## Status of this file (demo-v1.2; previous scoring, rank mode)

Numbers in the first sections are the **published benchmark configuration** (Isolation Forest active, history of earlier held-out lots). Numbers in the section "Added measurements" are the **live configuration** (no pooled reference, Isolation Forest inactive) and are the ones that describe the demo. Nothing below was changed at merge. One sentence in "Claims NOT to make" below (that the golden worked example through the live route is REJECT, not HOLD) predates the Module B guard: in demo-v1.2 that route gives HOLD, PDA 0.0390 (DISCLOSURES, "RESOLVED in demo-v1.2").

Every number on a slide must come from this file, and every number in this file comes from a committed harness table
(`harness/results/p18/*.csv`, regenerated by `python -m harness.comparison`). `python scripts/check_ppt_numbers.py` reads
those CSVs and prints each number used here; `python scripts/evaluate.py --format markdown` regenerates the headline table
from scratch and must equal the committed one (section "Regeneration check" below).

**Framing (the Lead's decision, "Option C"): reframe, do not claim to beat every baseline.** The harness does not support
"Module A beats the industry baselines" (`harness/results/p18/FINDINGS.md`). What it supports: Module A reaches much higher
recall than datasheet limits, static PAT and dynamic PAT, at a much higher review load, and it adds explanation,
cost-sensitive thresholds and cross-lot reasoning that those baselines do not have.

All figures: held-out benchmark of **9,779 parts, 521 defective**, five generator families, seed 2026, judged on the full
0h-168h Complete-lot series; cost is per part at FN:FP 10:1 (`harness/results/p18/comparison.md`, header).

**CONFIGURATION NOTE - benchmark versus live demo (Module A).** The benchmark ran Module A with a pooled cross-lot
reference and the Isolation Forest **active**: `harness/scoring.py:155-164` (`run_module_a`) calls
`detect(frames, prior_frames=list(history))` for each lot, where the history is every earlier lot of the same held-out
family (a family's first lot is a cold start with no forest). The live demo runs Module A **without** it:
`fusion/pipeline.py:72` calls `module_a_detect(frames)` with no `prior_frames`, so no forest is fitted and the score is the
max of robust z, MCD and ECOD only (all 77 Module A results of DEMO-COMPLETE-01 have `isolation_forest_score` = None). On a
4-lot sample (family `baseline`, 308 parts, seed 2026) the two configurations flag 63 versus 56 parts. Every Module A figure
below is therefore the benchmark configuration, not a measurement of the demo (DISCLOSURES #7). Say so if asked.

## Claims

| # | Claim text (slide wording) | Exact numbers | Source (file / column) | Caveat |
|---|---|---|---|---|
| 1 | Held-out benchmark size | 9,779 parts, 521 defective | `comparison.md` header; `headline.csv` `n_parts`; defective = fixed_delta `n_flagged` - `false_alarms` (2,344 - 1,823) | Synthetic data from the project's own generator, five held-out families. |
| 2 | Module A at REVIEW | recall 0.841; precision 0.184; flag rate 0.243 (2,378 flagged); cost/part 0.283 | `headline.csv` row `module_a_review`: `recall`, `precision`, `flag_rate`, `n_flagged`, `cost_per_part` | Roughly one part in four is flagged; 1,940 of the 2,378 flags are false alarms. |
| 3 | Module A at REJECT | recall 0.787; precision 0.205; flag rate 0.204 (1,998 flagged); cost/part 0.276 | `headline.csv` row `module_a_reject` | Pre-cap REJECT, as defined in `harness/comparison.py` (`comparison.md` header). |
| 4 | Recall versus static datasheet limits | Module A 0.841 vs 0.040. Baseline: precision 1.000, flag rate 0.002 (21 flagged) | `headline.csv` rows `module_a_review`, `static_limits`: `recall`, `precision`, `flag_rate` | The baseline is perfectly precise but almost never fires; Module A flags 0.243 of parts. |
| 5 | Recall versus static PAT | Module A 0.841 vs 0.447. Baseline: precision 0.350, flag rate 0.068 (666 flagged) | `headline.csv` rows `module_a_review`, `static_pat` | Module A's higher recall comes with 3.6x the flag rate. |
| 6 | Recall versus dynamic PAT | Module A 0.841 vs 0.591. Baseline: precision 0.972, flag rate 0.032 (317 flagged) | `headline.csv` rows `module_a_review`, `dynamic_pat` | See claim 8: dynamic PAT is far more precise and cheaper. |
| 7 | Fixed delta limits win on recall and cost | Fixed delta: recall 1.000, cost/part 0.186, precision 0.222, flag rate 0.240. Module A REVIEW: recall 0.841, cost/part 0.283 | `headline.csv` rows `fixed_delta`, `module_a_review` | Say this on the slide. The baseline's allowances come from the generator's own healthy-drift spread and every generated defect is a drift (`FINDINGS.md`, diagnosis 2), so real-world recall would be lower; how much lower cannot be measured here. |
| 8 | Dynamic PAT wins on precision and cost | Dynamic PAT: precision 0.972, cost/part 0.219. Module A REVIEW: precision 0.184, cost/part 0.283 | `headline.csv` rows `dynamic_pat`, `module_a_review`: `precision`, `cost_per_part` | Dynamic PAT's recall is 0.591: it is precise because it flags few parts. |
| 9 | Matched flag budget: at the same number of flags Module A has LOWER recall than every baseline | static limits (21 flags): 0.029 vs 0.040. static PAT (666): 0.409 vs 0.447. dynamic PAT (317): 0.307 vs 0.591. fixed delta (2,344): 0.833 vs 1.000 | `matched_flag_budget.csv`: `baseline_recall`, `module_a_recall` (precision columns: 0.714 vs 1.000, 0.320 vs 0.350, 0.505 vs 0.972, 0.185 vs 0.222) | This is the honest counterweight to claims 4-6: Module A's recall edge is bought with a larger flag budget, not better ranking at equal budget. |
| 10 | By defect archetype, Module A REVIEW has the highest recall of the three non-oracle baselines | early saturating 0.859, latent post-24h 0.750, progressive 0.924; best of static/PAT/DPAT 0.558, 0.441, 0.788 (all dynamic PAT) | `archetype_recall.csv`: `recall` by `defect_type` | Fixed delta is 1.000 on all three; at a higher flag rate than the baselines (claim 4-6 caveats). |
| 11 | What Module A adds: an explanation for every flag | Per-part plain-language sentence, robust-z table, MCD per-parameter contribution (Module A); TreeSHAP for Module B | Evidence: `tests/unit/explain/` (all pass, run in the full suite); Part Detail screenshots `frontend/screenshots/rehearsal/` | The baselines return a flag or a score only. Explanations are not scored by the harness. |
| 12 | What Module A adds: thresholds that follow a cost ratio | FN:FP 10:1 sets the REVIEW/REJECT thresholds (REVIEW 0.955628, REJECT 0.964286) | `config/harness_thresholds.yaml`; `FINDINGS.md` header | The 10:1 ratio is a disclosed default, not derived from field failure data (context.md Part 8). |
| 13 | What Module A adds: cross-lot reasoning | Module A scores each part against its own lot; the golden example (10 uA lot median, 45 uA part, 50 uA limit) is flagged REJECT while static limits (0.9 of the limit) and fixed delta (the part never drifts) miss it | `golden_example.csv` rows `static_limits`, `fixed_delta`, `module_a`; the golden test `tests/integration/test_golden_module_a.py` (never regresses) | Dynamic PAT also flags the golden example (score 2.625). The "cross-lot" pooled reference is NOT supplied by the live pipeline (DISCLOSURES #7, #25): the claim is within-lot reasoning, not cross-lot history. |
| 14 | Limit: Module A's shipped combination is not the best of the bake-off | Mean held-out cost: max 0.344 (shipped), weighted average 0.190, meta-model 0.146 | `combination_bakeoff.csv`: `mean_held_out_cost`, `shipped` | `max` is shipped because the fitted meta-model breaks "an explainable detector must corroborate a REJECT" (DISCLOSURES #5). |
| 15 | Limit: Module B beats the physics baselines but its intervals under-cover on one family | Beats the best physics baseline in 15/15 cells at 24h and 10/15 at 96h; median coverage 0.870 (24h) and 0.839 (96h) against a 0.90 target; minimum 0.498 (24h) and 0.437 (96h, `different_noise_regime` leakage) | `module_b_summary.csv`: `model_beats_best`, `cells`, `median_coverage`, `min_coverage`; `module_b_vs_physics.csv`: `target_coverage` | Calibrated on one measurement scale (DISCLOSURES #2); one threshold only (#1). |

## CLAIMS NOT TO MAKE

- "Module A beats the industry baselines." It does not: it loses to fixed delta limits on recall and cost, to dynamic PAT on
  precision and cost, and to every baseline on recall at a matched flag budget (claim 9).
- "Module A has high precision." Its precision is 0.184 (REVIEW) and 0.205 (REJECT); a healthy-looking lot still shows about
  one flagged part in six (DISCLOSURES #3).
- "Module A is better than dynamic PAT." The golden example does not separate them: dynamic PAT flags it too.
- Anything about Module B at REVIEW or a Module B WATCH: Module B has one threshold and answers PASS or REJECT only
  (DISCLOSURES #1).
- "Module B is accurate on real customer data." It is validated only on the generator's measurement scale
  (DISCLOSURES #2); the golden worked example through the live route is REJECT, not HOLD.
  **Correction (2026-10-03, session I2a):** that last clause is FALSE as of demo-v1.2. Through `POST /lots` the golden
  fixture is now HOLD with PDA 0.03896 (the Module B guard; DISCLOSURES, "RESOLVED in demo-v1.2"). Do not claim REJECT
  for the golden example through the live route. No measured number in this file was changed.
- "The 90% interval is reliable." Coverage is 0.437 to 0.605 on `different_noise_regime` (DISCLOSURES #6).
- "Cross-lot learning / pooled history is used." The live pipeline supplies no pooled reference (DISCLOSURES #7, #25).
- "Fixed delta limits are a weak baseline." It scores recall 1.000 here (claim 7); do not imply otherwise.
- Any figure not in this file.

## Regeneration check

`python scripts/evaluate.py --format markdown` was run once on an idle machine on 2026-10-02 (output below) and its headline table equals `headline.csv`. `python scripts/check_ppt_numbers.py` output is in section
"check_ppt_numbers.py output".

### evaluate.py output

`python scripts/evaluate.py --format markdown`, run once on an idle machine (Windows 11, Python 3.11.16): 460 seconds
(7 min 40 s). The table equals the `## headline` section of `harness/results/p18/comparison.md` byte for byte.

#### headline

| method | n_parts | evaluable_share | n_flagged | flag_rate | recall | precision | false_alarms | missed | cost_per_part |
|---|---|---|---|---|---|---|---|---|---|
| static_limits | 9779 | 1.000 | 21 | 0.002 | 0.040 | 1.000 | 0 | 500 | 0.511 |
| fixed_delta | 9779 | 1.000 | 2344 | 0.240 | 1.000 | 0.222 | 1823 | 0 | 0.186 |
| static_pat | 9779 | 1.000 | 666 | 0.068 | 0.447 | 0.350 | 433 | 288 | 0.339 |
| dynamic_pat | 9779 | 1.000 | 317 | 0.032 | 0.591 | 0.972 | 9 | 213 | 0.219 |
| module_a_review | 9779 | 1.000 | 2378 | 0.243 | 0.841 | 0.184 | 1940 | 83 | 0.283 |
| module_a_reject | 9779 | 1.000 | 1998 | 0.204 | 0.787 | 0.205 | 1588 | 111 | 0.276 |

### check_ppt_numbers.py output

```
held-out parts: 9779; defective (fixed_delta catches all: flagged - false_alarms): 521

[headline.csv] method | flag_rate | recall | precision | cost_per_part | n_flagged | false_alarms | missed
static_limits    0.002 0.040 1.000 0.511 21 0 500
fixed_delta      0.240 1.000 0.222 0.186 2344 1823 0
static_pat       0.068 0.447 0.350 0.339 666 433 288
dynamic_pat      0.032 0.591 0.972 0.219 317 9 213
module_a_review  0.243 0.841 0.184 0.283 2378 1940 83
module_a_reject  0.204 0.787 0.205 0.276 1998 1588 111

[recall gap, Module A REVIEW minus baseline] (percentage points)
static_limits  baseline recall 0.040 vs Module A 0.841; baseline flag_rate 0.002 vs Module A 0.243; baseline precision 1.000 vs Module A 0.184
static_pat     baseline recall 0.447 vs Module A 0.841; baseline flag_rate 0.068 vs Module A 0.243; baseline precision 0.350 vs Module A 0.184
dynamic_pat    baseline recall 0.591 vs Module A 0.841; baseline flag_rate 0.032 vs Module A 0.243; baseline precision 0.972 vs Module A 0.184

[matched_flag_budget.csv] baseline | n_flagged | baseline_recall | module_a_recall | baseline_precision | module_a_precision
static_limits  21 0.040 0.029 1.000 0.714
fixed_delta    2344 1.000 0.833 0.222 0.185
static_pat     666 0.447 0.409 0.350 0.320
dynamic_pat    317 0.591 0.307 0.972 0.505

[archetype_recall.csv] module_a_review vs best baseline per archetype
early_saturating   module_a_review 0.859; best of static/PAT/DPAT dynamic_pat 0.558; fixed_delta 1.000
latent_post_24h    module_a_review 0.750; best of static/PAT/DPAT dynamic_pat 0.441; fixed_delta 1.000
progressive        module_a_review 0.924; best of static/PAT/DPAT dynamic_pat 0.788; fixed_delta 1.000

[combination_bakeoff.csv]
max               mean_held_out_cost 0.344 shipped=True
weighted_average  mean_held_out_cost 0.190 shipped=False
meta_model        mean_held_out_cost 0.146 shipped=False

[module_b_summary.csv]
24h: model beats best physics baseline in 15/15 cells; median coverage 0.870; min coverage 0.498
96h: model beats best physics baseline in 10/15 cells; median coverage 0.839; min coverage 0.437
target coverage: [np.float64(0.9)]
lowest-coverage cell: different_noise_regime / leakage / 96h = 0.437
```


## Added measurements (all on synthetic held-out data)

Added in session M1 (`docs/EVIDENCE_MEASUREMENTS.md`, pre-registered in `docs/EVIDENCE_PLAN.md`). Nothing above this heading was
changed. Every figure is synthetic-generator data; none of it says anything about real parts. Source column: files under
`docs/evidence_data/`.

| # | Claim text (slide wording) | Exact numbers | Source | Caveat |
|---|---|---|---|---|
| A1 | Module B's predicted 168h versus the measured 168h, against naive extrapolation | Relative MAE 4.88% (95% CI 4.52-5.27) against 5.25% for persistence, the best naive baseline (7.0% better). 200 lots (40 per family), 0h+24h readings | `module_b_mae_summary.csv` (family ALL, parameter ALL, mode 24h); `module_b_mae_verdict.json` | The pre-registered target was a 10% gain and it was NOT met (M1 = FAIL). 150-lot run: 8.0% (`module_b_mae_150lots_verdict.json`). |
| A2 | Module B wins most family x parameter cells | Beats the best of five baselines in 12 of 15 cells at 24h and 13 of 15 at 96h (absolute MAE) | `module_b_mae_summary.csv` | The three losses at 24h are all `different_noise_regime`. Margins are about 2.5 to 10% per cell. |
| A3 | Module B on defective parts | Relative MAE 27.8% on defective parts against 30.7% for persistence; 3.5% against 3.7% on healthy parts | `module_b_mae_summary.csv` columns `rel_mae_defective_pct`, `rel_mae_healthy_pct` | Most of the aggregate accuracy is on healthy parts. |
| A4 | Module B interval coverage | Pooled coverage 0.78 against a 0.90 target (0h+24h); 0.55 on `different_noise_regime` | `module_b_mae_summary.csv` column `coverage` | Under-covers; consistent with DISCLOSURES #6. |
| A5 | Module A in the configuration the app runs (no pooled reference, Isolation Forest inactive) | REVIEW: flag rate 0.183 (1,787 flagged), recall 0.814, precision 0.237, cost/part 0.239. REJECT (pre-cap): flag rate 0.154, recall 0.758, precision 0.262, cost/part 0.242. Same 9,779 parts / 521 defective as the published table | `live_benchmark/headline_live.csv` | Shipped thresholds, not re-tuned for this configuration. Replaces the 4-lot "63 versus 56" sample in the configuration note above as the measured difference. |
| A6 | Published (pooled reference) versus live configuration | Cost/part REVIEW 0.283 versus 0.239 (difference 0.045, 95% CI 0.032-0.057); recall 0.841 versus 0.814; flag rate 0.243 versus 0.183 | `live_benchmark/headline_published.csv`, `headline_live.csv`, `per_family_published_minus_live.csv`, `decision.json` | By the pre-registered rule: "the Isolation Forest matters" (difference above 0.01 at REVIEW and REJECT), in the direction that the forest raises cost. |
| A7 | The app and the harness compute the same Module A severities | 385 parts on 5 lots; maximum absolute difference of combined severity 0.0; 0 tier mismatches | `config_check.json` | Compares each part's worst-parameter result. |
| A8 | Module A recall versus the three baselines under different generator assumptions | Module A REVIEW recall 0.784 to 0.978 across 10 settings, above static limits, static PAT and dynamic PAT in all 10 (claim C1 holds; REJECT tier holds) | `sensitivity/summary__live.csv`, `claims__live.json` | Settings: noise x0.5/x2, prevalence 1/3/8%, drift exponent range lower/higher, lot size 30/150, plus baseline; live configuration; 150 lots each. |
| A9 | Module A's flag rate does not fall with prevalence | REVIEW flag rate 0.170 to 0.196 at all settings; at 1% prevalence precision 0.062 (recall 0.978) | `sensitivity/summary__live.csv` | Claim C3 holds. Structural, see DISCLOSURES #3. |
| A10 | Where Module A's cost advantage over static limits breaks | At 1% prevalence cost/part REVIEW 0.173, REJECT 0.146 against 0.108 for static limits; Module A is cheaper at the other nine settings | `sensitivity/summary__live.csv`, `claims__live.json` (C2) | |
| A11 | Dynamic PAT stays high-precision | Precision 0.957 or higher at every setting (lowest at 1% prevalence) | `sensitivity/summary__live.csv` (C4) | Its recall stays about 0.60 to 0.66. |

### Added claims NOT to make

- "Module B beats naive baselines by 10 percent or more", or "substantially". The measured gain is 7.0% (A1) and the pre-registered 10% target failed.
- "Module B wins on every generator family." On `different_noise_regime` it loses to persistence by 10.6% (pooled relative MAE; 40-lot run).
- "Module B forecasts defective parts accurately." Its error on defective parts is about 28% (A3).
- "The Isolation Forest improves detection" or "cross-lot learning is demonstrated". On this data it costs more than it gains (A6); the generator has no campaign-level drift across lots to test it on.
- "The published benchmark numbers describe the demo." The demo's configuration is A5.
- "Module A is the cheapest method" under any setting: fixed delta limits or dynamic PAT are cheaper at every one of the ten settings.
- "Module A holds up at low prevalence on cost." It does not beat static limits on cost at 1% prevalence (A10), and precision is 0.062 there.
- "Robust to any generator assumption" or any statement about real data: the sweep varies values inside one generator structure.
