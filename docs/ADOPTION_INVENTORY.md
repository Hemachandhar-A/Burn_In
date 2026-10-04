# Module A absolute scoring (V1): consumer inventory (session I2a, Part 1)

Read-only inventory made on `demo-v1.2` (e1c249b) before any code changed. Grep used:
`git grep -n "combined_severity\|severity_tier\|severity_cap_reason\|explainable_corroboration\|module_a_rank" -- . ':!docs' ':!harness/results'`.

## 1a. Consumers of Module A's severity

"0-1?" = depends on `combined_severity` being a 0-1 percentile.

| file:line | what it does | 0-1? | what must change for V1 | risk |
|---|---|---|---|---|
| `module_a/detect.py:333-345` (`_detect_single_lot`) | Tier rule: `combined >= reject_threshold` (below-median capped to REVIEW), `>= review_threshold` REVIEW, else PASS. Thresholds from `config/harness_thresholds.yaml` via `_THRESHOLDS` (0.9556 / 0.9643) | Yes (thresholds are percentiles) | Nothing in the rank path. V1 does not use this function: `detect(scoring=cfg)` routes to `module_a.scoring.detect_lot_scored`, which has the same tier rule on its own scale and needs both thresholds. Add `severity_log10p` and the T transform there | Low |
| `module_a/detect.py:347-351` | `explainable_corroboration` from percentile ties | Yes (rank path only) | Not touched. `detect_lot_scored` computes it from severities (`explainable >= top - 1e-10`) | Low |
| `module_a/detect.py:101,104` | `_CORROBORATION_EPS`, `_CAP_PERCENTILE_THRESHOLD` (test export) | Yes | None (rank path; tests import them) | None |
| `module_a/scoring.py:279-315` (`detect_lot_scored`) | V1 results; today `combined_severity` = raw -log10 p (unbounded) | No (own scale) | Apply T(s) to `combined_severity`, set `severity_log10p = s`; tiers still decided on s | Medium (the change itself) |
| `fusion/pipeline.py:72-73` | `module_a_detect(frames)`; only on COMPLETE lots | - | Pass the `scoring` config chosen by `module_a_scoring()` | Low |
| `fusion/pipeline.py:79-83` | Per component keeps the frame (parameter) with the larger `combined_severity` | Order only | Unchanged in effect: T is monotone, so the argmax is the same as the argmax of s. Compare on `s` when present so T's float saturation (s > ~180 at S0 = 5) cannot create a tie | Low |
| `fusion/pipeline.py:90-92` | `module_a_rank` = position by (-combined_severity, component_id) | Order only | Same: rank on `s` when present, else `combined_severity`. Rank 1 = most severe in both modes | Low |
| `fusion/pipeline.py:168-173` | `worst_parameter` = the max-severity frame's parameter if its tier is not PASS | No | None | Low |
| `fusion/gate.py:13-17` | Fused part verdict from `severity_tier`, `severity_cap_reason`, `explainable_corroboration`; never reads the number | No | None. V1's tiers decide on s | Low |
| `capa/logic.py:282,291` | DPA slot (i): highest `combined_severity` among WATCH/REJECT parts; reason text `f"... ({severity:.2f})"` | Order: no. Text: yes (0.00-1.00 reads as a percentile) | Order keeps working (T monotone); but `severity_log10p`, when present, is the sort key, so it equals rank 1. Reason text: rarity phrasing from s when present, old text when None | Medium (user-visible text, only in absolute mode) |
| `capa/logic.py:324-329` | Control-part reason text "combined severity {x:.2f}" | Text: yes | Same rarity phrasing (or "no meaningful deviation") in absolute mode | Medium |
| `capa/logic.py:242-248` | Comment only | - | Comment mentions percentile; update wording | None |
| `explain/text.py:196-222` (`severity_cap_note`) | Notes for the explainability gate and direction cap | No (no number printed) | None | None |
| `explain/text.py` (`confidence_qualifier`, `explanation_sentence`) | Module B text and flagged-part sentence | No (checked: no severity or percentile used) | None | None |
| `explain/mcd.py`, `explain/ecod.py` | Re-fit MCD / ECOD to explain; do not read `combined_severity` | No | None (V1 does not change the fit) | Low |
| `report/*` (`data.py`, `pdf.py`, `csv_export.py`, `json_export.py`) | Verdict, flagged counts, deltas; no severity number printed (grep: no hit) | No | None. The report package never references Module A (grep: no `module_a` or `ModuleA` hit in `report/`) | None |
| `contracts.py:164-179` (`ModuleAResult`) | `combined_severity: float` documented as a 0-1 percentile; `AnalysisResults.module_a_results` carries one per part | Doc says 0-1 | Add `severity_log10p: float \| None = None` (additive, default None). Update the comment: 0-1 in both modes, monotone transform of s in absolute mode | Medium (frozen contract: Lead process, see 1b) |
| `storage/repository.py` (per-component results JSON) | Stores `AnalysisResults` JSON; reads back with `model_validate_json` | No | Old JSON without the new key parses (default None). New rows in rank mode store `"severity_log10p": null` | Low |
| `fusion/router.py:63-130` | `GET /parts/{id}` returns `module_a` (`ModuleAResult`) as stored | Passes through | New key appears in the response (null in rank mode, a float in absolute mode) | Low |
| `frontend/src/screens/LotDashboardScreen.tsx:28,198,340` | Sorts by `module_a_rank` (position) | Order only | None | None |
| `frontend/src/screens/PartDetailScreen.tsx` | Shows `severity_tier`-based items and `severity_cap_note`; no `combined_severity` display (grep) | No | None. Generated client (`openapi.json`, `schema.d.ts`) gains the optional field when regenerated | Low |
| `frontend/src/screens/PartDetailScreen.test.tsx:32-35` | Mock `ModuleAResult` with `combined_severity: 0.91` | Mock only | Optional field is not required by the type: no edit needed | None |
| `frontend/scripts/screenshots.ts`, `rehearsal.ts`, `smoke_live.ts` | Read `module_a_rank` as a position | Order only | None | None |
| `harness/scoring.py:300-304`, `harness/golden.py:103-202`, `harness/comparison.py`, `harness/bakeoff.py`, `harness/variants.py` | Part score = max of `combined_severity`; thresholds tuned/applied on the scale of the results | Scale-agnostic, except bakeoff/comparison which read the YAML percentile thresholds | Benchmark in absolute mode must use the V1 thresholds on s, not on T(s) (Part 3 passes `severity_log10p`/raw s). Default rank path unchanged | Medium |
| `scripts/config_check.py`, `scripts/demo.py:32`, `scripts/load_demo_lots.py:83` | Compare / sort by rank or severity | Order only | None | None |

## 1a (tests). Tests that pin a percentile-specific value

By file (the exact failing set under `MODULE_A_SCORING=absolute` is measured in Part 2d and listed in `ADOPTION_RESULT.md`):

* `tests/unit/module_a/test_p33.py` (REVIEW_T / REJECT_T = 0.9556 / 0.9643 constructed from rank k/n), `test_p32_hardening.py` (cap at REJECT_T = 27/28, n = 14/28), `test_combined_severity.py` (compares to `_THRESHOLDS`), `test_p32.py`: these call `detect()` directly with the default `scoring=None`, so the switch (which lives in `fusion/pipeline.py`) does not touch them.
* `tests/unit/fusion/test_pipeline.py:362-427` (builds `a_result(..., 0.95, 'REVIEW')` stubs and checks ranking): stubbed Module A, not affected by the switch.
* `tests/unit/capa/test_dpa_selection.py:121,140`, `test_dpa_work_order.py:53`: pin `Highest combined severity in the lot (...)` text from stub results with `severity_log10p` None, so the old text must stay exact when the field is None.
* `tests/unit/harness/test_p17_*`, `test_p18_comparison.py`, `tests/integration/test_golden_module_a.py`, `tests/integration/test_dpa_work_order_golden.py`, `test_live_lot_anchor.py`, `tests/unit/scripts/test_config_check.py`: run the real pipeline or detect and pin numbers; those that go through `run_full_pipeline` are the ones expected to move under `absolute`.

## 1b. Where the thresholds live

* Today: `config/harness_thresholds.yaml` (`module_a_review_threshold: 0.9556`, `module_a_reject_threshold: 0.9643`, `combination_strategy: max`), loaded once at import into `module_a.detect._THRESHOLDS` as `contracts.HarnessThresholds` (a **frozen** model, `model_config = {"frozen": True}`; its header says "never hand-edit; regenerate with `python -m harness.bakeoff`").
* Under V1 the cut-offs are on another scale (-log10 p, unbounded), so they cannot go into that YAML or that model without changing meaning. `ScoringConfig.review_threshold/reject_threshold` (module_a/scoring.py) already carry a second set in memory.
* Decision for this session: store the second set in **one named place that is not part of the frozen contract**: `module_a/settings.py` constants `ABSOLUTE_REVIEW_THRESHOLD = 2.956` and `ABSOLUTE_REJECT_THRESHOLD = 3.419` (with their provenance comment). Neither `contracts.HarnessThresholds` nor the YAML changes.
* Contract status: `HarnessThresholds` is frozen and is not edited. `ModuleAResult` is also frozen; the additive field `severity_log10p` is the one contract change and goes through the Part 6 process: a `CONTRACT_CHANGES.md` entry is appended by this session (Person: Lead, the one exception to "contracts are read-only"), additive with a default so no producer or stored JSON breaks.

## 1c. Design ruling (the Lead's), checked against the inventory

Ruling: keep `combined_severity` in [0, 1) as a monotone transform of s; tiers on s; add `severity_log10p`; rarity phrasing from s.

Check: no consumer in the table needs the number to be a percentile. Every consumer either orders by it (T monotone: same order), reads only the tier, or prints it (only `capa/logic.py` DPA reasons, two lines), which gets rarity phrasing. **No consumer for which the ruling is wrong; no STOP.**

Final choices:

* `T(s) = 1 - exp(-s / S0)`, computed as `-expm1(-s / S0)`, **S0 = 5.0**. Reason: it maps REJECT (3.419) to 0.495 and REVIEW (2.956) to 0.447, i.e. the two tiers straddle the middle of the 0-1 scale, a clear-cut defect (s = 15) reads 0.95 and the golden part (s about 55) reads 0.99998. T is cosmetic: tiers and ranks are decided on s.
* T is clamped at `1 - 1e-12` so the value stays strictly below 1. Beyond s about 138 (T within 1e-12 of 1), distinct parts can share a T value; therefore the pipeline's per-component pick and `module_a_rank` use `severity_log10p` (s) whenever it is set. That removes ties at the top at any magnitude.
* `severity_log10p: float | None = None`. None in rank mode and for old stored rows.
* Rarity phrasing (DPA reason): `more extreme than about 1 in 10^{s} healthy parts` with s rounded to an integer and a display cap: s >= 15 prints `1 in 10^15 or rarer`; s < 1 prints `within the range of healthy parts`.
* Small lots (< 30 parts, so no MCD): V1 uses the robust z leg only (normal tail of |z|); the ECOD leg is unavailable without an anchor (none is supplied), and the Isolation Forest is never part of V1. In rank mode, lots under 30 keep today's behaviour unchanged (MCD input 0.0 for every part). The tier thresholds are the same two numbers at every lot size.
* Module A still runs only on COMPLETE lots (`fusion/pipeline.py` `if is_complete:`), unchanged.
