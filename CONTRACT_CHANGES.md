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
- Status: OPEN

---
