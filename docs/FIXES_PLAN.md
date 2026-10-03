# FIXES_PLAN.md - Session F24 (Lead): Module B out-of-range guard, disposition status, units

Branch `fixes-guard-signoff-units`, from `demo-v1.1` (HEAD 700ac73 at start). Written and committed before any code change.
Environment: Windows 11 (10.0.26100), uv 0.12.22, Python 3.11.17, Node v22.21.1, npm 10.9.4.

## Regression anchors (must not change; re-checked after every part)

- DEMO-COMPLETE-01 (generated, COMPLETE_SEED = 5): REJECT, PDA 0.0779, 15 of 77 flagged, top part DEMO-COMPLETE-01-0004.
- DEMO-EARLY-01 (EARLY_SEED = 1): IN_PROGRESS, LOT_AT_RISK, PDA 0.1429, 11 of 77 flagged.
- LIVE-01 after the three files: COMPLETE, REJECT, PDA 0.0649, 13 flagged.
- Golden test: 4 passed. Backend suite: 1816 passed + 1 skipped (+ new tests). Frontend vitest: 371.

## Part 1 - Module B out-of-range guard: acceptance tests (verbatim)

- T1 boundary tests at the edge of the range (inside passes through, just outside is unavailable).
- T2 SCALE SWEEP: take one generated complete lot and one in-progress lot, multiply one parameter's values by 10^k for k in -3..3 (through the real pipeline, including unit handling as the route does); for every k either the Module B verdicts equal those at k=0 or the forecast is unavailable; NEVER a different confident verdict. Paste the table (k, number of Module B REJECTs, number unavailable).
- T3 the golden fixture through POST /lots (uploaded in uA as the skipped test does): no Module B REJECT from the scale problem; lot verdict HOLD and PDA about 0.039 as the harness path gives. Un-skip test_golden_lot_through_the_route_is_hold and make it pass; if it cannot pass, say exactly why.
- T4 FALSE-BLOCK RATE: run all five held-out generator families (at least 20 lots each): the guard triggers on at most 1% of in-distribution parts. Paste the per-family rates.
- T5 regression anchors above unchanged.
- T6 (only if the fallback is implemented) invariance test: fallback output scales exactly with the inputs.

Design: at calibration time record per (part_number, parameter) the range of the training inputs (value_0h, the relative changes (v24-v0)/v0 and (v96-v0)/v0, and the lot medians). At prediction time an input outside the allowed range (margin m, log-scale for levels, chosen and justified below) yields `forecast_unavailable=True` with a reason string and no verdict. Fusion already treats unavailable as no Module B signal (exceeds_safety_slope None). Fallback variant B is implemented only if the physics baseline is scale-equivariant AND the safety slope is relative; findings recorded below after 1a.

## Part 2 - Disposition status (E10): rule and acceptance tests

Spec (essential-features.md E10): REJECT requires sign-off from two DISTINCT account IDs; each action requires a written rationale; the dual sign-off needs a small state machine; a concurrency lock around the disposition write; each decision is an immutable record.

Ruling (Lead). Per part and analysis run, only the LATEST decision per account counts:

| Status | Condition |
|---|---|
| NONE | no sign-offs |
| ACCEPT_RECORDED | latest decisions are all ACCEPT (>= 1 account) |
| HOLD_RECORDED | latest decisions are all HOLD (>= 1 account) |
| REJECT_PENDING_SECOND | exactly one account's latest is REJECT, and no other account has a non-REJECT latest decision |
| REJECT_FINAL | two or more DISTINCT accounts' latest decisions are REJECT |
| CONFLICT | accounts' latest decisions disagree and the condition for REJECT_FINAL does not hold (e.g. one REJECT and one ACCEPT; one ACCEPT and one HOLD) |

Precedence: REJECT_FINAL first, then NONE, then CONFLICT (disagreement), then PENDING_SECOND, then ACCEPT/HOLD_RECORDED. Because the latest decision per account counts, an account that REJECTed and later changed to ACCEPT no longer counts as a REJECT; a REJECT_FINAL where one signer later changes is re-evaluated by the same rule (the history stays immutable, the status is derived). Ambiguities the spec leaves open are reported, not ruled further.

- T7 EXHAUSTIVE TRUTH TABLE: every sequence of up to 3 sign-offs from the two accounts a.sharma and r.mehta over {ACCEPT, HOLD, REJECT} gives the status the rule says (generate the table in the test and also assert a printed sample).
- T8 empty and whitespace-only rationale -> 422 and no row written.
- T9 two threads submitting the first and second REJECT for the same part at once end in REJECT_FINAL with exactly two records and no exception (repeat 20 times).
- T10 same-account second REJECT -> the existing 400.
- T11 timing_flag still written for two REJECTs under 2 minutes apart and never as config_change.
- T12 history is immutable (a correction adds a record).

## Part 3 - Units everywhere: acceptance tests (verbatim)

- T13 round trip: the prefix helper's displayed value times its factor equals the canonical value for ten test values per parameter.
- T14 the sentence for the golden fixture contains a unit and a readable magnitude.
- T15 vitest: every chart/axis title and z-score table header contains a unit.
- T16 the PDF text of a generated report contains the unit tokens (extract text as the previous sessions did if no renderer exists).
- T17 old stored results JSON without the new fields still parses and renders (no 'undefined').

Design: canonical unit carried as an ADDITIVE field (default None) through TrajectoryPoint, ZScoreRow and the module results / PartExplanation as appropriate (not SHAP values); unit in explanation sentences; ONE frontend helper and ONE PDF helper for automatic SI-prefix display (10000 nA shown as 10 uA), both tested; axis titles, table headers and PDF column headers show units.

---

## Part 1a findings (read-only investigation, before the guard was written)

- **Range information at prediction time:** none was kept. `module_b/calibration.py::_calibrate_one` (the `complete` frames, train + calibration lots) fed the models and the slope, but `CalibratedDriftModel` stored only the regressors, `safety_slope`, the confidence/slope quantiles and lot ids. `module_b/model.py::feature_matrix` (FEATURE_NAMES, lines 25-34) uses absolute levels and absolute deltas (`delta_24h`, `offset_0h`, `lot_drift_24h`, `value_0h`), so the trees are tied to the calibration scale. The calibration set is 14 synthetic lots per part number (`module_b/predictor.py::synthetic_models`).
- **`safety_slope` is ABSOLUTE:** `module_b/calibration.py::drift_rate` = `(value_168h - value_0h) / (168 - t0)` in measured units per hour, and `exceeds_safety_slope = rate > model.safety_slope` (same file, `forecast`). It is the conformal 0.95 quantile of healthy parts' measured drift rates - not a relative drift.
- **Physics baseline is scale-equivariant** (`module_b/baselines.py`): `power_law = v0 + (v_last - v0) * ratio**n` with `n` from a ratio of medians and robust-z healthy selection, all invariant to multiplying inputs by c > 0, so its prediction scales by c.
- **Variant implemented: A (unavailable only).** The fallback (physics-only forecast with `forecast_basis`) requires an equivariant baseline AND a relative slope. The first holds, the second does not, so a physics-only forecast could not be judged against the slope and would never be allowed to claim `exceeds_safety_slope`. No fallback, no `forecast_basis` field, no T6.
- **How "unavailable" is represented today:** `ModuleBResult.forecast_unavailable=True` with every forecast field None (`module_b/predictor.py::_unavailable`). `fusion/gate.py::compute_part_verdict` only sets b_tier REJECT on `exceeds_safety_slope` truthy, and `fusion/pipeline.py` ranks Module B only on results with a drift rate - so unavailable already contributes no REJECT, no rank and no `predicted_168h`. `explain/text.py::unavailable_forecast_note` produced a generic note; it now carries the reason.

## Margin choice (Part 1b)

Recorded per (part number, parameter) from the calibration's own complete lots: range of `value_0h`, range of the lot median at 0h, ranges of the relative changes (v24-v0)/v0 and (v96-v0)/v0. An input is declined when:

| quantity | allowed interval | margin | why |
|---|---|---|---|
| `value_0h` | [min / 3, max * 3] (log scale) | `LEVEL_MARGIN = 3` | the 20 held-out lots of the most extreme family put single parts at 0.44x the calibration minimum; 3x keeps those in, while a 10x unit slip leaves the window for the large majority of parts |
| lot median at 0h | [min / 2, max * 2] | `LOT_MARGIN = 2` | the lever that catches a whole lot at the wrong scale; chosen by the sweep below |
| relative changes | [lo - 1 span, hi + 1 span] | `REL_MARGIN_SPANS = 1` | held-out families reach rel24 up to 3.9 and rel96 up to 5.8 (calibration maxima 2.6 / 3.4); one span of margin admits them, and it still declines near-zero denominators |

`LOT_MARGIN` trade-off, measured on 5 held-out families x 100 lots x 3 parameters x 5 calibration sets (part numbers PN, DEMO-PN, PN-1, PN-X, PN-Y):

| LOT_MARGIN | worst per-family false-block | lots at 10^+1 / 10^-1 NOT detected (fully declined) |
|---|---|---|
| 2.5 | 0.08% | 16.3% / 15.7% |
| **2.0 (chosen)** | **0.42%** | **9.5% / 9.2%** |
| 1.5 | 2.33% | 4.0% / 3.8% |
| 1.25 | 5.40% | 2.2% / 1.9% |
| 1.0 | 13.3% | 0.8% / 0.7% |

|k| >= 2 (a 100x or 1000x slip) is declined in 100% of cases at every margin. Requirement T4 (<= 1%) rules out a margin below about 1.75; at 2.0 roughly one lot in eleven that is off by exactly 10x lands inside the allowed lot window - the calibration lots themselves span ~8x (lot centres are lognormal with sigma 0.5), so such a lot is indistinguishable from an ordinary high or low lot from the data alone. This is a disclosed limit of a data-derived guard, not something a smaller margin fixes without declining ordinary lots. Related finding: because `safety_slope` is one absolute number per part number, an ordinary lot whose level sits at the top of the calibrated range already sees most of its healthy parts above the slope (the 10x lot in the T2 sweep: 73 of 77 Module B REJECTs). That is existing model behaviour, not changed here.
