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
- Status: OPEN

---
