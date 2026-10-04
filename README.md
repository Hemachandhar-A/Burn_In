# Burn-in screening tool (ISRO PS 26170)

Module A flags components that are anomalous relative to their own lot even when every reading is inside the datasheet
limit; Module B forecasts the 168h value from the 0h/24h readings and flags early rejection against a calibrated safety
slope. Synthetic data only. Design: `context.md`; what was built: `essential-features.md`.

## Quick start

**Prerequisites:** Python 3.11 with [uv](https://docs.astral.sh/uv/), Node 22, and a bash shell (Git Bash on Windows).

```bash
uv sync                          # creates .venv from uv.lock
bash scripts/build_demo.sh       # the demo, one process, one port
```

`build_demo.sh` reseeds the two accounts, loads the two preloaded lots, runs `npm ci && npm run build`, pre-warms the models and
starts uvicorn, which also serves the built frontend. It takes about 2.5 minutes on a clean clone. Open
**http://localhost:8000** (`--port N` changes it) once `/health` answers; "Demo ready" prints a few seconds before it does.

| Login (pick the name, type the PIN) | PIN |
|---|---|
| A. Sharma (`a.sharma`) | `1234` |
| R. Mehta (`r.mehta`) | `5678` |

Preloaded lots: **DEMO-COMPLETE-01** (Complete: `HOLD`, 4 of 77 parts flagged, Module A decides; Module B forecasts shown as information) and **DEMO-EARLY-01** (In-Progress, forecast).
The preloaded data lives in storage; the live in-memory lot state is rebuilt only when a checkpoint is uploaded
(`docs/DISCLOSURES.md`, "What to say if asked").

**Development** (hot reload; the frontend must stay on port 5173):

```bash
bash scripts/dev.sh              # backend with --reload, plus `npm run dev` on 5173
```

**Tests:** `uv run pytest` (backend), `cd frontend && npm test -- --run && npx tsc -b` (frontend).

## Module A scoring (from demo-v2) and what to say if asked

Module A's default scoring is **absolute (V1F)**: a robust z-score leg and, for lots of 77 or more parts, a multivariate (MCD) leg are turned into
tail probabilities; a part's severity is `s = -log10 p` of its most extreme leg; REVIEW at `s >= 2.956`, REJECT at `s >= 3.419`. **`s` is an index, not a
probability.** The isolation forest and ECOD contribute **no live score** (the forest needs earlier lots the app does not pass in; ECOD needs a reference the app does
not supply). The previous scoring (within-lot percentile) is still available: `MODULE_A_SCORING=rank`. Details: `docs/PPT_NUMBERS.md`, `docs/DISCLOSURES.md` #36-#45,
`docs/SYSTEM_LEVEL_BENCHMARK.md`. All numbers are synthetic.

- **"Why not just a delta limit?"** On this synthetic data a cost-tuned fixed delta costs less than Module A alone (0.031 against 0.082 per part), because the generator's
  defects are drifts and the harness delta limit is relative to the part's own 0h reading. The system's case is the explanation for every flag, lot-relative scores that
  need no per-parameter allowance and a multivariate view; the shipped system (Module A decides a finished lot; Module B forecasts for in-progress lots) costs the same 0.082 per part and is not cheaper than a tuned delta limit.
- **"Is the severity a probability?"** No, an index used to rank parts and apply two tuned cutoffs.
- **"Does it work on real data?"** Not tested. Shadow mode and recalibration on the customer's history are the recommended first steps.
- **"Does it see across lots?"** Module B's safety slope is calibrated across lots. The cross-lot isolation forest is designed and benchmarked but **not active in the app**
  (`docs/CROSS_LOT_ROADMAP.md`).

## Module B on finished lots, and the FN:FP setting (from demo-v2.1)

- **On a finished (Complete) lot, Module A alone decides the part verdicts.** Module B's 168h forecast is still computed and shown (Part Detail, with a note "Module B forecast (information only)" when it exceeds the safety slope) but does not change a part's verdict, the flag count, the PDA or the lot verdict. **On an in-progress lot Module B is the only screen and works as before** (forecast verdicts `LOT_ON_TRACK` / `LOT_AT_RISK` / `STOP_RUN_RECOMMENDED`). Why: on synthetic data it halves the cost per part (0.243 to 0.082) at a recall price (0.964 to 0.923): `docs/MODULE_B_ROLE_EXPERIMENT.md`, `docs/DISCLOSURES.md` #46. Switch back with `MODULE_B_FINISHED_LOT_ROLE=current` (other values: `tiered`, `advisory` (default), `off`).
- **The Settings FN:FP cost ratio selects Module A's REVIEW and REJECT cut-offs** (2:1 to 50:1; 10:1 is the default and gives 2.956 / 3.419). Higher ratio, lower cut-offs, more parts flagged; it applies to lots analysed after the second account signs the change off (`module_a/fnfp.py`, DISCLOSURES #47). The PDA threshold setting now also reaches the analysis (#48).

## Where things are

- Rehearsal click path (live upload of `demo_data/*.csv`): `demo_data/README.md`. Scripted version:
  `cd frontend && node scripts/rehearsal.ts` (see its header; needs a running demo and Playwright's Chromium).
  Without Playwright's Chromium, set `PW_CHANNEL=msedge` (or `chrome`) to use the installed browser.
- Run any script as a module so imports resolve: `uv run python -m scripts.evaluate --format markdown` (not `python scripts/evaluate.py`).
- What to say about limitations: `docs/DISCLOSURES.md`. Numbers that may go on a slide, and the ones that may not:
  `docs/PPT_NUMBERS.md` (re-derive them with `python scripts/check_ppt_numbers.py`).
- Open items and contract changes: `BLOCKERS.md`, `CONTRACT_CHANGES.md`.
