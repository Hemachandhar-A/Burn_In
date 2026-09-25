# CONTRACT_CHANGES.md

Append-only. Everyone appends; the Lead resolves in batches (IMPLEMENTATION_PLAN.md Part 6).
Never edit `contracts.py` or the generated TS client yourself - log here and use a `TEMP_<name>` stub.

Entry format:

```
## [date] [your id] - short title
- Missing/wrong: ...
- Why it matters: ...
- Proposed fix: ...
- Status: OPEN
```

---

## 2026-09-25 P4 - FeatureFrame has no `parameter` or `part_number`; `elapsed_hours` order undocumented
- Missing/wrong: `FeatureFrame` carries a single `value_0h`/`value_24h`/`value_96h`, so each frame must be one (component, parameter) pair - but it has no `parameter` field saying which one, and no `part_number`. Separately, `elapsed_hours: list[float]` doesn't state which reading each entry belongs to.
- Why it matters: `ModuleBResult.parameter` can't be filled from the input, and E3 trains "one global model per part number," which Module B can't select without `part_number`. Irregular checkpoints (context.md 5.9) mean linear/power-law extrapolation needs the real hour of the "24h" reading, not an assumed 24.0. Module A (`ModuleAResult.parameter`) likely hits the same gap.
- Proposed fix: add `parameter: str` and `part_number: str` to `FeatureFrame`; document `elapsed_hours` as `[t_0h, t_24h, t_96h?]`, aligned 1:1 with the value fields present. Until resolved, the P4.0 stub fills `parameter` with canned values and P4.1 will read input through a `TEMP_ModuleBInput` wrapper in `module_b/`.
- Status: RESOLVED by Lead on develop (commit: see the `contracts.py` FeatureFrame fix, 2026-09-25). Lead made the four-part fix: `parameter` and `part_number` added; `elapsed_hours` is `dict[str, float]` keyed by checkpoint label (`"0h"`, `"24h"`, `"96h"`) rather than the documented list P4 proposed - same information, no positional ambiguity; `Reading.parameter` widened to `str`; `robust_z` keys are per checkpoint. P4: replace `TEMP_ModuleBInput` with `FeatureFrame` directly.

---

## 2026-09-25 Lead - FeatureFrame reshaped; P2 (and P3) must build features.compute() to the new shape
- Missing/wrong: `contracts.py`'s `FeatureFrame` now has `part_number: str` and `parameter: str`, `elapsed_hours` is `dict[str, float]` keyed by checkpoint label (not `list[float]`), `robust_z` is keyed per checkpoint, and `Reading.parameter` is `str` (not a Literal). Only the last is a runtime-visible change for ingestion.
- Why it matters: `features.compute()` must produce **one `FeatureFrame` per (component, parameter) pair** and populate the two new fields and the dict-shaped `elapsed_hours`. As of this commit no `features/` directory exists on `develop` or any pushed branch (only `p4-module-b` is on the remote), so this is a heads-up to build against the new shape from the start, not a rework of merged code. P3 (Module A) reads the same frame and gets `parameter` for `ModuleAResult.parameter` from it.
- Proposed fix: P2, please pick this up in P2.4 (E8 step 1 wording updated to match); P3, code against the new `FeatureFrame` in P3.0/P3.1. If either already has local work built against the old shape, rebase onto `develop` and switch it.
- Status: OPEN (awaiting P2 / P3 acknowledgement)

---

## 2026-09-25 P1 - No defined wide-format CSV layout between the generator and P2's ingestion
- Missing/wrong: E1's "What it is" says the generator outputs wide-format CSV lots, and P2's 7.3 row requires "wide vs. long format equivalence" - but no numbered E1 step, no `contracts.py` type, and nothing in IMPLEMENTATION_PLAN.md defines the wide CSV's columns (one row per component? how checkpoint columns are named when `checkpoint_hour` is an explicit, possibly irregular number rather than a fixed 0/24/96/168 identity - context.md 7.2 / E1 step 8; where units go; whether the long format is `Reading`'s fields verbatim).
- Why it matters: P1 and P2 would each have to guess the layout, and an ingestion test written against one guess and a generator file written against another is exactly the drift the contract freeze exists to prevent. The irregular-checkpoint requirement (E1 step 8) makes a naive `iddq_0h, iddq_24h, ...` column scheme lossy - a jittered 23.6h read has no column.
- Proposed fix: the Lead pins one layout in contracts.py (or a documented schema the ingestion parser owns), e.g. long format = one row per `Reading` using its field names verbatim; wide format = one row per (component_id, checkpoint_hour) with lot_id, part_number, manufacturer, date_code, checkpoint_hour, then one `<parameter>_<unit>` value column per parameter - keeping elapsed time as a numeric column, not a column-name suffix. Until pinned, the generator hands P2 `LotDataset` objects only (no CSV writer), which is what G2 requires; a CSV writer is a small follow-up once the layout exists.
- Status: RESOLVED by Lead on `develop` (see the Lead entry "Resolving P2's four open entries" below): layout pinned as P2's `parse_wide_lot_csv` implements it, which differs from this proposal in one respect - lot metadata (`lot_id`, `part_number`, `manufacturer`, `date_code`) comes from the ingestion form, not from columns. P1: a CSV writer can now be built against the pinned layout (IMPLEMENTATION_PLAN.md Part 5.2).

---

## 2026-09-25 P2 - Does Module A ever score the actual 168h reading on a Complete lot?
- Missing/wrong: `FeatureFrame`'s per-checkpoint fields are split inconsistently - `robust_z` and `elapsed_hours` are generic `dict[str, float]` keyed by checkpoint label (open-ended, could hold `"168h"`), but `value_0h`/`value_24h`/`value_96h` and `delta_24h`/`delta_96h` are hardcoded scalar fields with no `value_168h`/`delta_168h`. Raised at G0 because the latest `essential-features.md` E7 step 4 change ("a lot is Complete only once its schedule includes 168h") means real 168h `Reading`s exist by the time a lot completes, and Module A's methods (robust z-score, MCD) are checkpoint-generic per `context.md` 5.9 - nothing said whether they run on 168h too.
- Why it matters: without an explicit answer, P2 (features/) and P3 (module_a/) could independently guess differently about whether a 168h `FeatureFrame` gets built at all.
- Proposed fix: n/a - asked as a design question, not a schema gap.
- Status: RESOLVED by Lead, 2026-09-25 - **168h is intentionally excluded from Module A scoring.** `FeatureFrame`/Module A only ever operate on 0h/24h/(96h); the 168h reading's only role is as the Complete-status trigger (E7 step 4) and as Module B's prediction target (`predicted_168h` vs. the eventual actual, reconciled via the confirmed-outcome/DPA loop, 5.17/5.19) - not a value module_a/ ever computes robust-z/MCD/IF/ECOD against. No contract or schema change needed; `value_168h`/`delta_168h` are deliberately absent from `FeatureFrame`, not a gap. P2: `features.compute()` should never attempt to build a 168h frame. P3: no 168h case to handle in `module_a/`.

---

## 2026-09-25 Lead - SUPERSEDES "P2 - Does Module A ever score the actual 168h reading on a Complete lot?" (its RESOLVED status was wrong)
- Supersedes: the entry titled "P2 - Does Module A ever score the actual 168h reading on a Complete lot?" (currently on the `p2-ingestion` branch, not yet on `develop`), whose resolution said 168h is intentionally excluded from Module A and that `value_168h`/`delta_168h` are deliberately absent from `FeatureFrame`. **That resolution is reversed.** The original entry is left in place, unedited, so the history shows the correction and not a silently different answer.
- Why the old resolution was wrong: `context.md` 7.1 (the paragraph headed "The most important architectural decision in this design") frames Module A as full time-series screening - "screening the *complete* recorded time series, implies post-hoc analysis once burn-in finishes" - and the ingestion stage's lot-status field exists precisely so Module B runs on In-Progress lots and Module A (with B) on Complete ones. `context.md` 7.9 screen 3 says the same: Full Disposition is for Complete lots, "both modules". A Module A that never reads the 168h value cannot screen the full series, which contradicts that framing. The 168h reading is therefore not only the Complete trigger and Module B's target - Module A scores it too. (Note: the "most important architectural decision" passage sits under 7.1 Architecture in `context.md`; 7.9 is the screen inventory that repeats the Complete-lot/both-modules rule.)
- Fix applied on `develop`: `FeatureFrame` gains `value_168h: float | None` and `delta_168h: float | None`, same required-but-nullable pattern as `value_96h`/`delta_96h` (no default). `robust_z` and `elapsed_hours` were already open-ended dicts; a `"168h"` key is now populated when the reading exists. `IMPLEMENTATION_PLAN.md` Part 5.2 and `essential-features.md` E2 step 1 and E8 step 1 updated to match.
- Guardrail that does NOT change (AGENTS.md rule 6): 168h is Module B's prediction target. Module B's inputs stay bounded by its 0h/24h horizon - `value_168h`/`delta_168h` are present on the frame for Module A only and Module B must never read them, even on a Complete lot.
- **P2 - real rework, not a heads-up.** `features/compute.py` on `p2-ingestion` (P2.4, `d921ff7`) states it "never looks past 96h", has `_ALL_LABELS = ("0h", "24h", "96h")`, and constructs `FeatureFrame` without the two new fields (which are now required, so it will fail validation until updated). Please: add the `"168h"` label, populate `value_168h`/`delta_168h`, `robust_z["168h"]` and `elapsed_hours["168h"]` for Complete lots (None when the lot has no 168h reading), and update `tests/unit/features/` and the module docstring. Rebase onto `develop` first.
- **Other branches whose `FeatureFrame(...)` constructions now need `value_168h=`/`delta_168h=`:** P4 (`tests/unit/module_b/test_module_b_stub.py`), P1 (`harness/golden.py` and `tests/unit/test_smoke.py`), P5 (`tests/unit/test_smoke.py`, a copy of the Lead's smoke test). Mechanical: pass `None`, or real values where the fixture is a Complete lot (the P1 golden fixture should probably supply a 168h value, since Module A scores it).
- **P3:** no `module_a/` exists on any pushed branch, so nothing to unwind - P3 should build E2 against the 168h-inclusive frame from the start (robust z and per-checkpoint MCD at 168h on Complete lots).
- Status: RESOLVED by Lead on `develop` (contract + docs). OPEN for P2 (rework), and a mechanical follow-up for P1/P4/P5.

---

## 2026-09-25 Lead - Resolving P2's four open entries (test date, reference parts, wide CSV, pooled reference)
- Note on where the entries live: P2's four entries are on the `p2-ingestion` branch, not yet on `develop`, so their own Status lines cannot be edited from here. This entry is the resolution of record; **P2: on your next rebase, set each of the four entries' Status to RESOLVED and point at this entry.**
- **1. "No field anywhere stores a lot's test date" - RESOLVED.** `contracts.py` `Project` gains `test_date: datetime` (required, same pattern as `created_by`/`part_number`); IMPLEMENTATION_PLAN.md Part 5.5 mirrors it. Consequence P2 must handle: `save_project` needs a `test_date` argument (Part 5.5's signature is updated to `save_project(project_id, lot_id, part_number, test_date, created_by)`), and `ingestion/store.py`'s interim per-lot test-date stash can be retired in favour of `Project.test_date`.
- **2. "`Reading` has no way to mark a reference/control part" - RESOLVED as approved, interim unchanged.** The `reference_expected` argument on `apply_tester_offset_correction` (and the optional `reference_expected_json` form field) **stays exactly as P2 built it** - no contract change was made here. What is resolved is only the question of whether the gap is acknowledged: it is, and absence of the argument continues to mean the correction is simply not applied (E7 step 8). No new `Reading` field or `ReferencePart` type was added; if one is ever wanted it comes through a separate contract change.
- **3. "Wide-format CSV" (and P1's matching entry) - RESOLVED, pinned not provisional.** Layout pinned in IMPLEMENTATION_PLAN.md Part 5.2 and `essential-features.md` E7 step 1, exactly as `parse_wide_lot_csv` implements it: one row per (`component_id`, `checkpoint_hour`), `checkpoint_hour` a numeric column, one `<parameter>_<unit>` column per parameter, blank cell = no reading, lot metadata from the form. **P2: drop the `TEMP_WIDE_CSV_SCHEMA` marker from `parse_wide_lot_csv`'s docstring (and the `parsing.py` module docstring) - the layout is now pinned.** P2's note that "no upload path picks between wide/long" is still open and is P2's call within `ingestion/router.py`.
- **4. "No storage query for the pooled cross-lot reference" - RESOLVED as to ownership, interim unchanged.** `query_readings_by_part_number` (or a stats-returning equivalent) is now explicitly in **P2.6's scope** in IMPLEMENTATION_PLAN.md Part 10 - it was genuinely unassigned before. The `pooled_reference` argument / `TEMP_POOLED_REFERENCE` shape in `features.compute()` **stays exactly as P2 built it**, with the lot-relative fallback and `used_pooled_fallback=True` flag as the interim; only the "which session lands the real fix" question is answered. P2 note: P2.6's commit `357988b` already went by without it, so it needs adding in a follow-up P2.6 commit.
- Status: RESOLVED by Lead on `develop`.

---
