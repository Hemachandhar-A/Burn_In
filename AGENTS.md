# AGENTS.md — Session Rules for This Project

Read this at the start of every coding-agent session, before touching code. This file is deliberately short — for the *why* behind any rule here, `context.md` is the source of truth; this file only states *what to do*, not the reasoning.

---

## Fill in before starting (delete this line once filled)

```
Person:         [Lead / P1 / P2 / P3 / P4 / P5]
Track:          [e.g. "P1 / Generator", "P1 / Frontend", "P5 / Routers" — from IMPLEMENTATION_PLAN.md Part 2]
Session:        [session number and name from IMPLEMENTATION_PLAN.md Part 10, e.g. "P3 session 2 — remaining detectors + combination"]
Branch:         [from Part 8's branch table, e.g. "p3-module-a" — "develop directly" if this is Lead's L1/L2]
Feature IDs:    [e.g. E2, from essential-features.md — n/a if Lead]
Directories:    [from IMPLEMENTATION_PLAN.md Part 4 — the ONLY paths this session may edit]
Prerequisite:   [the specific session(s) from Part 10's dependency graph this one needs closed first — "none" if this is a track's first session]
```

**If you filled in `Lead` above:** your work packet is `IMPLEMENTATION_PLAN.md` Part 10, the Lead section — not one of P1–P5's. You're the one exception to "contracts are read-only" (rule 3 below); everything else in this file still applies to you.

**If your Track is a frontend session:** read the "Frontend kickoff" variant below, not the default one — the first task and the definition of done are genuinely different for UI work.

---

## What this project is, in one paragraph

A screening tool for ISRO Problem Statement 26170: Module A flags components anomalous relative to their own lot even when inside datasheet limits; Module B predicts a 168h value from 0h/24h readings and flags early rejection against a calibrated safety slope. Full reasoning, every citation, and the complete locked design: `context.md`. What to build: `essential-features.md` (must-build) and `non-essential-features.md` (stretch). Build order, interfaces, and the per-person/per-session plan: `IMPLEMENTATION_PLAN.md` — Part 10 is organized by session and prerequisite, not by calendar day, since sessions can compress or stretch.

## Locked stack — do not add or swap

**Backend:** Python 3.11, FastAPI, Uvicorn, Pydantic v2, pandas, NumPy, SciPy, scikit-learn, PyOD, LightGBM (quantile loss), MAPIE, `shap`, SQLAlchemy + SQLite, `PyJWT>=2.13.0` (auth tokens — this floor matters, not just the name: 2.9.0–2.12.1 carry real CVEs fixed in 2.13.0), `argon2-cffi` (PIN hashing — Argon2id, the current OWASP-recommended default for new code, not `bcrypt`), `pytest` + `httpx`.
**Frontend:** React 18 or 19 + Vite + TypeScript, `react-router-dom` (routing), `@tanstack/react-query` (server-state/caching), `react-plotly.js@^3` + `plotly.js@^3` (charts — v3 is the current maintained line; it dropped support for `plotly.js` v1/v2 and React <18, so don't pin an older `react-plotly.js` version by habit), `openapi-typescript` + `openapi-fetch` (generated, typed API client — this is the pairing `openapi-typescript`'s own docs recommend, not one option among several), Vitest + React Testing Library + jsdom (tests), npm with a committed `package-lock.json`.
**No deep learning. No Streamlit — fully dropped, not kept as a fallback.** No new dependency, on either side, without asking the Lead first.

## Non-negotiable rules

1. **Reuse libraries. Never reimplement an algorithm** named in `essential-features.md` — if it names scikit-learn, PyOD, SHAP, or MAPIE for something, use that, not a hand-rolled version.
2. **Stay inside your owned directories** (filled in above). Need something from another directory changed? Ask the Lead — never edit it yourself, even to "just fix a small thing." **Calling another owner's exposed function is different from editing their directory and is allowed** — three sanctioned examples exist by session 0: everyone calls P2's storage repository functions (`save_account`, `save_project`, `save_analysis_run`, `save_disposition_signoff`, `save_confirmed_outcome`, `log_event`, and their `query_*` counterparts — `IMPLEMENTATION_PLAN.md` Part 5.5) instead of writing SQL directly; every router calls identity's `get_current_account` instead of reimplementing JWT verification; `ingestion/router.py` calls fusion's `run_full_pipeline` (Part 5.7) instead of assembling the pipeline itself. The rule is call, never inline-reimplement, never edit the file it lives in — and it generalizes to a fourth case mid-build without needing a new exception written down first.
3. **Contracts are read-only.** If `contracts.py` is missing a field or type you need: do **not** edit it, and do **not** guess. Append an entry to `CONTRACT_CHANGES.md` (what's missing, why, your proposed fix), keep working against a clearly-prefixed `TEMP_<name>` local stub, and continue — don't wait for a response, the Lead reviews this file in batches, not continuously. **The same applies to the OpenAPI schema/generated TS client on the frontend side** — if a route's response shape doesn't have the field a screen needs, log it the same way; never hand-add a field to the generated client file, it gets overwritten on the next regeneration anyway.
4. **Test first, or alongside — never after.** Every stage has a named edge-case checklist in `IMPLEMENTATION_PLAN.md` Part 7.3, including the Frontend row. A stage isn't done until every row in its checklist has a passing test.
5. **If your stage touches Module A, the golden test must never regress**: lot median 10 µA, a part at 45 µA, limit 50 µA — must be flagged. This is the problem statement's own worked example. Run it before every commit that touches `module_a/` or `fusion/`.
6. **Never leak future data.** Module B's inputs are explicitly bounded by an information horizon — if you're touching feature engineering or Module B, a part's 96h/168h values must never be visible to code computing its 0h/24h features, even accidentally.
7. **No silent imputation of a missing target or a missing required input.** Missing 0h/24h means `forecast_unavailable=True`, not a guessed value. Missing 96h is allowed and flagged, never silently filled in.
8. **Split by lot, never randomly**, anywhere a train/test or calibration split happens — a lot must never appear on both sides of a split.
9. **Determinism matters.** Fixed seeds everywhere randomness is involved. Same input, same seed, same output — every time, on every machine.
10. **Terminology discipline.** Use this project's actual verdict vocabulary — `PASS` / `WATCH` / `REJECT` for parts, `ACCEPT` / `HOLD` / `REJECT` for lot disposition, `LOT_ON_TRACK` / `LOT_AT_RISK` / `STOP_RUN_RECOMMENDED` for an in-progress forecast (never the same wording as a final Complete-lot verdict — a forecast must never look like a measured result). Never invent new status words, on either side of the API boundary — the frontend displays exactly what the backend sends, it doesn't relabel a verdict.
11. **Explainability is a requirement, not a chart.** If your stage produces a flag or a verdict, it needs a matching explanation mechanism — check `essential-features.md` E4 for which one applies to what you're building before assuming SHAP covers everything.
12. **Nothing about this project claims certainty it doesn't have.** If you're writing user-facing text and you're not sure whether a claim is evidence-backed or a disclosed judgment call, check `context.md` Part 8 before writing it — don't phrase a disclosed default as if it were proven.
13. **The JWT lives in memory only.** Never `localStorage`, never `sessionStorage`, never a cookie — a plain React state variable (or context) holding the token, lost on refresh by design. This is a disclosed trade-off (`context.md` Part 8.1), not something to "fix" by persisting it somewhere more convenient.
14. **The frontend talks to the backend only through the generated client.** If a screen needs data the client doesn't expose, that's a contract gap (rule 3) — never write a raw `fetch()` call as a workaround, even temporarily; it silently reintroduces exactly the contract-drift risk the generated client exists to prevent.

## One fresh session per Part 10 session — not one long continued thread

Never stated explicitly until now, despite the rest of this file assuming it throughout: **start a new agent session (a new Claude Code or Antigravity conversation, not a continuation of yesterday's) for each numbered session in Part 10.** Not a new session per person, and not one giant thread for a whole track.

Why this, not one continued session: everything a session needs to resume correctly — what's built, what tests pass, what's still open — lives in git (the commits, the test files, `CONTRACT_CHANGES.md`, `BLOCKERS.md`), not in chat memory. The "orient" step below (`git log`, `git status`, re-reading contracts and tests) exists specifically so a session with zero memory of any prior one can pick up exactly where the last one stopped. A continued thread works too, technically, but degrades the longer it runs — context fills with completed work that's no longer relevant, and it's easy to lose track of exactly which Part 10 session you're even in. Starting fresh each time isn't a workaround for a limitation; it's the actual design, and it's why the kickoff and ongoing prompts both open with a full re-orientation rather than assuming continuity.

**In practice**: finish a session (commit, report status, per the workflow below), close that conversation, and open a new one for the next session in your track — same day or a different one, doesn't matter, since state lives in the repo, not the chat. If two consecutive sessions in your own track are short and you're already mid-flow, running them back to back in one sitting is fine — but still treat each as its own session with its own commit and its own close-out, not one blurred piece of work.

## Session workflow, every session, in order

1. **Checkout your branch, then orient.** `git checkout <branch>` (from the Branch field above and Part 8's table) — `git checkout -b <branch>` instead if this is your track's actual first session and the branch doesn't exist yet. Confirm with `git branch` that you're actually on it, not still on `develop` or wherever the last session left off — **this step was missing entirely from an earlier version of this file**, which went straight to `git log`/`git status` without ever saying to be on the right branch first, the same kind of gap as the missing push instruction. Lead's L1/L2 sessions are the one exception: stay on `develop` directly, per Part 8's sanctioned exception, no checkout needed there. Then: `git log --oneline -10`, `git status`, read `contracts.py` for your inputs/outputs, read existing tests in your directory. **Frontend sessions additionally:** confirm the generated client under `frontend/src/api/` is current — regenerate it (`npm run generate-client`, or ask the Lead if the OpenAPI schema hasn't changed since your last session) before writing any screen code against it.
2. **Identify the task.** Which session number from `IMPLEMENTATION_PLAN.md` Part 10's work packet for your role and track, what its prerequisite is and whether that prerequisite is actually closed yet, what's explicitly out of scope for this session.
3. **Test first.** Write the test for the next piece of behavior before the implementation.
4. **Implement**, reusing the named library, staying in your directory.
5. **Commit and push after each piece of work that passes its test** — not saved up for one commit at the end. Repeat steps 3–5 for each remaining piece of this session's scope. **This step was missing entirely from an earlier version of this file** — it only said to commit once, at close-out, and never once said to push at all. Both matter beyond tidiness: Part 8's rolling merges only work if a branch's commits actually reach the remote for the Lead to see and merge, and if the session ends up interrupted (see step 8), only what's pushed survives past your own machine.
6. **Validate against the Part 7.3 checklist** for your stage — not just the test you just wrote, the whole checklist, before calling the stage done. **Frontend sessions additionally:** a screenshot-verification pass against the exact screen description in `essential-features.md` E6, using the agent's own browser-driving capability (Antigravity's Chromium loop, or Claude Code's equivalent) — this is a required close-out step for a screen, not an optional nicety.
7. **Log, don't guess**, per rule 3, if you hit a contract gap.
8. **Commit and push one final time**, with a message stating what was built and what tests (or screenshot checks) now pass — this closes out the session's work as a whole, on top of the incremental commits from step 5, not instead of them.
9. **Report status** at the end of the session: what's built, tests passing, any `CONTRACT_CHANGES.md` entries added, blockers (if genuinely stuck beyond a contract gap, also log to `BLOCKERS.md`), which session in Part 10 comes next and whether its prerequisite is met yet. **If the session has to end before its own close-out criteria are actually met** — time ran out, genuinely blocked on something — commit and push whatever's done anyway, with the commit message and status report both saying plainly that this session isn't finished and exactly what's left, so the next session (yours or someone else's) resumes from real repo state instead of guessing where the last one stopped.

## Kickoff prompt — Lead, session L1 (none of the other prompts actually fit this one)

Not a filled-in copy of the backend kickoff below — that one's `<orient>` says "read `contracts.py`" and its `<environment_check>` says "install from both lockfiles." Neither exists yet at `L1`; this session is what creates them. A gap found asking directly whether Lead had a working kickoff prompt at all — it didn't, until now.

```
<goal>
I am the Lead, starting session L1 — the first session on this project. The repo exists with just
`main`, nothing else yet.
</goal>
<orient>
git checkout main. Create develop from it: git checkout -b develop, then git push -u origin develop —
this is the one time I'm genuinely on main, and it's this one command; everything else in this session
happens on develop. Read AGENTS.md (this file) in full. Read IMPLEMENTATION_PLAN.md Part 5 in full —
this is what contracts.py gets transcribed from, not designed fresh. Read Part 10's Lead section for
L1's exact scope.
</orient>
<first_task>
Transcribe Part 5 into contracts.py as Pydantic BaseModels — a transcription, not new design. Create
api/main.py: an empty FastAPI() instance, CORS for the Vite dev origin, a /health route. Scaffold a
minimal frontend/ (npm create vite, react-ts template, zero real components, one trivial passing Vitest
test) — needed so the install-check below is even possible this early; P1.9 builds this out later, it
doesn't create it from nothing. Draft scripts/seed.py — it won't run clean until P2.1 exists, which is
expected at this point, not a bug.
</first_task>
<share_and_signoff>
This session's output has to leave the agent entirely at this point: share contracts.py, api/main.py,
and the frontend skeleton with all five developers for the same-session sign-off G0 requires — an actual
yes from each, not silence read as agreement. Each of the five then runs their own install check (Part 3's
acceptance gate) locally. That's what actually closes G0 — the drafting alone doesn't.
</share_and_signoff>
<rules>
Follow every rule in AGENTS.md without exception, especially R1 and R4 — this is the one session where
contracts are being designed rather than read. Once this session closes and sign-off happens, they're
frozen, and rule 3 (contracts are read-only) applies from here on, including to me, except through the
Part 6 process.
</rules>
```

**L2, L3, L4, L5 all use the ongoing prompt below**, `Person: Lead` — by then `contracts.py` and both lockfiles genuinely exist, so the ongoing prompt's assumptions hold. `L1` is the one session that's a true exception.

## Kickoff prompt — first session on a new track (backend)

```
<goal>
I am [Person], starting [track/session name] for this project. Repo is cloned, contracts are frozen.
</goal>
<orient>
git checkout -b [branch name from Part 8's table] — this is the track's first session, the branch doesn't
exist yet. (Lead's L1: skip this, stay on develop directly.) Read AGENTS.md (this file) in full. Read
IMPLEMENTATION_PLAN.md Part 10, my work packet — specifically the session named [session name] and its
stated prerequisite. Read contracts.py for my exact input/output types. Read essential-features.md, [my
feature ID].
</orient>
<environment_check>
If this is my track's actual first session (a ".0" or ".1" session with no earlier session on this
track): before writing any code, run the Part 3 acceptance gate myself — install from both lockfiles,
run pytest and Vitest, confirm both are green. If either isn't clean, stop and fix or flag it — don't
build on top of a broken environment. Also confirm I actually reviewed the specific contracts.py types
this session's packet names as mine (not just skimmed the whole file) — if anything about them is
unclear or missing for what I need, that's a CONTRACT_CHANGES.md entry now, not a guess later.
</environment_check>
<first_task>
Do exactly what Part 10's session entry says for this session — for most tracks' first session, that
is writing a stub: a function matching my contracted output shape, returning fixed fake-but-correctly-shaped
data, so downstream people can start building against it immediately. One real exception, not a rule to
guess from elsewhere: P1's Generator track (session P1.1) has no separate stub session at all and starts
directly on real work (E1 steps 1-3) — nothing downstream needs an early Generator stub, since P2 builds
its own synthetic test fixtures independently. Follow Part 10's actual wording for this session, not this
paragraph's general case, if the two differ.
</first_task>
<rules>
Follow every rule in AGENTS.md without exception. Test first. If contracts.py is missing
something I need, log it to CONTRACT_CHANGES.md and use a TEMP_ stub — never edit
contracts.py directly and never guess.
</rules>
```

## Kickoff prompt — first session on the frontend track

```
<goal>
I am [Person], starting the frontend track for this project. Repo is cloned, contracts are frozen,
the API skeleton (api/main.py) exists.
</goal>
<orient>
git checkout -b p1-frontend — a new branch, separate from p1-generator (Part 8), started fresh here.
Read AGENTS.md (this file) in full. Read IMPLEMENTATION_PLAN.md Part 10, the frontend sessions.
Read essential-features.md E6 for the complete 7-screen spec — this is the single source of truth
for what each screen contains, don't infer a screen's contents from anywhere else.
Check which backend routes already exist for real vs. still stubbed (ask the Lead or check
CONTRACT_CHANGES.md) — build against real routes where they exist, against a locally-mocked
response matching the OpenAPI schema where they don't yet.
</orient>
<first_task>
Build out the minimal skeleton the Lead already created in L1 (npm install and an empty passing Vitest
test already exist and were verified clean at G0 — this session doesn't start from nothing): add
react-router-dom with an empty placeholder route for all 7 screens named in E6, the generated API client
wired to an env-configurable base URL, and an AuthContext holding the JWT in memory only (rule 13).
</first_task>
<rules>
Follow every rule in AGENTS.md without exception, especially 13 and 14. Every screen gets a
screenshot-verification pass against its E6 description before being called done. Never hand-write
a fetch call — if the generated client doesn't expose what a screen needs, that's a contract gap,
log it and use a typed local mock, never an untyped workaround.
</rules>
```

## Ongoing session prompt

```
<goal>
I am [Person]. Continuing [track]. Session: [session name from Part 10]. Objective: [specific next piece].
</goal>
<orient>
git checkout [my track's branch from Part 8's table] — confirm with git branch that I'm actually on it,
not develop or wherever the last session left off. git log --oneline -10 && git status. Read my
directory's existing code and tests. Confirm this session's prerequisite (from Part 10) is actually
closed before starting. If the prerequisite is a session on someone else's branch: run
git fetch origin && git log origin/develop --oneline -10 before doing anything else. If its work is
visible there, get it into my branch with git rebase origin/develop (a rebase, not git pull), and
push my branch with git push --force-with-lease (never plain push, never --force) when the session
closes. If it is NOT visible there, it hasn't landed — ask directly (or check CONTRACT_CHANGES.md /
BLOCKERS.md) rather than start and build against a branch missing what I need. Never guess from
elapsed time. Full reasoning: the Git section below.
</orient>
<task>
[Paste the specific Part 7.3 checklist row(s) this session targets.]
</task>
<rules>
Test first. Stay in my owned directories. Log contract gaps, never guess or edit contracts.py or
the generated client by hand.
</rules>
<end_of_session>
Commit and push (git push --force-with-lease if this session rebased) whatever isn't already pushed from this session's incremental commits — including if
this session isn't actually finished, marked plainly as in-progress if so. Report: what's built, which
Part 7.3 rows now pass (or which screens passed screenshot-verification), any CONTRACT_CHANGES.md or
BLOCKERS.md entries added, which session is next and whether its prerequisite is met.
</end_of_session>
```

## Git

**Checking a prerequisite that lives on someone else's branch.** Part 10 names a prerequisite session, but nothing in git says "P2.4 is done" — you have to look. Run `git fetch origin`, then `git log origin/develop --oneline -10`. If the prerequisite session's work isn't visible there, it hasn't merged into `develop`, and starting now means building against a branch that's missing what you need. If it's unclear, ask directly or check `CONTRACT_CHANGES.md` / `BLOCKERS.md` — don't guess from how much time has passed.

**A merged session is not the same as a live, reachable route.** `git log origin/develop` only confirms a session's *commits* merged. It does not confirm that a router is registered in `api/main.py`, or that its routes are reachable. If your prerequisite is a route (an endpoint you need to call, or that the frontend's generated client is built from), confirm it directly: open `/docs` on a running app, or read the OpenAPI schema (`app.openapi()['paths']`, or `frontend/src/api/openapi.json` after regenerating). If the route is missing there, treat the prerequisite as not met, even though the session shows as merged, and ask the Lead. Registering a router in `api/main.py` is part of the same merge that introduces it, so a missing route is a merge gap, not something to work around.

**Getting a landed prerequisite into your own branch is a rebase, not a pull.** `git pull` merges `develop` into your branch with a merge commit, which is not what "rebase onto `develop` daily" means. The correct sequence is `git fetch origin`, then `git rebase origin/develop`.

**Pushing a rebased branch needs `git push --force-with-lease`, not a plain push.** A rebase rewrites history, so the remote rejects an ordinary push — every time anyone rebases, which is often given the daily-rebase rule. Use `--force-with-lease` specifically, not `--force`: it fails safely if someone else pushed to the branch since your last fetch, instead of silently overwriting their work.

**Backend tracks:** branch per track (e.g. `p3-module-a`), off `develop`. Rebase onto `develop` daily, regardless of merge order position, and **push the rebased branch back to the remote every time** — a rebase that stays local doesn't help the Lead, who can only merge what's actually on the remote. PR into `develop` only when your Part 7.3 checklist is fully green and one other person has reviewed.

**P1 specifically owns two backend tracks and one frontend track that merge at different points** — `p1-generator` (merges early, right after the Lead's session-L1 contracts), and a separate `p1-frontend` branch, started fresh once the API skeleton and at least one real backend route exist, merging last. Don't try to carry both on one branch — they have different prerequisites and different reviewers' worth of context.

Merge order into `main` is fixed — see `IMPLEMENTATION_PLAN.md` Part 8 — don't merge out of order even if your branch is ready early; wait for what you depend on.
