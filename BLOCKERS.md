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
- Status: OPEN

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
- Status: OPEN

---

## 2026-09-26 P1 - POST /lots accepts lot ids that no later route can address
- Blocked on: `ingestion/router.py` (P2). `POST /lots` takes `lot_id` as a form field and accepts any string, but every later call addresses the lot by URL path. Checked against the running app with TestClient: `lot_id` values `A/B`, `.` and `..` all create (200), then `POST /lots/{lot_id}/checkpoints` 404s for each, even with the id percent-encoded. Starlette decodes `%2F` before routing, and dot segments collapse in URLs. The same will hold for `GET /lots/{lot_id}` (P5.3) and the report route.
- What was tried: the Ingest screen now refuses these ids before sending (`lotIdProblem` in `frontend/src/api/lots.ts`), so they can't be created from the UI. Any other client, or a CSV-driven script, still can.
- Proposed fix (P2's call): return 422 from `POST /lots` for a `lot_id` containing `/` or made only of dots, with the same wording, so the rule lives on the server too.
- Status: OPEN
