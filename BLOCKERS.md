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

## 2026-09-30 Lead - RESOLVED: P5 blocked on P3.3/P4.3/P2.6
- Blocked on: the entry above, "2026-09-25 P5 - Blocked on P3.3/P4.3 and P2.6" - `p3-module-a` (P3.3) and `p4-module-b` (P4.3) were not on `develop`, and P2.6 (`p2-ingestion`) wasn't merged either.
- What was tried: all three landed on `develop` since - P3.3 in `ae61640` ("Merge p3-module-a into develop: Module A's final merge (P3.0-P3.3 complete)"), P4.3 in `40bdd13` ("P4.3: E3 steps 6-7 - real module_b.predict returning full ModuleBResult"), and P2.6 in `4b62a10` ("Merge p2-ingestion into develop: three P2-flagged ingestion fixes"), all reachable from the `p5-fusion`/`develop` merge `dbd6c85` (`git log --oneline --all` confirms all three SHAs).
- Status: RESOLVED.

---

## 2026-09-30 Lead - RESOLVED: P2.5 blocked on fusion
- Blocked on: the entry above, "2026-09-25 P2 - P2.5 still blocked after P2.6/P2.7/P2.8" - `ingestion/router.py` calling `fusion.run_full_pipeline` then `storage.save_analysis_run`/`storage.log_event` needed P5's `fusion/` merged into `develop`.
- What was tried: confirmed directly in the code now on `develop` (post `dbd6c85`) - `ingestion/router.py`'s `_run_pipeline_and_persist` calls `run_full_pipeline(dataset, ScreeningConfig())` (imported from `fusion.pipeline`) and then `repository.save_analysis_run(...)`. Part A's independent verification of this same merge (A4/A5 this session) exercised this exact path end to end against real fusion output.
- Status: RESOLVED.

---

## 2026-09-30 Lead - RESOLVED: scripts/seed.py's documented invocation can't import storage/
- Blocked on: the entry above, "2026-09-25 P2 - scripts/seed.py's documented invocation can't import storage/" - `python scripts/seed.py` (and `uv run python scripts/seed.py`) fails with `No module named 'storage'` because running a script by file path puts `scripts/` on `sys.path[0]`, not the repo root.
- What was tried: reproduced against a throwaway DB (`DATABASE_URL=sqlite:///./_tmp_seed.db`) - `uv run python scripts/seed.py` still fails with exactly `No module named 'storage'`. `.venv/Scripts/python.exe -m scripts.seed` (module invocation) runs clean and seeds both accounts ("seeded a.sharma (Quality Engineer)", "seeded r.mehta (Reliability Engineer)"), same fix the 2026-09-25 entry already identified. Per AGENTS.md rule 3/this session's ruling, only `scripts/seed.py`'s docstring was changed (`python -m scripts.seed`, run from the project root) - no code touched.
- Status: RESOLVED.

---

---

## 2026-09-30 Lead-as-P5 - RESOLVED: lot metadata (manufacturer, date code, test date) not persisted or exposed
- Blocked on: `GET /projects/{id}` could not return manufacturer / date code / test date - only the `Reading` rows carried manufacturer and date code, and `ProjectSummary` had no such fields. (No entry for this existed in this file to flip from OPEN; this is the only entry for it.)
- What was tried / resolution: nullable `manufacturer` and `date_code` columns on the project table, `ProjectSummary` additions, ingestion fills them, `init_db()` adds the columns to an old database file. Details in CONTRACT_CHANGES.md (2026-09-30, Block 4d Part 3).
- Status: RESOLVED.

---

## 2026-09-30 Lead-as-P5 - RESOLVED: G5 auth finding (P2 routes and GET /lots/{lot_id} unauthenticated)
- Blocked on: G5 findings 1, 3, 4 (CONTRACT_CHANGES.md 2026-09-30 Block 4b).
- Resolution: app-level `get_current_account` dependency on the four routers in `api/main.py`; tests in `tests/integration/test_g5_routes.py` (12 routes -> 401 without a token, CORS preflight unaffected).
- Status: RESOLVED.

## 2026-09-30 Lead-as-P5 - RESOLVED: G5 disposition finding (unknown component/project/run accepted)
- Blocked on: G5 finding 2.
- Resolution: `identity/router.py::create_disposition` validates project, run and component (404, nothing written); tests in `tests/integration/test_g5_routes.py`.
- Status: RESOLVED.

## 2026-09-30 Lead-as-P5 - OPEN: Module B has a single threshold (PASS or REJECT only)
- Blocked on: nothing is blocked - a disclosure. `fusion/gate.py` never gives Module B a REVIEW tier, so WATCH comes from Module A only and E12's table rows needing Module B at REVIEW are unreachable.
- Status: OPEN (disclosed in user-facing material, not fixed).
