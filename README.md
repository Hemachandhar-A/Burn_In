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

Preloaded lots: **DEMO-COMPLETE-01** (Complete, Module A and B results) and **DEMO-EARLY-01** (In-Progress, forecast).
The preloaded data lives in storage; the live in-memory lot state is rebuilt only when a checkpoint is uploaded
(`docs/DISCLOSURES.md`, "What to say if asked").

**Development** (hot reload; the frontend must stay on port 5173):

```bash
bash scripts/dev.sh              # backend with --reload, plus `npm run dev` on 5173
```

**Tests:** `uv run pytest` (backend), `cd frontend && npm test -- --run && npx tsc -b` (frontend).

## Where things are

- Rehearsal click path (live upload of `demo_data/*.csv`): `demo_data/README.md`. Scripted version:
  `cd frontend && node scripts/rehearsal.ts` (see its header; needs a running demo and Playwright's Chromium).
- What to say about limitations: `docs/DISCLOSURES.md`. Numbers that may go on a slide, and the ones that may not:
  `docs/PPT_NUMBERS.md` (re-derive them with `python scripts/check_ppt_numbers.py`).
- Open items and contract changes: `BLOCKERS.md`, `CONTRACT_CHANGES.md`.
