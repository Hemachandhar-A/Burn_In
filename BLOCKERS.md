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

## 2026-09-26 P1 - MOCK_LoginRequest / MOCK_TokenResponse stand in for POST /auth/login (Login screen)
- Blocked on: `POST /auth/login` (Part 5.6, `identity/router.py`, P5.4). It isn't in the live OpenAPI schema (`app.openapi()['paths']` on `develop` @ b55a6cd: `/health`, `/lots`, `/lots/demo`, `/lots/{lot_id}/checkpoints`, `/lots/{lot_id}/quality`, `/lots/{lot_id}/report`, `/projects`, `/projects/{project_id}`, `/projects/{project_id}/disposition-signoffs`, `/projects/{project_id}/events`), and `identity/` isn't on `develop`.
- What was tried: a hand-typed mock per the Login screen. `frontend/src/api/mocks.ts` has `MOCK_LoginRequest` and `MOCK_TokenResponse` (field for field `contracts.py` `LoginRequest`/`TokenResponse`) and `MOCK_login`, which accepts `scripts/seed.py`'s demo PINs and returns 401 otherwise. The token is an opaque placeholder, not a JWT. Only `frontend/src/api/auth.ts` `login()` calls it.
- Consequence: Part 7.3's Frontend row, "login round-trips a real JWT", can't pass until this lands. The hard-refresh-re-prompts half already works (in-memory token, rule 13).
- When P5.4 lands: `npm run generate-client`, change `login()` to take the ApiClient and call `client.POST('/auth/login', { body })`, point `TokenResponse` in `frontend/src/auth/AuthContext.ts` at `components['schemas']['TokenResponse']`, delete the mocks, and mark this RESOLVED in the same session.
- Status: RESOLVED (2026-09-30, Block 5B-1 Part 2a) - `POST /auth/login` is live on `develop` (P5.4 merged). `login()` now takes the ApiClient and calls it directly; `MOCK_login`/`MOCK_LoginRequest`/`MOCK_TokenResponse` deleted; `AuthContext.ts`'s `TokenResponse` points at `components['schemas']['TokenResponse']` via `api/auth.ts`.

---

## 2026-09-26 P1 - POST /lots rejects the pinned wide CSV layout (router never calls parse_wide_lot_csv)
- Blocked on: `ingestion/router.py` (P2). `upload_lot` and `upload_checkpoint` only call `parse_lot_csv` (long format). `ingestion/parsing.py` implements `parse_wide_lot_csv` for the layout E7 step 1 pins (`component_id, checkpoint_hour, <parameter>_<unit>...`), but no route reaches it. Found while screenshot-verifying Ingest against a running backend: a wide file comes back 422 with "missing required column for 'parameter' / 'value' / 'unit'".
- What was tried: the Ingest screen shows those messages correctly (E7 step 5) and needs no change either way, since it sends the file as-is. Verified the screen's happy path with the long format, which the route accepts: POST /lots -> IN_PROGRESS, 24 readings; then POST /lots/{id}/checkpoints with a 168h file -> COMPLETE, 36 readings. Not fixing it here: `ingestion/` is P2's directory (rule 2).
- Proposed fix (P2's call): detect the layout from the header row (`checkpoint_hour` present and no `parameter`/`value` column -> wide) and dispatch to `parse_wide_lot_csv`, in both upload routes.
- Status: OPEN

---

## 2026-09-26 P1 - MOCK_/TEMP_ stand in for the five routes Lot Dashboard + Part Detail need (P1.11)
- Blocked on: `GET /lots/{lot_id}` (P5.3), `GET /parts/{component_id}` (P5.7), `POST /parts/{component_id}/disposition` (P5.5), `POST /parts/{component_id}/confirmed-outcome` (P5.8), `POST /lots/{lot_id}/dpa-work-order` (P5.8). None are in the live OpenAPI schema - `fusion/router.py`, `identity/`, `capa/` don't exist on any pushed branch as of this session (checked `git log origin/develop`: only P5.1's stub, `698d064`, has landed). `POST /lots/{lot_id}/report` (P2, report/router.py) is real and wired through the generated client as usual.
- What was tried: `frontend/src/api/mocks.ts` adds seeded, deterministic (rule 9) generator functions - `MOCK_getLotSummary`, `MOCK_generateDpaWorkOrder`, `MOCK_getPartDetail`, `MOCK_submitDisposition`, `MOCK_submitConfirmedOutcome` - and the response types they return (`TEMP_LotSummaryResponse`, `TEMP_PartDetailResponse`, plus several `MOCK_*`/`TEMP_*` supporting types). Called from `frontend/src/api/lotDetail.ts` and `frontend/src/api/parts.ts`, the same one-function-per-route pattern as `api/auth.ts`. The response shapes also carry fields `contracts.py` doesn't have yet - logged separately in `CONTRACT_CHANGES.md` ("Lot Dashboard and Part Detail need fields `LotSummaryResponse`/`PartDetailResponse` don't carry").
- Consequence: Part 7.3's Frontend row can't fully close for these two screens until real data replaces the synthetic generator - severities, PDA, verdicts, and explanations shown are plausible-looking, not computed by Module A/B.
- When the real routes land: for each, the one function that calls its `MOCK_`/`TEMP_` version (`getLotSummary`, `generateDpaWorkOrder`, `getPartDetail`, `submitDisposition`, `submitConfirmedOutcome`) is edited to call the regenerated client instead - `downloadReport` in `lotDetail.ts` is the template for what that looks like (real route, already wired). Delete the corresponding mock function/types from `mocks.ts` once nothing else calls them, and mark this entry resolved.
- Status: PARTIALLY RESOLVED (2026-09-30, Block 5B-1 Part 2b) - `GET /lots/{lot_id}` is real and wired (`getLotSummary` in `lotDetail.ts`); `LotDashboardScreen.tsx` now renders it directly (real `explanation_summary`, `insufficient_data_components` banner). `GET /parts/{component_id}` and `POST /parts/{component_id}/disposition` are also live in the schema now, but Part Detail was deliberately left untouched this session (reserved for a separate "5B-2 rebuilds Part Detail" block) - `getPartDetail`/`submitDisposition` still call their `MOCK_`/`TEMP_` versions. `POST /lots/{lot_id}/dpa-work-order` and `POST /parts/{component_id}/confirmed-outcome` are still not in the live schema; `generateDpaWorkOrder`/`submitConfirmedOutcome` stay mocked. Still OPEN for those three.
- Status update (2026-09-30, Block 5B-2): `GET /parts/{component_id}` swapped to real (`getPartDetail` in `parts.ts`); Part Detail rebuilt against the generated `PartDetailResponse`/`PartExplanation` types. `POST /parts/{component_id}/disposition` is real in the schema but still mocked - a *new*, separate blocker (`project_id`/`analysis_run_id` required query parameters the response gives the frontend no way to obtain; see CONTRACT_CHANGES.md, its own entry). Still OPEN for `dpa-work-order`, `confirmed-outcome`, and `disposition`.
- Status update (2026-09-30, Block 5C): `POST /lots/{lot_id}/dpa-work-order` and `POST /parts/{component_id}/confirmed-outcome` are both real now (Block 4a merged) and swapped - `generateDpaWorkOrder` in `lotDetail.ts`, `submitConfirmedOutcome` in `parts.ts`. `POST /parts/{component_id}/disposition` is the only one of the original five still mocked - see the dedicated CONTRACT_CHANGES.md entry, unaffected by this block (Block 5D's job).

---

## 2026-09-26 P1 - POST /lots accepts lot ids that no later route can address
- Blocked on: `ingestion/router.py` (P2). `POST /lots` takes `lot_id` as a form field and accepts any string, but every later call addresses the lot by URL path. Checked against the running app with TestClient: `lot_id` values `A/B`, `.` and `..` all create (200), then `POST /lots/{lot_id}/checkpoints` 404s for each, even with the id percent-encoded. Starlette decodes `%2F` before routing, and dot segments collapse in URLs. The same will hold for `GET /lots/{lot_id}` (P5.3) and the report route.
- What was tried: the Ingest screen now refuses these ids before sending (`lotIdProblem` in `frontend/src/api/lots.ts`), so they can't be created from the UI. Any other client, or a CSV-driven script, still can.
- Proposed fix (P2's call): return 422 from `POST /lots` for a `lot_id` containing `/` or made only of dots, with the same wording, so the rule lives on the server too.
- Status: OPEN

---

## 2026-09-26 P1 - MOCK_ stand in for the seven routes Project Browser, History and Settings need (P1.12)
- Blocked on: `GET /events` and `GET /disposition-signoffs` (P2, storage/router.py - approved by the Lead on 2026-09-26 in CONTRACT_CHANGES.md, not built yet; only the per-project variants are live), `GET /settings`, `POST /settings/propose`, `POST /settings/signoff` (P5.5, identity/router.py), `GET /settings/worklist`, `GET /settings/corrective-status` (P5.8, capa/router.py). Checked against the live schema (`app.openapi()['paths']` on this branch, rebased on `develop` @ b55a6cd): none are there. `GET /projects` is real and wired through the generated client.
- What was tried: hand-typed mocks per screen in `frontend/src/api/mocks.ts`, field for field against `contracts.py`: `MOCK_EventResponse`, `MOCK_DispositionRecord` (History); `MOCK_SettingsResponse`, `MOCK_PendingSettingChange`, `MOCK_SettingsProposalRequest`, `MOCK_SettingsSignoffRequest`, `MOCK_WorklistResponse`, `MOCK_CorrectiveStatusResponse` (Settings). They share one fixture world (`MOCK_FIXTURE_PROJECTS`) and a mutable in-memory store, so a proposal and its sign-off show up in the next `GET /settings` and `GET /events`. The mock enforces the two-distinct-account rule (403 when the proposer signs off their own change). Called only from `frontend/src/api/history.ts` and `frontend/src/api/settings.ts`, one function per route.
- Consequence: History and Settings show fixture data, not the database. The Project Browser's Status column reads the (still mocked) `GET /lots/{lot_id}` - see CONTRACT_CHANGES.md "Project Browser, History, Settings" item 1.
- When the real routes land: `npm run generate-client`, then edit each function in `history.ts` / `settings.ts` to take the ApiClient and call its route (`listProjects` in `lots.ts` is the template); the two POSTs drop their `accountId` argument. Delete the mocks once nothing calls them and mark this RESOLVED in the same session.
- Status: PARTIALLY RESOLVED (2026-09-30, Block 5B-1 Parts 2b-2d) - `GET /events`, `GET /disposition-signoffs`, `GET /settings`, `POST /settings/propose`, `POST /settings/signoff` are all real and wired now (History and Settings screens no longer mocked for these). `GET /settings/worklist` and `GET /settings/corrective-status` (P5.8, capa/router.py) are still not in the live schema - `getWorklist`/`getCorrectiveStatus` in `settings.ts` still call their `MOCK_` versions. Still OPEN for those two.
- Status: RESOLVED (2026-09-30, Block 5C) - `GET /settings/worklist` and `GET /settings/corrective-status` are both real now (Block 4a merged) and swapped in `settings.ts`. All seven of this entry's original routes are live and wired. `mocks.ts` shrunk accordingly - `MOCK_getWorklist`/`MOCK_getCorrectiveStatus`/`MOCK_getLotSummary`/`MOCK_generateDpaWorkOrder` and their supporting `TEMP_`/`MOCK_` types deleted (only `MOCK_submitDisposition` and its two types remain, plus `MOCK_FIXTURE_PROJECTS` for tests).

---

## 2026-09-30 P1 - corrective status no longer reacts to a real settings change (was only true by mock coincidence)
- Blocked on: `GET /settings/worklist` and `GET /settings/corrective-status` (P5.8, capa/router.py) not being merged - same root cause as the entry above.
- Why this is worth its own entry: before this session, `MOCK_getCorrectiveStatus` read `confirmed_outcome_fn_ceiling` off the *same* in-memory `mockSettings` object that `MOCK_proposeSetting`/`MOCK_signoffSetting` wrote to, so a SettingsScreen test could finalize a new ceiling and immediately see the corrective-status badge react - this looked like a real cross-feature integration, but it was only true because both were mocks sharing one module-level variable. Now that `GET /settings`, `POST /settings/propose` and `POST /settings/signoff` are real (Block 5B-1 Part 2d) and `GET /settings/corrective-status` is still mocked, that link is gone: finalizing a ceiling change through the real settings routes has no way to affect the still-mocked corrective status, in the app as it stands today.
- What was tried: `SettingsScreen.test.tsx`'s old "finalizing a new FN ceiling moves the live corrective status" test was rewritten to "proposing and signing off a new FN ceiling round-trips through the real routes" - it now asserts the real propose/signoff flow completes correctly, without claiming the corrective-status badge reacts to it (that claim would be false against the app as it currently runs).
- Consequence: none for a user today (the corrective-status panel's own tests, which mock `getCorrectiveStatus` directly, still cover its rendering correctly) - but demo-day walkthroughs should not show "propose/sign off a ceiling change, watch the corrective status badge update," since that will not actually happen until Block 4a lands.
- When Block 4a lands: `getCorrectiveStatus`'s real route will presumably compute the FN rate live from `save_confirmed_outcome`/`query_confirmed_outcomes` and the *current* `confirmed_outcome_fn_ceiling` read via `get_current_settings_state()` (the same helper `GET /settings` already uses in `identity/router.py`), which will restore the link naturally through the real database rather than a shared mock variable. Worth a screenshot-verification pass once that route exists, to confirm the link actually reads as live.
- Status: RESOLVED (2026-09-30, Block 5C) - `GET /settings/corrective-status` is real now (`capa/router.py::get_corrective_status`), and confirmed by reading it directly: it calls `get_current_settings_state()` for `confirmed_outcome_fn_ceiling` - the exact same live-state function `GET /settings`/`POST /settings/propose`/`POST /settings/signoff` already use (`identity/router.py`). The link is restored through the real database, not a shared mock variable, exactly as this entry's "When Block 4a lands" line predicted. `settings.ts`'s `getCorrectiveStatus`/`getWorklist` now take the ApiClient and call the real routes.

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

## 2026-09-30 P1 - RESOLVED: MOCK_submitDisposition (follow-up to the P1.11 entry)
- Blocked on: `POST /parts/{component_id}/disposition` needing `project_id`/`analysis_run_id`.
- What was tried: hand-typed mock per the Part Detail screen.
- Status: RESOLVED (2026-09-30, Block 5D Part 2) - `MOCK_submitDisposition` deleted. `submitDisposition` in `api/parts.ts` calls the real route with the ids from the fetched `PartDetailResponse` (Block 4c Part 3a). `mocks.ts` now holds only fixture data.

## 2026-09-30 P1 - Lot Dashboard metadata: ProjectSummary has no manufacturer, date code or test date (Block 5E Part 1)
- Blocked on: `GET /projects/{project_id}` returns `ProjectSummary` = `project_id, lot_id, part_number, created_at, created_by` only. `manufacturer`, `date_code` and `test_date` (entered on the Ingest form and sent in `LotMetadata`) are not returned by any read route, so the Lot Summary panel cannot show them.
- What was tried: the panel shows lot id and part number (from `getProject`, `project_id == lot_id` per `ingestion/router.py`); the other three are left out, not invented.
- Smallest backend change: add optional `manufacturer: str | None`, `date_code: str | None`, `test_date: datetime | None` to `ProjectSummary` and fill them in `storage/router.py::_project_summary` (the `Project` row already stores `test_date`; manufacturer/date code would need persisting at `save_project`). Needs a Lead contract ruling.
- Status: OPEN
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

## 2026-09-30 Lead-as-P2 - OPEN: flaky test_analysis_run_id_matches_the_latest_of_two_runs (real cause is fusion/router.py, not SQL ordering)
- Blocked on: `fusion/router.py:78` picks the run with `max(matches, key=lambda m: m[1].created_at)`. Python's `max` returns the FIRST maximal element, so when two runs share a `created_at` (coarse Windows clock) it returns the OLDER run. Reproduced deterministically by freezing the clock in `storage.repository`: run1 returned, every time.
- Done (`storage/repository.py`): every timestamp-ordered query now has a rowid tie-break (insertion order among ties); SQLite already returned insertion order in practice, so those tests pass before and after - it is a guarantee, not a repro.
- Needs (outside P2's directories): in `fusion/router.py` pick the last max, e.g. `max(reversed(matches), key=...)` (matches are built in query order, ascending by created_at then rowid), plus a frozen-clock twin test in `tests/unit/fusion/test_part_detail_ids.py`. Alternative inside storage: make `created_at` strictly monotonic per process.
- Status: OPEN.

## 2026-09-30 Lead-as-P5 - RESOLVED: flaky test_analysis_run_id_matches_the_latest_of_two_runs (tied created_at)
- Cause: `fusion/router.py` `max(matches, key=created_at)` returns the FIRST maximal element, so two runs with identical `created_at` (coarse clock) resolved to the older run. Same pattern found and fixed in `capa/logic.py::find_latest_run_for_component`, `fusion/router.py::_staleness_note_for` (latest sign-off) and `report/data.py::_trigger_for_run` (latest trigger event).
- Fix: `max(enumerate(xs), key=(timestamp, index))` - later insertion wins; inputs are in insertion order thanks to the rowid tie-break in `storage/repository.py`.
- Evidence: frozen-clock tests failed before, pass after (`tests/unit/fusion/test_part_detail_ids.py`, `test_tie_latest_signoff.py`, `tests/unit/capa/test_tie_latest_run.py`, `tests/unit/report/test_tie_trigger.py`); flaky test looped 30/30 passes.
- Status: RESOLVED (supersedes the OPEN entry above, which stays as history).
## 2026-09-30 P1 - RESOLVED: Lot Dashboard metadata fields (Block 5F Part 1e)
- Resolves the Block 5E entry "ProjectSummary has no manufacturer, date code or test date".
- Status: RESOLVED (2026-09-30, Block 5F) - `ProjectSummary` now carries nullable `manufacturer`, `date_code`, `test_date` (merged from develop `aa7ec74`). The Lot Dashboard panel shows Part Number, Manufacturer, Date Code and Test Date (date part, via `formatUtc`) only when present; null or empty fields are left out.
