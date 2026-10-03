# Module A absolute scoring (V1): evidence gate result (session I2a)

Branch `scoring-adoption` on `demo-v1.2` (e1c249b). Python 3.11.17 (uv), Node 22.21.1, Windows 11. Pre-registration:
`docs/ADOPTION_PLAN.md` (committed before the evidence runs; deviation D1 appended). All data is SYNTHETIC. Nothing the judges
see changes: the switch defaults to today's scoring.

## Verdict

**NOT ADOPT-READY as pre-registered.** R1, R2 and R3 hold on the published protocol with a wide margin; **R4 fails** (clean-lot
flag rate through the app at lot size 30 is 0.2233 in the test, 0.157 in the 100-lot diagnostic; the rule is <= 0.05). The cause
is measured (below): the MCD chi-square leg is badly over-confident at small n, and reproduces on pure Gaussian data, so it is a
property of the estimator at finite n, not of the generator. The sweep (Part 4a) is deferred by ruling (D1).

| Rule | Value | Holds? |
|---|---|---|
| R1 cost per part at REVIEW <= 0.22 | 0.082 [0.069, 0.096] | yes |
| R2 recall at REVIEW >= 0.75 | 0.923 [0.902, 0.945] | yes |
| R3 no family's cost > 0.03 above current | every family is LOWER: -0.126 altered_correlation, -0.118 baseline, -0.116 different_noise_regime, -0.459 higher_defect_prevalence, -0.141 wider_drift_exponent | yes |
| R4 clean-lot flag rate through the app <= 0.05 at n >= 30 | n=30: **0.2233** (test) / 0.157 (diagnostic), n=77: 0.0370 / 0.0416, n=150: 0.0243 / 0.0268 | **NO (n=30)** |

## What was built

* `module_a/settings.py`: `module_a_scoring()` reads `MODULE_A_SCORING` in {`rank`, `absolute`}, default `rank`; an unknown value
  raises. `module_a_scoring_config()` returns None for rank. One named place for the V1 constants: `ABSOLUTE_REVIEW_THRESHOLD = 2.956`,
  `ABSOLUTE_REJECT_THRESHOLD = 3.419` (tuning seed 6101, docs/SCORING_EXPERIMENT_RESULT.md), `DISPLAY_S0 = 5.0`.
* `fusion/pipeline.py`: with the default the call is exactly `module_a_detect(frames)` as before; with `absolute` it passes the V1
  config. A part's worst frame and `module_a_rank` use `severity_log10p` (s) when present, so large s cannot saturate or tie.
* `module_a/scoring.py`: `ScoringConfig.display_s0` (None by default, so the experiment harness is unchanged). Set, results carry
  `severity_log10p = s` and `combined_severity = T(s) = 1 - exp(-s / 5)` (clamped below 1.0). Tiers are decided on s.
* `contracts.py`: `ModuleAResult.severity_log10p: float | None = None` (additive; CONTRACT_CHANGES.md entry 2026-10-03). Old stored JSON parses.
* `capa/logic.py`: the DPA reason text uses rarity phrasing from s ("more extreme than about 1 in 10^N healthy parts, assuming a
  near-Gaussian healthy spread", capped at "1 in 10^15 ... or rarer") and sorts by s; unchanged text when s is None.
* Frontend client regenerated (`openapi.json`, `schema.d.ts`: one optional field); `npx tsc -b` clean, vitest 391 passed, build ok. No screen reads the field.
* Lots below 30 parts (no MCD): V1 scores the robust-z leg only (the ECOD leg is unavailable without an anchor; the Isolation Forest is never part of V1). Rank mode keeps today's behaviour. Module A still runs only on COMPLETE lots.
* PDF delta-table Component column widened (DISCLOSURES #34, resolved, with a test).
* New tests (existing tests not edited): `tests/unit/module_a/test_adoption_switch.py` (13), `tests/integration/test_adoption_absolute.py`
  (size 30 is a strict xfail that records R4), `tests/unit/report/test_pdf_component_column.py` (3).

Inventory and the design ruling check: `docs/ADOPTION_INVENTORY.md` (no consumer for which the ruling is wrong).

## K: how many scores enter the maximum for a part

For a COMPLETE lot with the four checkpoints (0h, 24h, 96h, 168h) and three parameters, **K = 16 scores per part**, all combined by `max`:

* z leg: 12 = 3 parameters x 4 checkpoints. `features/compute.py:133-142` builds `robust_z` for every checkpoint label of every frame;
  `module_a/scoring.py:181` takes each frame's worst-checkpoint |z| (so 4 per frame); `_sev_z_absolute` (`scoring.py:220`) turns it into -log10 p.
* MCD leg: 4 = one 3-dimensional distance per checkpoint. `module_a/scoring.py:149` loops over the checkpoints, `:160` converts each
  squared distance with `chi2_neg_log10_sf(sq, df = 3)`; the part's value is the max over checkpoints, attached to each of the part's frames.
* ECOD leg: 0 (NaN without an anchor; `scoring.py:243,255`).
* The part takes the max over its three frames (`fusion/pipeline.py`, `a_by_comp`). The 16 scores are correlated (the MCD distance is built from the same z values), so 16 independent draws is only an upper bound on the multiplicity: the nominal part-level share if they were independent is 1-(1-t)^16 = 1.6% at p < 1e-3 (the REVIEW threshold is s = 2.956, p = 1.1e-3). In-app lots with fewer checkpoints (IN-PROGRESS) do not run Module A.

## The diagnostic: is V1 calibrated? (ruling 2)

Full tables: `docs/evidence_data/adoption/calibration_summary.md` (generated from `calibration_n*.json`, `gaussian_null.json`).
Clean lots, baseline family, defect prevalence 0, seed 7101, through `fusion.run_full_pipeline` with `MODULE_A_SCORING=absolute`;
**100 lots for n = 15, 20, 30, 40 and 40 lots for n = 50, 60, 77, 100, 150** (1500 to 6000 parts per row).

Part-level share at or above REVIEW (s >= 2.956):

| n | combined (pipeline tier) | z leg alone | MCD leg alone |
|---|---|---|---|
| 15 | 0.0680 | 0.0680 | not run (n < 30) |
| 20 | 0.0575 | 0.0575 | not run |
| 30 | 0.1570 | 0.0467 | 0.1470 |
| 40 | 0.1135 | 0.0315 | 0.1087 |
| 50 | 0.0795 | 0.0285 | 0.0720 |
| 60 | 0.0575 | 0.0262 | 0.0504 |
| 77 | 0.0416 | 0.0282 | 0.0321 |
| 100 | 0.0387 | 0.0283 | 0.0297 |
| 150 | 0.0268 | 0.0203 | 0.0182 |

Calibration histogram (share of INDIVIDUAL scores with p below 1e-3; nominal 0.001), observed on the generator's lots vs on
simulated pure-Gaussian data with the same estimators (1000 simulated lots per n):

| n | z observed | z Gaussian null | MCD observed | MCD Gaussian null |
|---|---|---|---|---|
| 15 | 13.0x | 12.5x | n/a | n/a |
| 30 | 7.9x | 6.5x | 75.8x | 80.5x |
| 50 | 5.5x | 3.7x | 38.4x | 24.9x |
| 77 | 5.5x | 3.0x | 20.0x | 11.2x |
| 100 | 5.9x | 2.0x | 17.6x | 6.6x |
| 150 | 4.0x | 1.7x | 10.4x | 4.1x |

(x = observed share divided by the nominal 0.001. Shares at p < 1e-2 and p < 1e-4 are in the summary file; at 1e-4 the MCD ratio is 478x at n=30 and 39x at n=150.)

Reading:

1. **At n <= 40 the miscalibration is the estimator, not the data**: on Gaussian data the MCD distances are already 80x over-confident at n = 30 (observed on the generator: 76x). sklearn's `MinCovDet` (reweighted, as module_a uses it) under-estimates the covariance at small n, so squared distances are too large against a chi-square(3) tail.
2. **Beyond n of about 50 the generator adds its own excess**: the Gaussian-null ratio falls to 4x at n = 150 while the observed ratio is 10x; the same for z (1.7x null vs 4.0x observed). The healthy generator noise is heavier-tailed than Gaussian, and no finite-sample correction removes that part.
3. **The z leg is also over-confident at small n** (12.5x at n = 15 on Gaussian data), because sigma = IQR/1.35 is estimated from n points; a plain normal tail is the wrong reference there. Lots under 30 parts are scored by the z leg only: 0.068 (n=15) and 0.0575 (n=20) of clean parts are flagged.
4. The thresholds (2.956 / 3.419) were tuned at n = 77, where the combined clean share is 0.04; at that size they happen to absorb the inflation. They do not transfer to other lot sizes.
5. Side observation (not a V1 matter): for a part that is not flagged, the pipeline stores the Module A result of its FIRST parameter, not its maximum-severity frame (`worst_parameter` for PASS parts). Flagged parts store the maximum frame, so tier counts are exact; stored severity for PASS parts is not the part's maximum.

## Candidate small-lot fixes (not implemented, by ruling)

Any chosen fix becomes a NEW post-hoc variant, evaluated on fresh seeds and on the published protocol (seed 2026), with thresholds
re-tuned on tuning seed 6101 only.

| | mechanism | effort | risk |
|---|---|---|---|
| **F1** raise the MCD floor in absolute mode (z leg only below it) | no MCD below the floor | Smallest: one constant | The diagnostic says a floor of 60 is NOT enough: the combined clean share is 0.0575 at n = 60, 0.0795 at n = 50; it would need to be about 77 (0.0416) or more. Every lot of 30 to 76 parts then loses the multivariate leg, whose absence costs recall (in the experiment the z leg alone had cost 0.137 against 0.091 for MCD alone at n = 77). The z leg stays over-confident below 30 (0.058 to 0.068 at n = 15 to 20). It fixes R4 only by removing the detector |
| **F2** Hardin-Rocke scaled-F reference for MCD distances | replace chi-square(3) by a scaled F with finite-sample parameters | Medium | The published approximation is for the raw MCD; sklearn's `MinCovDet.fit` applies a consistency correction and then a reweighting step (re-estimate from the points inside the chi-square 97.5% cut), and `mahalanobis()` uses the REWEIGHTED location and precision. The scale/df of the paper do not describe that estimator, and a scale-and-df fit matches a tail only approximately; it would have to be checked against the Gaussian null in `gaussian_null.json` before use. Fixes MCD only, not the z leg |
| **F3** calibrate each leg against a SIMULATED finite-sample Gaussian null (same estimator, tabulated by lot size, interpolated) | the null of this diagnostic, turned into a reference table; p = share of the null at least as large | Medium to large: a deterministic simulation per size (the tail at 1e-4 needs on the order of 1e6 null scores per size, or a fitted tail), a table in the repo, interpolation in n, re-tune on seed 6101 | The table is tied to the estimator version (sklearn), the dimension (3) and the checkpoint count; it removes the estimator part of the inflation (the dominant part at n <= 40) but not the generator's heavier tails (the residual 1.3x to 2.5x at n of 50 to 150), which the re-tuned thresholds must absorb; thresholds remain synthetic |

**Which the evidence supports best: F3** (or its parametric form, fitting the scaled-F parameters per size to the simulated null, which is F2 done against the estimator actually used). Reasons: (a) the Gaussian null reproduces the MCD inflation at n = 30 almost exactly (80x vs 76x), so a null built from the same estimator is the right reference; (b) the z leg is over-confident at n = 15 to 60 for the same reason (12.5x to 3.2x on Gaussian data) and only F3 corrects both legs, so lots under 30 would also become interpretable; (c) F1 at the floor proposed (60) leaves the combined clean share at 0.0575 and removes a detector; (d) F2 as published does not match the reweighted sklearn estimator and corrects one leg. F3 does not fix the heavier generator tails; that residual is what re-tuning on seed 6101 is for, and it is a reason to expect a small-lot fix to bring R4 close to, not necessarily below, 5% at n = 30 until it is measured.

## Published protocol (Part 3)

Same five held-out families, seed 2026, 9779 parts (521 defective), live configuration, V1 thresholds fixed. The four baselines and the
"current" rows are the earlier `scripts.live_benchmark` tables for the same lots (`docs/evidence_data/live_benchmark/`);
`parts_published` was checked against `harness/results/p18/comparison.md` (flag counts and precision equal). 95% CIs from 1000 resamples
of lots. Files: `docs/evidence_data/adoption/published_protocol_*.csv|json`, `parts_absolute_live.csv.gz`.

| method | n_flagged | flag rate | recall [95% CI] | precision | false alarms | missed | cost/part [95% CI] |
|---|---|---|---|---|---|---|---|
| static limits | 21 | 0.002 | 0.040 [0.023, 0.059] | 1.000 | 0 | 500 | 0.511 [0.439, 0.578] |
| fixed delta | 2344 | 0.240 | 1.000 [1.000, 1.000] | 0.222 | 1823 | 0 | 0.186 [0.149, 0.231] |
| static PAT | 666 | 0.068 | 0.447 [0.379, 0.512] | 0.350 | 433 | 288 | 0.339 [0.285, 0.398] |
| dynamic PAT | 317 | 0.032 | 0.591 [0.545, 0.642] | 0.972 | 9 | 213 | 0.219 [0.174, 0.263] |
| current, published config (IF active), REVIEW | 2378 | 0.243 | 0.841 [0.801, 0.885] | 0.184 | 1940 | 83 | 0.283 [0.255, 0.313] |
| current, live config, REVIEW | 1787 | 0.183 | 0.814 [0.775, 0.859] | 0.237 | 1363 | 97 | 0.239 [0.208, 0.270] |
| current, live config, REJECT | 1505 | 0.154 | 0.758 [0.716, 0.805] | 0.262 | 1110 | 126 | 0.242 [0.207, 0.280] |
| **absolute (V1), REVIEW** | 884 | 0.090 | 0.923 [0.902, 0.945] | 0.544 | 403 | 40 | **0.082 [0.069, 0.096]** |
| **absolute (V1), REJECT** | 757 | 0.077 | 0.912 [0.889, 0.935] | 0.627 | 282 | 46 | 0.076 [0.062, 0.091] |

Per held-out family (REVIEW, cost per part [95% CI]; recall; flag rate), absolute vs current (live):

| family | absolute cost | current cost | absolute recall | current recall | absolute flag rate | current flag rate |
|---|---|---|---|---|---|---|
| altered_correlation | 0.072 [0.049, 0.096] | 0.198 [0.150, 0.251] | 0.929 | 0.848 | 0.084 | 0.162 |
| baseline | 0.074 [0.051, 0.100] | 0.192 [0.168, 0.218] | 0.913 | 0.885 | 0.076 | 0.181 |
| different_noise_regime | 0.094 [0.068, 0.123] | 0.210 [0.176, 0.248] | 0.929 | 0.869 | 0.103 | 0.190 |
| higher_defect_prevalence | 0.137 [0.072, 0.206] | 0.596 [0.398, 0.810] | 0.909 | 0.628 | 0.137 | 0.192 |
| wider_drift_exponent | 0.064 [0.045, 0.086] | 0.205 [0.176, 0.239] | 0.939 | 0.878 | 0.079 | 0.190 |

V1 is cheaper in every family and has higher recall in every family; no family gets worse. The benchmark lots are 77 parts, the size
at which the thresholds were tuned, so this table does not show the small-lot behaviour above.

## Heavy-tailed noise (Part 4b)

Clean lots (150 lots of 77 parts, seed 7101), part-level share flagged at REVIEW:

| family | current (rank, live) | absolute (V1) |
|---|---|---|
| different_noise_regime (Student-t healthy noise) | 0.199 | **0.0714** |
| baseline | 0.189 | 0.0446 |

Cost on that family under the published protocol: absolute 0.094 against 0.210 for current (table above). The Gaussian assumption
shows up as 7.1% flagged on clean heavy-tailed lots against 4.5% on the baseline (above the 5% line for that family; no pass/fail
threshold was registered for 4b), while cost remains well below current scoring.

## Sweep (Part 4a): DEFERRED

C1, C2, C5, C6, C7 are not evaluated in this session (ruling, D1), so that the sweep is run once, on the version that is adopted.
`scripts/sensitivity.py` is unchanged.

## Classified failing tests under `MODULE_A_SCORING=absolute` (input to Session I2b)

Full suite, `MODULE_A_SCORING` unset, first run on the committed code: 1977 passed, 1 xfailed, **1 failed**
(`tests/integration/test_g5_gate.py::test_row6_severity_cap_note_fires_for_both_reasons_with_distinct_wording`): my switch plumbing passed
a `scoring=` keyword on every call, and this test patches `module_a_detect` with a one-argument stub. **Fixed** (a real defect of mine, class C):
in rank mode the call is exactly `module_a_detect(frames)` again; the re-run of the whole suite is under "No-change verification" below.
With `MODULE_A_SCORING=absolute` (first run 1972 passed, 1 xfailed, 6 failed; the six re-run after the fix, still 6 failed):

| test | class | why |
|---|---|---|
| `tests/integration/test_g5_gate.py::test_row6_severity_cap_note_fires_for_both_reasons_with_distinct_wording` | **D** (test stub signature) | patches `module_a_detect` with `patched(frames)`; in absolute mode the pipeline must pass `scoring=`, so the call raises `TypeError`. Not a V1 defect: the test's premise (forcing a rank-mode Module A result) does not apply under V1 and the stub needs a `scoring=None` argument |
| `tests/integration/test_g5_routes.py::test_full_flow_across_routes` | **B** | looks for a second REJECT part besides the golden part; under V1 the golden part is the lot's only REJECT (the others were rank-percentile decoys) |
| `tests/unit/scripts/test_load_demo_lots.py::test_golden_lot_through_the_route_is_hold` | **B** | the golden fixture through `POST /lots` is **ACCEPT** under V1, not HOLD with PDA 0.03896 (three REJECT parts, two of them decoys) |
| `tests/integration/test_live_lot_anchor.py::test_live_lot_three_uploads_anchor` | **A** | pins LIVE-01 PDA 0.0649; under V1 it is 0.0779 |
| `tests/unit/explain/test_text.py::test_explanation_summary_on_the_golden_lot` | **B** | pins "5 of 77 parts flagged, spread across iddq (2), prop_delay (2), leakage (1)"; under V1 "1 of 77 parts flagged, concentrated in leakage" |
| `tests/unit/scripts/test_config_check.py::test_pipeline_and_harness_live_path_agree_on_two_small_lots` | **A** | compares the app's `combined_severity` with the harness's rank-percentile reference; under V1 it is T(s) |

Class C (a real defect in V1 itself): none found by the suite. The demo lots under V1: DEMO-COMPLETE-01 PDA 0.0649 (REJECT; 0.0779 under rank), DEMO-EARLY-01 unchanged (Module A does not run on in-progress lots).

No failing test was edited. Note for I2b: under V1 the golden worked example through the live route flags GOLDEN-045 as REJECT (rank 1)
but the lot disposition is ACCEPT, because one REJECT part out of 77 is below the PDA threshold of 0.03 to 0.05.

## Real-life reasoning

* **Mechanism.** Rank-percentile scoring converts each detector's score into "where does this part sit in its lot", so a lot with no
  defect still has a top 5%: 18.9% of clean parts were flagged (live configuration). V1 asks "how improbable is this deviation if healthy parts
  follow the lot's own distribution", so a clean lot produces few small probabilities while a real outlier produces astronomically small ones
  (the golden part's s is about 55). Flag rate follows the lot instead of being a constant; on the benchmark it flags 9.0% (recall 0.92) instead of 18.3% (recall 0.81).
* **What real data it needs.** None beyond the lot itself: no history, no pooled reference; the first lot of a part number is scored like the hundredth.
* **Failure modes, now with numbers.** (1) The Gaussian assumption: the generator's healthy noise is heavier-tailed than Gaussian and V1's per-score tails are
  4x to 10x too heavy at n = 150; heavy-tailed families flag 7.1% of clean parts. (2) Finite-sample over-confidence below about 77 parts,
  dominated by the MCD leg and reproduced on Gaussian data (R4 failure above); the z leg is over-confident below 60. (3) Mixed fabs or date codes in one lot
  (multimodal) are not tested and will produce small p-values for healthy parts. (4) The thresholds (2.956, 3.419) were tuned on synthetic labels at lot size 77 and do not
  transfer to other sizes as the diagnostic shows. (5) Max over about 16 correlated scores per part is not corrected for multiplicity.
* **Still unproven on real data.** That real healthy parts are near-Gaussian after robust standardisation; that the clean-lot flag rate
  (4% at n = 77 here) holds on a real process; that the defect archetypes planted by the generator resemble real latent defects (recall 0.92 is a
  property of those archetypes); that thresholds transfer between testers and part numbers; MCD behaviour on real, discretised or rank-deficient data.

## No-change verification with `MODULE_A_SCORING` unset (Part 5b)

Run on the final code, `MODULE_A_SCORING` unset (raw logs in `.evidence_logs/`, not committed):

* Full backend suite: **1981 passed, 1 xfailed, 0 failed** (1958 before + 23 new: 13 + 7 + 3; the xfail is the strict R4 record at size 30).
* `python -m scripts.evaluate --format markdown`: the headline table equals the headline of `harness/results/p18/comparison.md` (empty diff on the table rows; `comparison.md` also holds the other tables, which this default command does not print). Copy: `docs/evidence_data/adoption/eval_default_headline_0d.md` (first run).
* Golden Module A test (`tests/integration/test_golden_module_a.py`) and the route test `test_golden_lot_through_the_route_is_hold` (HOLD, PDA 0.03896): part of the suite above, passing.
* Demo anchors through `scripts.load_demo_lots` on a fresh DB: DEMO-COMPLETE-01 REJECT, PDA 0.0779; DEMO-EARLY-01 LOT_AT_RISK, PDA 0.1429. LIVE-01 (COMPLETE / REJECT / 0.0649) is pinned by `test_live_lot_anchor.py`, also in the suite. The "15 of 77" and "top part -0004" figures are pinned by `tests/unit/scripts/test_load_demo_lots.py` (passing); I did not print them separately.
* Frontend: client regenerated (one optional field), `npx tsc -b` clean, vitest 391 passed, `npm run build` ok.
* The only observable difference in rank mode: API results now carry `"severity_log10p": null`.
* Under `absolute` (informational): DEMO-COMPLETE-01 PDA 0.0649; the golden fixture ACCEPT, PDA 0.01299, with GOLDEN-045 the only REJECT part (rank mode: HOLD, 0.03896, REJECT parts G-037, G-066, GOLDEN-045).


## Things not done or uncertain

* **Part 4a (the 10-setting sweep, claims C1, C2, C5, C6, C7) was not run**, by ruling D1. Nothing is claimed about them.
* **Test-first was not followed for the switch**: I wrote the implementation before its tests (the tests then passed, and the size-30 R4 result was found by them). The first full-suite run of the default mode failed one test because of my own plumbing; fixed and re-verified.
* **The "current" rows and the four baselines in the published-protocol table were not recomputed**: they are read from the earlier `docs/evidence_data/live_benchmark/` tables (same seed and lots). I verified `parts_published` against `harness/results/p18/comparison.md` (flags and precision), and the current-live headline equals DISCLOSURES #32 (0.183, 0.814, 0.239); the baselines in the same file match comparison.md.
* **Part 2c(ii) uses the baseline family only** (20 clean lots per size, seed 7101); the experiment's P1 pooled five clean families. The 100/40-lot diagnostic uses the same family.
* **Run-to-run differences between the test and the diagnostic** (n=30: 0.2233 vs 0.157; n=77: 0.0370 vs 0.0416) are different lot draws (20 vs 100 / 40 lots), not different code; the sampling error at 20 lots is large.
* **K = 16 assumes four checkpoints** (a COMPLETE lot); a lot with fewer checkpoints has fewer scores.
* **4b**: the clean-lot flag rate is measured on clean lots; the cost on the heavy-tailed family comes from the published-protocol family row (it has defects). No threshold was registered for 4b.
* **Nothing is validated on real data, and no fix was tested on fresh seeds.** My reading that F3 is best supported rests on the diagnostic only; the claim that F3 would bring n = 30 close to 5% is a hypothesis.
* **Process incidents**: I started a full-suite pytest with wrong flags early (output discarded); a kill by PID was denied, the Lead then cleared it, and I did not retry. The first Part 0d benchmark run may have overlapped my first code edits, so the benchmark was re-run on the final code (identical headline).
* Not pushed or merged anywhere beyond `scoring-adoption`; `main`, `develop` and tags untouched. The untracked sensitivity files in the main repo folder were not touched.

