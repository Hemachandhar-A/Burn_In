# BLOCKERS.md

Append-only. Log genuine blockers (beyond a contract gap) here; the Lead triages (IMPLEMENTATION_PLAN.md Part 11).

Entry format:

```
## [date] [your id] - short title
- Blocked on: ...
- What was tried: ...
- Status: OPEN
```

---

## 2026-09-25 P2 - scripts/seed.py's documented invocation can't import storage/
- Blocked on: `scripts/seed.py`'s own docstring says to run it as `uv run python scripts/seed.py`. With storage's `accounts` table and `save_account` now built (this session, P2.1), that invocation still fails with `No module named 'storage'` - not a signature mismatch (the call already matches `save_account(account_id, display_name, role, pin_hash)` exactly), but a `sys.path` issue: running a script by file path puts *its own* directory (`scripts/`) on `sys.path[0]`, not the repo root, so `storage` (a root-level package) isn't importable.
- What was tried: `uv run python scripts/seed.py` (fails as above); `uv run python -m scripts.seed` (works clean, seeds both accounts) - module invocation puts the repo root on `sys.path` instead. Not fixing this myself since `scripts/` is Lead-owned (AGENTS.md rule 2) and the fix is either a docstring/invocation change or a `sys.path` shim inside a Lead file, not a P2 change.
- Status: OPEN - for now, `uv run python -m scripts.seed` is the working invocation; every developer's local setup step should use that form until this is resolved one way or the other.

---

## 2026-09-25 P5 - Blocked on P3.3/P4.3 and P2.6
- Blocked on: P3.3 and P4.3 are not merged into develop, preventing session P5.2. P2.6 is also not merged into develop, preventing fallback to session P5.4.
- What was tried: Ran `git fetch origin` and `git log origin/develop`. Found no commits indicating P3.3, P4.3, or P2.6 have landed.
- Status: OPEN

---

## 2026-09-25 P2 - P2.5 still blocked after P2.6/P2.7/P2.8; checked, not guessed
- Blocked on: P2.5 (`ingestion/router.py` calling `fusion.run_full_pipeline` then
  `storage.save_analysis_run`/`storage.log_event`) needs P5.1's orchestrator stub. Checked
  `git fetch origin && git log origin/develop --oneline`: `fusion/` is not on `develop` yet.
  `git log origin/p5-fusion --oneline` shows P5.1's stub exists (`be4ed67 P5.1: Implement
  orchestration stub and data model stubs`) but that branch's own latest commit
  (`71b4ef2`) logs P5 as blocked on P3.3/P4.3 and **P2.6 not merged** - i.e. P5 is waiting on
  the same `p2-ingestion` branch this session is on, which hasn't PR'd into `develop` yet either.
- What was tried: nothing to fix from P2's side - `ingestion/`, `features/`, `report/`,
  `storage/` are P2's owned directories; `fusion/` is P5's, not editable here (AGENTS.md rule
  2). This session (P2.8) does not depend on P2.5 (its own prereq is P2.6 only, already on this
  branch), so it proceeded without waiting.
- Status: OPEN, informational for the Lead - three P2 sessions (P2.6, P2.7, P2.8) have now run
  with P2.5 still open. The actual unblock is mutual: `p2-ingestion` needs to merge to `develop`
  so `p5-fusion` can pick up P2.6's repository API, and P2.5 needs `p5-fusion` merged (or at
  least rebased-in) to get `fusion.run_full_pipeline`. Flagging for a merge-order decision, not
  asking P2 to build against an unmerged branch.

---
