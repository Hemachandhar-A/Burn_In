# Evidence measurements (session M1)

Three pieces of evidence for the PPT and the judges, all measured on SYNTHETIC held-out data, none changing shipped
behaviour. The pass criteria were written and committed before any measurement (`docs/EVIDENCE_PLAN.md`, commit a5115b3,
with three clarifications D1-D3 recorded there before the sensitivity runs). Every number below is read from a committed
file under `docs/evidence_data/` by a generator, not typed by hand. The claims these measurements support are appended to
`docs/PPT_NUMBERS.md` (A1-A11, with the claims NOT to make) and the limitations to `docs/DISCLOSURES.md` (#27-#29). Negative results are reported as they came out.

Machine and tooling: Windows 11 Home (10.0.26100), Python 3.11.17, uv 0.12.22, Node 22.21.1; repo at tag demo-v1.1
(700ac73), branch `evidence-measurements`. Run Python as `PYTHONPATH=. uv run python -m scripts.<name>` (the plain
`python scripts/evaluate.py` form needs `PYTHONPATH=.` on this machine, or `-m scripts.evaluate`).

## Part 0: baseline checks

| Check | Result |
|---|---|
| Golden test (`tests/integration/test_golden_module_a.py`, temp DB) | 4 passed in 24.02 s |
| `scripts/evaluate.py --format markdown` before any edit | 568 s; headline table identical to `harness/results/p18/comparison.md` (empty diff, CR stripped) |


## Piece 1: Module B drift-prediction accuracy (MAE of predicted 168h)

**What was done.** `scripts/module_b_mae.py` generates 40 complete lots per generator family (five families, 77 parts,
three parameters, so 9,240 part-parameter predictions per family per input mode), runs `module_b.predict` (the call
`fusion.run_full_pipeline` makes) on each lot with the 0h+24h reading only and with 0h+24h+96h, and scores against the
MEASURED 168h reading (what a judge's hidden Value_168h would be). It also reports the error against the noise-free true
168h from the generator sidecar (never a model input). Raw per-part errors: `docs/evidence_data/module_b_mae_raw.csv.gz`;
summary: `module_b_mae_summary.csv`; verdict: `module_b_mae_verdict.json`. A 150-lot run (`module_b_mae_150lots_*`) checks that
the result is not a small-sample artefact.

**Was a MAE table already there?** Yes: `harness/results/p18/module_b_vs_physics.csv` and `module_b_summary.csv` (absolute MAE
per family x parameter x horizon against persistence, linear and the lot-fitted power law; the model beat the best of those
in 15 of 15 cells at 24h). This measurement adds the fixed-exponent power law, a lot-median drift baseline, relative
(pooled) MAE, healthy/defective splits, bootstrap CIs and the leakage check. Reconciliation: against the best of all five
baselines the model wins 12 of 15 family x parameter cells at 24h (13 of 15 at 96h; 150-lot run: 12 of 15 at 24h).
The 15-of-15 in the old table counts three baselines only; the fixed-exponent power law (c) is the strongest competitor
in most cells and the win margins are small (about 2.5 to 10 percent per cell), which the old table also showed
(its gain column ranges from 0.2 to 11 percent).

**Leakage control (checked before any scoring).** `module_b.predictor.synthetic_models(part_number)` trains the model on
`SYNTHETIC_LOTS` = 14 complete lots of the BASELINE family with seeds 0..13 and lot ids
`SYNTHETIC-<part number>-<seed>`; calibration inside it is split by lot (`module_b/calibration.py`). Each generated lot is a
pure function of `SeedSequence([seed, sha256(lot_id), sha256(part_number)])` (`generator/lot.py:_lot_seed`). The evaluation
lots here use seed 7001, lot ids `M1-<family>-<index>` and part number `PN-M1`. Disjointness is guaranteed by
construction and asserted at the start of every run (`assert_disjoint_from_training`, aborts on failure): the (seed, lot id)
pairs share no element, the derived lot seeds share no element (overlap = 0 of 200 evaluation
lots against 14 training lots), and the evaluation seed is outside 0..13. The seed is not the harness seed 2026 (ids `HO-...`) on which the thresholds and the earlier
Module B reports were built, and nothing in this session was tuned on these lots. Four of the five families (wider_drift_exponent,
higher_defect_prevalence, different_noise_regime, altered_correlation) are structurally different from the training
family, so they are genuinely held out; the `baseline` family is the training DISTRIBUTION (fresh lots, same process), so
it is in-distribution and is not part of the held-out clause of the criterion.

**Commands.**

```
PYTHONPATH=. uv run python -m scripts.module_b_mae                      # 40 lots/family, 35 s
PYTHONPATH=. uv run python -m scripts.module_b_mae --lots 150 --out <dir> --cache <dir>   # 101 s
```

**Baselines** (same inputs as the model, no training): (a) persistence = the latest reading the mode allows (the 24h value
in the 0h+24h mode); (b) straight line through 0h and the latest reading; (c) v0 + (v_last - v0) x ((168 - t0)/(t_last - t0))^0.22
with the fixed exponent n = 0.22, the "literature median" value the session brief specified. The repository itself cites only the
0.15-0.30 spread (LJMU Fig. 1a; `context.md` 1.4, `module_b/baselines.py`), inside which 0.22 sits, and uses 0.25 as its own default;
I found no separate citation for 0.22 in the repo, so treat the 0.22 as the brief's choice, not an independently sourced number; (d) lot-median relative drift: per lot and parameter m = median over the parts of
(v_last - v0)/v0, each part predicted as v0 x (1 + m x ratio^0.22); (e) the app's own lot-fitted power law (`module_b/baselines.py`),
added as a stricter comparator than the brief asked for.

### Pooled result, 0h+24h mode (the pre-registered basis); relative MAE vs measured 168h, 95% CI over lots

| method | relative MAE % | healthy % | defective % | interval coverage | mean width |
|---|---|---|---|---|---|
| Module B | 4.88 [4.52, 5.27] | 3.49 | 27.8 | 0.784 | 2.20 |
| (a) persistence | 5.25 [4.94, 5.57] | 3.71 | 30.7 |  |  |
| (b) linear | 31.65 [29.51, 34.13] | 29.35 | 69.7 |  |  |
| (c) power law n=0.22 | 5.44 [5.03, 5.91] | 4.07 | 28.1 |  |  |
| (d) lot-median drift | 6.18 [5.73, 6.66] | 4.12 | 40.1 |  |  |
| (e) app lot-fitted power law | 5.67 [5.22, 6.17] | 4.30 | 28.3 |  |  |

### Pooled result, 0h+24h+96h mode

| method | relative MAE % | healthy % | defective % | interval coverage | mean width |
|---|---|---|---|---|---|
| Module B | 3.62 [3.36, 3.92] | 2.96 | 14.5 | 0.789 | 1.54 |
| (a) persistence | 3.75 [3.50, 4.03] | 2.91 | 17.7 |  |  |
| (b) linear | 6.18 [5.80, 6.62] | 5.49 | 17.7 |  |  |
| (c) power law n=0.22 | 3.81 [3.54, 4.12] | 3.03 | 16.7 |  |  |
| (d) lot-median drift | 5.75 [5.41, 6.08] | 3.68 | 40.0 |  |  |
| (e) app lot-fitted power law | 4.11 [3.80, 4.47] | 3.33 | 16.9 |  |  |

### Per family, 0h+24h mode (model against that family's best of (a)-(e))

| family | Module B rel MAE % | best baseline | best baseline rel MAE % | ratio B / best | coverage |
|---|---|---|---|---|---|
| baseline | 3.240 | (c) power law n=0.22 | 3.530 | 0.917 | 0.847 |
| wider_drift_exponent | 3.640 | (c) power law n=0.22 | 4.070 | 0.895 | 0.851 |
| higher_defect_prevalence | 5.590 | (c) power law n=0.22 | 5.940 | 0.940 | 0.818 |
| different_noise_regime | 8.530 | (a) persistence | 7.710 | 1.106 | 0.549 |
| altered_correlation | 3.390 | (c) power law n=0.22 | 3.740 | 0.905 | 0.855 |
| ALL_HELD_OUT | 5.290 | (a) persistence | 5.620 | 0.940 | 0.768 |
| ALL | 4.880 | (a) persistence | 5.250 | 0.930 | 0.784 |

### Per parameter in the parameter's own unit, all families, 0h+24h mode

| parameter | method | MAE vs measured 168h | MAE vs true 168h | relative MAE % |
|---|---|---|---|---|
| iddq (uA) | Module B | 1.384 [1.235, 1.526] | 1.242 | 6.700 |
| iddq (uA) | (a) persistence | 1.509 [1.347, 1.671] | 1.387 | 6.860 |
| iddq (uA) | (b) linear | 6.965 [6.348, 7.635] | 6.939 | 41.290 |
| iddq (uA) | (c) power law n=0.22 | 1.477 [1.329, 1.624] | 1.361 | 7.200 |
| iddq (uA) | (d) lot-median drift | 1.817 [1.626, 2.019] | 1.709 | 8.100 |
| iddq (uA) | (e) app lot-fitted power law | 1.519 [1.369, 1.668] | 1.410 | 7.500 |
| leakage (nA) | Module B | 0.467 [0.419, 0.522] | 0.419 | 5.740 |
| leakage (nA) | (a) persistence | 0.519 [0.466, 0.576] | 0.480 | 6.420 |
| leakage (nA) | (b) linear | 2.512 [2.266, 2.787] | 2.508 | 39.590 |
| leakage (nA) | (c) power law n=0.22 | 0.524 [0.471, 0.582] | 0.485 | 6.870 |
| leakage (nA) | (d) lot-median drift | 0.617 [0.552, 0.688] | 0.581 | 7.560 |
| leakage (nA) | (e) app lot-fitted power law | 0.540 [0.484, 0.600] | 0.503 | 7.160 |
| prop_delay (ns) | Module B | 0.154 [0.137, 0.173] | 0.145 | 2.200 |
| prop_delay (ns) | (a) persistence | 0.172 [0.155, 0.189] | 0.165 | 2.460 |
| prop_delay (ns) | (b) linear | 0.828 [0.770, 0.896] | 0.829 | 14.080 |
| prop_delay (ns) | (c) power law n=0.22 | 0.158 [0.141, 0.174] | 0.150 | 2.260 |
| prop_delay (ns) | (d) lot-median drift | 0.204 [0.183, 0.226] | 0.198 | 2.870 |
| prop_delay (ns) | (e) app lot-fitted power law | 0.162 [0.145, 0.178] | 0.155 | 2.340 |

The full table (every family x parameter x mode x method, with CIs, healthy and defective splits, coverage and interval width)
is `module_b_mae_summary.csv`.

### Verdict against the pre-registered criterion

M1 PASS required: pooled MAE beats the best naive baseline by at least 10 percent AND loses on no held-out family by more than 10 percent.

| Measure | 40 lots/family (pre-registered run) | 150 lots/family (robustness) |
|---|---|---|
| Best naive baseline, pooled | persistence (5.25 %) | persistence (5.41 %) |
| Module B pooled | 4.88 % | 4.98 % |
| Improvement over the best baseline | 7.0 % (needs >= 10) | 8.0 % |
| Worst held-out family ratio (Module B / best baseline) | different_noise_regime 1.106 (loses by more than 10 percent: True) | different_noise_regime 1.069 |
| Same result against baselines (a)-(d) only | improvement 7.0 %, M1_PASS = False | |
| **M1** | **FAIL** | PASS = False |

**What it means.** Module B is better than every naive baseline on average, by about 7 percent (8 percent at 150 lots), not by
10. The model and the best baseline have overlapping confidence intervals in the pooled table, and on
`different_noise_regime` it is worse than "predict no further change" (ratio 1.11). The
pre-registered "beats by at least 10 percent" fails. Two further points a judge could find: on DEFECTIVE parts (the ones the
forecast is for) the model's relative MAE is 27.8 % against 30.7 % for persistence,
so most of its aggregate accuracy is on healthy parts that barely move; and its 90 percent interval covers
0.78 of measured values pooled (0.55 on `different_noise_regime`), below target.

**What to say on a slide:** "On 200 fresh synthetic lots (disjoint from Module B's training lots), predicted 168h is within
4.9 % of the measured value on average (MAE, 0h+24h readings), against 5.2 % for the best
naive extrapolation - a small, consistent edge, ahead in 12 of 15 family x parameter cells." **What not to say:** that it
"substantially beats" or "is 10 percent better than" naive methods; that it wins on every family; that it is accurate on real
data; that its 90 percent interval is reliable; that it forecasts defective parts well (about 28 % error there).

**Limits.** Synthetic data from the same generator family the model's prior is trained on; the error against the measured
168h includes irreducible measurement noise (against the noise-free true value the absolute errors are 6 to 10 percent smaller,
column "MAE vs true 168h"); relative MAE weights parts by 1/value, and the three parameters are pooled with equal part weight.

## Piece 2: the benchmark in the LIVE configuration (Isolation Forest inactive)

**What was done.** Code reading first: `harness/scoring.py` (`run_module_a`) calls `detect(frames, prior_frames=list(history))`
with every earlier lot of the family as history, so the Isolation Forest is active from a family's second lot; the app's
pipeline (`fusion/pipeline.py:72`) calls `module_a_detect(frames)` with no `prior_frames`, so it is inactive. Two optional
parameters were added with defaults that reproduce today's behaviour exactly: `scripts/evaluate.py --no-pooled-reference`
(passes no prior_frames) and `--max-history K` (the K most recent earlier lots), threaded through
`harness.scoring.run_module_a`, `module_a_table` and `harness.comparison.part_table`. Tests
(`tests/unit/harness/test_live_configuration.py`) show the default output is identical to the pre-change implementation
(full ModuleAResult equality) and that the live switch changes only the Isolation Forest component (robust z, MCD and ECOD
identical; forest score None). Thresholds are the shipped ones in both configurations; nothing was re-tuned. Because the
thresholds were derived with the forest active, the live numbers are not threshold-optimised for the live configuration.

**M3 config check (pre-registered).** The app pipeline (`fusion.run_full_pipeline`, no prior_frames) and the harness live path
were run on 5 generated lots (one per family): 385 parts compared, maximum absolute difference of
`combined_severity` = 0.0, `severity_tier` mismatches = 0. Criterion < 1e-9: **PASS**.
(`scripts/config_check.py`, 15 s, `docs/evidence_data/config_check.json`. The app exposes the Module A result of each part's worst
parameter, so that is what is compared.)

**Commands.**

```
PYTHONPATH=. uv run python -m scripts.live_benchmark run --config published|live|hist2|hist5|hist10
PYTHONPATH=. uv run python -m scripts.live_benchmark report
PYTHONPATH=. uv run python scripts/evaluate.py --format markdown --no-pooled-reference     # same via the CLI
```

Seconds: live 111 s; published, hist2, hist5, hist10 about 1,740 s each when run together with the live run (5 processes on 8
logical cores; the published run alone took 568 s in Part 0). The published configuration re-run reproduces the committed
headline table exactly (`docs/evidence_data/live_benchmark/headline_published.csv`).

### Module A, all configurations (9,779 held-out parts, 521 defective, seed 2026; FN:FP 10:1)

| configuration | method | n_flagged | flag_rate | recall | precision | false_alarms | missed | cost_per_part |
|---|---|---|---|---|---|---|---|---|
| published | module_a_review | 2378 | 0.243 | 0.841 | 0.184 | 1940 | 83 | 0.283 |
| published | module_a_reject | 1998 | 0.204 | 0.787 | 0.205 | 1588 | 111 | 0.276 |
| live | module_a_review | 1787 | 0.183 | 0.814 | 0.237 | 1363 | 97 | 0.239 |
| live | module_a_reject | 1505 | 0.154 | 0.758 | 0.262 | 1110 | 126 | 0.242 |
| hist2 | module_a_review | 2234 | 0.228 | 0.839 | 0.196 | 1797 | 84 | 0.270 |
| hist2 | module_a_reject | 1862 | 0.190 | 0.777 | 0.218 | 1457 | 116 | 0.268 |
| hist5 | module_a_review | 2382 | 0.244 | 0.837 | 0.183 | 1946 | 85 | 0.286 |
| hist5 | module_a_reject | 1998 | 0.204 | 0.775 | 0.202 | 1594 | 117 | 0.283 |
| hist10 | module_a_review | 2405 | 0.246 | 0.841 | 0.182 | 1967 | 83 | 0.286 |
| hist10 | module_a_reject | 1991 | 0.204 | 0.779 | 0.204 | 1585 | 115 | 0.280 |

The four baselines are identical in every configuration (static_limits recall 0.040 cost 0.511;
fixed_delta 1.000 / 0.186; static_pat 0.447 / 0.339;
dynamic_pat 0.591 / 0.219), as they do not use Module A.

`--max-history`: all three runs (2, 5, 10 earlier lots) were run on the full benchmark, not a sample.

### Cost per part, published minus live, per family (positive = the forest costs more); 95% CI from a paired lot bootstrap

| family | method | cost_published | cost_live | cost_published_minus_live | ci_lo | ci_hi | recall_published | recall_live | flag_rate_published | flag_rate_live |
|---|---|---|---|---|---|---|---|---|---|---|
| altered_correlation | module_a_review | 0.242 | 0.198 | 0.044 | 0.010 | 0.073 | 0.879 | 0.848 | 0.225 | 0.162 |
| altered_correlation | module_a_reject | 0.235 | 0.213 | 0.023 | -0.019 | 0.052 | 0.818 | 0.778 | 0.182 | 0.135 |
| baseline | module_a_review | 0.251 | 0.192 | 0.059 | 0.046 | 0.072 | 0.885 | 0.885 | 0.240 | 0.181 |
| baseline | module_a_reject | 0.221 | 0.173 | 0.048 | 0.036 | 0.060 | 0.865 | 0.865 | 0.201 | 0.153 |
| different_noise_regime | module_a_review | 0.262 | 0.210 | 0.052 | 0.026 | 0.074 | 0.899 | 0.869 | 0.257 | 0.190 |
| different_noise_regime | module_a_reject | 0.255 | 0.213 | 0.042 | 0.013 | 0.067 | 0.838 | 0.798 | 0.222 | 0.161 |
| higher_defect_prevalence | module_a_review | 0.568 | 0.596 | -0.028 | -0.100 | 0.036 | 0.686 | 0.628 | 0.247 | 0.192 |
| higher_defect_prevalence | module_a_reject | 0.652 | 0.665 | -0.013 | -0.062 | 0.034 | 0.603 | 0.562 | 0.211 | 0.165 |
| wider_drift_exponent | module_a_review | 0.256 | 0.205 | 0.051 | 0.032 | 0.068 | 0.888 | 0.878 | 0.246 | 0.190 |
| wider_drift_exponent | module_a_reject | 0.237 | 0.199 | 0.038 | 0.018 | 0.055 | 0.847 | 0.827 | 0.206 | 0.158 |
| ALL | module_a_review | 0.283 | 0.239 | 0.045 | 0.032 | 0.057 | 0.841 | 0.814 | 0.243 | 0.183 |
| ALL | module_a_reject | 0.276 | 0.242 | 0.034 | 0.021 | 0.045 | 0.787 | 0.758 | 0.204 | 0.154 |

**M3 decision rule.** |published - live| cost per part: REVIEW 0.045, REJECT 0.034;
threshold 0.01 at both. Verdict: **"the Isolation Forest matters"**.

**What it shows.** The Isolation Forest, as configured, makes the benchmark WORSE on cost, not better: with it Module A REVIEW flags
24.3% of parts (recall 0.841, cost 0.283); without it 18.3% (recall 0.814, cost 0.239). It buys
2.7 points of recall for 577 more false alarms. The cost
rises with the amount of pooled history (hist2 0.270, hist5 0.286, hist10 0.286, all earlier lots 0.283, none 0.239).

**Per family and the design intent.** The forest's design intent is to catch campaign-level drift across lots. Four families
(baseline, altered_correlation, different_noise_regime, wider_drift_exponent) show a cost increase with the forest whose CI excludes
zero at REVIEW (baseline 0.059, noise 0.052, wider exponent 0.051, altered correlation 0.044), and in `baseline` the recall is the
same with and without it (0.885): it only adds false alarms. The one family where the forest raises recall materially is
`higher_defect_prevalence` (0.628 live to 0.686 published); there the cost difference is -0.028 with a CI
([-0.100, 0.036]) that includes zero. That family is a
contamination regime (the lot median itself is pulled by defects), not campaign-level drift across lots. **No family in the
generator contains campaign-level drift across lots: every lot is an independent draw (the seed mixes the lot id), so this benchmark
cannot confirm or refute the design intent.** What it does support: on this synthetic data, with the shipped thresholds, the
forest does not help, and in four of five families it costs more than it gains. That is neither evidence for nor against the idea on real
campaigns that do drift.

**What to say on a slide / what not to say.** SAY: "The running app does not use a pooled reference. In that configuration Module A
REVIEW flags 18.3% of parts at recall 0.814 and cost 0.239 per part (benchmark configuration with the Isolation Forest: 24.3%, 0.841, 0.283)."
Quote the configuration that the demo runs. DO NOT SAY: that the Isolation Forest improves detection, that cross-lot learning is demonstrated,
or that the published figures describe the demo. Limits: one seed (2026), five families, thresholds not re-tuned for the live
configuration.

## Piece 3: sensitivity of the benchmark conclusions to generator assumptions

**What was done.** `scripts/sensitivity.py` re-runs the benchmark (all four baselines and Module A, shipped thresholds,
nothing re-tuned) in ten settings built from the generator's own config objects (`ScreeningConfig`, `MeasurementParams`,
custom `GeneratorFamily` objects; NO generator code was changed): the baseline, noise x0.5 and x2 (measurement noise and tester-offset sigma),
fixed prevalence 1%, 3%, 8%, healthy drift exponent in [0.10, 0.20] and [0.25, 0.40], and lot size 30 and 150. Module A runs in the
LIVE configuration. Every setting has exactly 150 lots with the same lot ids and seed (5101), so 4,500 / 11,550 / 22,500 parts for
lot size 30 / 77 / 150; the baseline is re-run in this design instead of reusing Part 0b (D1) so all settings are comparable.
Static PAT's reference population stays the nominal baseline process, as in the published benchmark. 95% CIs are percentile
bootstrap over lots (1,000 resamples). Each setting runs in 81-163 s (six in parallel); one result file per setting under
`docs/evidence_data/sensitivity/`, the run skips a finished setting. The settings the brief lists are nine besides the baseline,
not ten (D3).  The published (pooled-reference) configuration was NOT run for the sweep: a first attempt with five settings in parallel had not finished any setting after about 20 minutes (the Isolation Forest history grows to 150 lots), the brief made it optional ('if time allows'), and the processes were stopped. Part 2 gives the published-versus-live comparison on the full benchmark instead. Only the smallest setting (lot_30) had finished when they were stopped; its files are kept as `lot_30__published.json` and are not used in any claim.
**Commands.**

```
PYTHONPATH=. uv run python -m scripts.sensitivity run --setting <name> --config live    # names: baseline noise_x0.5 noise_x2 prev_1 prev_3 prev_8 exp_low exp_high lot_30 lot_150
PYTHONPATH=. uv run python -m scripts.sensitivity report --config live
```

### Per setting: recall, precision, flag rate, cost per part with 95% CI (live configuration)

| setting | method | defective | recall | precision | flag rate | cost/part |
|---|---|---|---|---|---|---|
| baseline | module_a_review | 551 | 0.864 [0.834, 0.894] | 0.225 [0.206, 0.243] | 0.183 [0.181, 0.186] | 0.207 [0.191, 0.226] |
| baseline | module_a_reject | 551 | 0.808 [0.771, 0.843] | 0.251 [0.231, 0.272] | 0.153 [0.151, 0.156] | 0.206 [0.186, 0.231] |
| baseline | static_limits | 551 | 0.069 [0.041, 0.099] | 1.000 [1.000, 1.000] | 0.003 [0.002, 0.005] | 0.444 [0.401, 0.490] |
| baseline | fixed_delta | 551 | 0.998 [0.994, 1.000] | 0.424 [0.383, 0.465] | 0.112 [0.102, 0.126] | 0.065 [0.056, 0.077] |
| baseline | static_pat | 551 | 0.254 [0.190, 0.320] | 0.439 [0.308, 0.681] | 0.028 [0.015, 0.041] | 0.371 [0.330, 0.412] |
| baseline | dynamic_pat | 551 | 0.612 [0.571, 0.652] | 0.991 [0.980, 1.000] | 0.029 [0.026, 0.033] | 0.186 [0.157, 0.214] |
| noise_x0.5 | module_a_review | 551 | 0.868 [0.838, 0.899] | 0.225 [0.207, 0.244] | 0.184 [0.181, 0.187] | 0.205 [0.188, 0.225] |
| noise_x0.5 | module_a_reject | 551 | 0.811 [0.775, 0.847] | 0.251 [0.231, 0.271] | 0.154 [0.151, 0.156] | 0.205 [0.184, 0.230] |
| noise_x0.5 | static_limits | 551 | 0.069 [0.041, 0.099] | 1.000 [1.000, 1.000] | 0.003 [0.002, 0.005] | 0.444 [0.401, 0.490] |
| noise_x0.5 | fixed_delta | 551 | 0.998 [0.994, 1.000] | 0.612 [0.575, 0.645] | 0.078 [0.072, 0.084] | 0.031 [0.028, 0.035] |
| noise_x0.5 | static_pat | 551 | 0.252 [0.189, 0.316] | 0.437 [0.306, 0.678] | 0.028 [0.015, 0.041] | 0.372 [0.331, 0.413] |
| noise_x0.5 | dynamic_pat | 551 | 0.610 [0.569, 0.649] | 0.994 [0.984, 1.000] | 0.029 [0.026, 0.033] | 0.186 [0.158, 0.213] |
| noise_x2 | module_a_review | 551 | 0.858 [0.829, 0.886] | 0.220 [0.201, 0.238] | 0.186 [0.183, 0.189] | 0.213 [0.197, 0.230] |
| noise_x2 | module_a_reject | 551 | 0.809 [0.778, 0.844] | 0.250 [0.229, 0.270] | 0.154 [0.152, 0.157] | 0.207 [0.187, 0.229] |
| noise_x2 | static_limits | 551 | 0.073 [0.043, 0.104] | 1.000 [1.000, 1.000] | 0.003 [0.002, 0.005] | 0.442 [0.400, 0.488] |
| noise_x2 | fixed_delta | 551 | 1.000 [1.000, 1.000] | 0.154 [0.138, 0.172] | 0.309 [0.285, 0.335] | 0.262 [0.239, 0.286] |
| noise_x2 | static_pat | 551 | 0.258 [0.195, 0.325] | 0.430 [0.300, 0.669] | 0.029 [0.016, 0.043] | 0.370 [0.330, 0.411] |
| noise_x2 | dynamic_pat | 551 | 0.603 [0.562, 0.643] | 0.988 [0.976, 0.997] | 0.029 [0.026, 0.032] | 0.190 [0.161, 0.218] |
| prev_1 | module_a_review | 134 | 0.978 [0.950, 1.000] | 0.062 [0.053, 0.072] | 0.182 [0.179, 0.185] | 0.173 [0.169, 0.177] |
| prev_1 | module_a_reject | 134 | 0.970 [0.941, 0.993] | 0.073 [0.062, 0.085] | 0.154 [0.151, 0.157] | 0.146 [0.142, 0.151] |
| prev_1 | static_limits | 134 | 0.067 [0.030, 0.110] | 1.000 [1.000, 1.000] | 0.001 [0.000, 0.001] | 0.108 [0.092, 0.125] |
| prev_1 | fixed_delta | 134 | 1.000 [1.000, 1.000] | 0.149 [0.125, 0.174] | 0.078 [0.069, 0.090] | 0.066 [0.057, 0.078] |
| prev_1 | static_pat | 134 | 0.269 [0.189, 0.355] | 0.163 [0.098, 0.346] | 0.019 [0.008, 0.032] | 0.101 [0.083, 0.120] |
| prev_1 | dynamic_pat | 134 | 0.657 [0.579, 0.746] | 0.957 [0.915, 0.990] | 0.008 [0.007, 0.009] | 0.040 [0.028, 0.053] |
| prev_3 | module_a_review | 352 | 0.952 [0.930, 0.972] | 0.161 [0.146, 0.176] | 0.181 [0.178, 0.183] | 0.166 [0.159, 0.174] |
| prev_3 | module_a_reject | 352 | 0.923 [0.897, 0.947] | 0.185 [0.168, 0.202] | 0.152 [0.150, 0.155] | 0.148 [0.139, 0.157] |
| prev_3 | static_limits | 352 | 0.068 [0.037, 0.100] | 1.000 [1.000, 1.000] | 0.002 [0.001, 0.003] | 0.284 [0.256, 0.313] |
| prev_3 | fixed_delta | 352 | 0.997 [0.991, 1.000] | 0.316 [0.281, 0.354] | 0.096 [0.086, 0.108] | 0.067 [0.057, 0.079] |
| prev_3 | static_pat | 352 | 0.253 [0.190, 0.319] | 0.330 [0.220, 0.571] | 0.023 [0.012, 0.036] | 0.243 [0.214, 0.274] |
| prev_3 | dynamic_pat | 352 | 0.636 [0.584, 0.691] | 0.982 [0.965, 0.996] | 0.020 [0.018, 0.022] | 0.111 [0.090, 0.131] |
| prev_8 | module_a_review | 957 | 0.784 [0.759, 0.810] | 0.346 [0.333, 0.360] | 0.188 [0.185, 0.191] | 0.302 [0.274, 0.330] |
| prev_8 | module_a_reject | 957 | 0.712 [0.683, 0.741] | 0.373 [0.360, 0.387] | 0.158 [0.155, 0.161] | 0.338 [0.303, 0.373] |
| prev_8 | static_limits | 957 | 0.060 [0.039, 0.081] | 1.000 [1.000, 1.000] | 0.005 [0.003, 0.007] | 0.779 [0.732, 0.828] |
| prev_8 | fixed_delta | 957 | 0.999 [0.997, 1.000] | 0.570 [0.528, 0.608] | 0.145 [0.134, 0.158] | 0.063 [0.054, 0.075] |
| prev_8 | static_pat | 957 | 0.229 [0.179, 0.282] | 0.556 [0.421, 0.777] | 0.034 [0.021, 0.048] | 0.654 [0.602, 0.712] |
| prev_8 | dynamic_pat | 957 | 0.613 [0.583, 0.643] | 0.995 [0.989, 1.000] | 0.051 [0.048, 0.055] | 0.321 [0.287, 0.354] |
| exp_low | module_a_review | 551 | 0.860 [0.830, 0.889] | 0.224 [0.205, 0.242] | 0.183 [0.181, 0.186] | 0.209 [0.193, 0.228] |
| exp_low | module_a_reject | 551 | 0.806 [0.770, 0.842] | 0.251 [0.230, 0.271] | 0.153 [0.151, 0.156] | 0.208 [0.187, 0.232] |
| exp_low | static_limits | 551 | 0.071 [0.042, 0.102] | 1.000 [1.000, 1.000] | 0.003 [0.002, 0.005] | 0.443 [0.400, 0.488] |
| exp_low | fixed_delta | 551 | 0.998 [0.994, 1.000] | 0.409 [0.369, 0.449] | 0.116 [0.106, 0.130] | 0.070 [0.061, 0.082] |
| exp_low | static_pat | 551 | 0.254 [0.190, 0.320] | 0.438 [0.306, 0.681] | 0.028 [0.015, 0.041] | 0.371 [0.330, 0.412] |
| exp_low | dynamic_pat | 551 | 0.612 [0.572, 0.651] | 0.991 [0.980, 1.000] | 0.029 [0.026, 0.033] | 0.186 [0.157, 0.214] |
| exp_high | module_a_review | 551 | 0.858 [0.828, 0.888] | 0.225 [0.206, 0.244] | 0.182 [0.179, 0.185] | 0.209 [0.192, 0.227] |
| exp_high | module_a_reject | 551 | 0.808 [0.772, 0.843] | 0.251 [0.231, 0.272] | 0.153 [0.151, 0.156] | 0.207 [0.186, 0.231] |
| exp_high | static_limits | 551 | 0.069 [0.041, 0.099] | 1.000 [1.000, 1.000] | 0.003 [0.002, 0.005] | 0.444 [0.401, 0.490] |
| exp_high | fixed_delta | 551 | 0.998 [0.994, 1.000] | 0.442 [0.399, 0.485] | 0.108 [0.097, 0.121] | 0.061 [0.052, 0.073] |
| exp_high | static_pat | 551 | 0.254 [0.190, 0.320] | 0.439 [0.308, 0.681] | 0.028 [0.015, 0.041] | 0.371 [0.330, 0.412] |
| exp_high | dynamic_pat | 551 | 0.612 [0.571, 0.652] | 0.991 [0.980, 1.000] | 0.029 [0.026, 0.033] | 0.186 [0.157, 0.214] |
| lot_30 | module_a_review | 217 | 0.825 [0.775, 0.878] | 0.202 [0.177, 0.227] | 0.196 [0.191, 0.202] | 0.241 [0.209, 0.278] |
| lot_30 | module_a_reject | 217 | 0.825 [0.775, 0.878] | 0.205 [0.179, 0.231] | 0.194 [0.188, 0.199] | 0.238 [0.207, 0.274] |
| lot_30 | static_limits | 217 | 0.078 [0.039, 0.123] | 1.000 [1.000, 1.000] | 0.004 [0.002, 0.006] | 0.444 [0.378, 0.520] |
| lot_30 | fixed_delta | 217 | 1.000 [1.000, 1.000] | 0.427 [0.374, 0.481] | 0.113 [0.100, 0.129] | 0.065 [0.054, 0.078] |
| lot_30 | static_pat | 217 | 0.253 [0.181, 0.324] | 0.417 [0.289, 0.678] | 0.029 [0.015, 0.046] | 0.377 [0.317, 0.442] |
| lot_30 | dynamic_pat | 217 | 0.608 [0.541, 0.670] | 0.964 [0.930, 0.992] | 0.030 [0.025, 0.036] | 0.190 [0.148, 0.237] |
| lot_150 | module_a_review | 1020 | 0.872 [0.847, 0.898] | 0.233 [0.215, 0.251] | 0.170 [0.168, 0.172] | 0.189 [0.175, 0.202] |
| lot_150 | module_a_reject | 1020 | 0.829 [0.802, 0.857] | 0.256 [0.238, 0.275] | 0.147 [0.145, 0.149] | 0.187 [0.171, 0.204] |
| lot_150 | static_limits | 1020 | 0.076 [0.054, 0.101] | 1.000 [1.000, 1.000] | 0.003 [0.002, 0.005] | 0.419 [0.382, 0.459] |
| lot_150 | fixed_delta | 1020 | 0.998 [0.995, 1.000] | 0.416 [0.373, 0.458] | 0.109 [0.099, 0.122] | 0.064 [0.055, 0.077] |
| lot_150 | static_pat | 1020 | 0.258 [0.205, 0.311] | 0.454 [0.313, 0.701] | 0.026 [0.015, 0.038] | 0.350 [0.317, 0.386] |
| lot_150 | dynamic_pat | 1020 | 0.625 [0.595, 0.657] | 0.997 [0.992, 1.000] | 0.028 [0.026, 0.031] | 0.170 [0.149, 0.192] |

### Rank order of methods by cost per part (lowest first; point estimates)

| setting | rank_by_cost |
|---|---|
| baseline | fixed_delta < dynamic_pat < module_a_reject < module_a_review < static_pat < static_limits |
| noise_x0.5 | fixed_delta < dynamic_pat < module_a_reject < module_a_review < static_pat < static_limits |
| noise_x2 | dynamic_pat < module_a_reject < module_a_review < fixed_delta < static_pat < static_limits |
| prev_1 | dynamic_pat < fixed_delta < static_pat < static_limits < module_a_reject < module_a_review |
| prev_3 | fixed_delta < dynamic_pat < module_a_reject < module_a_review < static_pat < static_limits |
| prev_8 | fixed_delta < module_a_review < dynamic_pat < module_a_reject < static_pat < static_limits |
| exp_low | fixed_delta < dynamic_pat < module_a_reject < module_a_review < static_pat < static_limits |
| exp_high | fixed_delta < dynamic_pat < module_a_reject < module_a_review < static_pat < static_limits |
| lot_30 | fixed_delta < dynamic_pat < module_a_reject < module_a_review < static_pat < static_limits |
| lot_150 | fixed_delta < dynamic_pat < module_a_reject < module_a_review < static_pat < static_limits |

Module A REVIEW's rank by cost across the ten settings: baseline 4, noise_x0.5 4, noise_x2 3, prev_1 6, prev_3 4, prev_8 2, exp_low 4, exp_high 4, lot_30 4, lot_150 4. Lowest-cost method per setting:
fixed_delta in 8 settings, dynamic_pat in 2, Module A in 0. Module A is never the cheapest method.

### Pre-registered claims C1-C4 (point estimates, every setting; REVIEW and REJECT tiers evaluated separately, D2)

| Claim | REVIEW | REJECT |
|---|---|---|
| C1 recall exceeds static limits, static PAT and dynamic PAT at EVERY setting | HOLDS at all 10 | HOLDS at all 10 |
| C2 cost per part beats static limits at EVERY setting | BREAKS at prev_1 (REVIEW 0.173 vs static limits 0.108) | BREAKS at prev_1 (REJECT 0.146 vs static limits 0.108) |
| C3 flag-rate floor (>= 10%) persists at 1% prevalence | HOLDS: flag rate 0.182 | HOLDS: flag rate 0.154 |
| C4 dynamic PAT precision above 0.9 at every setting | HOLDS at all 10 (lowest 0.957, at prev_1) | same (a baseline claim) |

**Reading.** C1 holds: Module A's recall is above all three baselines at every setting (0.784 to 0.978 at REVIEW).
C3 holds, and it is structural: Module A's flag rate is 0.170 to 0.196 at every setting whatever the prevalence,
so at 1% prevalence precision is only 0.062 and cost per part exceeds static limits (C2 breaks there: 0.173 against
0.108). C2 holds at every other setting. C4 holds (dynamic PAT precision 0.957 or higher). Module A's recall falls as
prevalence rises (0.978 at 1%, 0.952 at 3%, 0.784 at 8%): with more defects the lot's own median and spread are contaminated and
fewer defects are extreme within their lot. It is also less sensitive to noise x2 than fixed_delta, whose cost goes from 0.065 to 0.262
(Module A REVIEW 0.207 to 0.213).

**What to say on a slide / what not to say.** SAY: "Across ten generator settings (noise x0.5 to x2, prevalence 1 to 8%, drift exponent range, lot
size 30 to 150), Module A's recall stayed above static limits, static PAT and dynamic PAT in all ten; its flag rate stayed between
17% and 20%, so at low prevalence most flags are false alarms." DO NOT SAY: "Module A is cost-optimal" (it is never the
cheapest; fixed_delta or dynamic PAT are), "robust to any assumption", or that conclusions hold on real data.

**What this analysis can and cannot show.** It varies assumption VALUES (noise level, prevalence, exponent range, lot size) inside one fixed
generator STRUCTURE. The structure is what it cannot test: power-law drift plus archetype defects, independent lots, additive
(or Student-t) measurement noise, one process per part number, thresholds derived on data from the same generator. A real
process with correlated lots, campaign drift, non-stationary testers or failure modes outside the four archetypes could break
conclusions that hold on all ten settings here. The 95% CIs cover sampling variation over lots only, not model misspecification;
several settings share defect draws (common random numbers), so contrasts between them are tighter than the CIs suggest.

## Reproduction summary

| Item | Command | Seconds |
|---|---|---|
| Module B MAE, 40 lots/family | `PYTHONPATH=. uv run python -m scripts.module_b_mae` | 35 |
| Module B MAE, 150 lots/family | same with `--lots 150` | 101 |
| M3 config check, 5 lots | `PYTHONPATH=. uv run python -m scripts.config_check` | 15 |
| Live and history-limited benchmarks | `python -m scripts.live_benchmark run --config ...` | 111 (live), ~1,740 each (4 in parallel) |
| Sensitivity, one setting | `python -m scripts.sensitivity run --setting ...` | 81-163 (six in parallel) |
| Default benchmark unchanged | `PYTHONPATH=. uv run python scripts/evaluate.py --format markdown` | 568 |
