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
