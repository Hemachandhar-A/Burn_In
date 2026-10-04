# Live demo files

Four small CSVs in the ingestion long format (`component_id,parameter,checkpoint_hour,value,unit`), generated
deterministically by `python -m scripts.make_demo_csvs` (generator seed `LIVE_SEED` in that script; committed, so
nobody needs to regenerate them). 77 parts x 3 parameters; the readings are synthetic.

| file | rows | use |
|---|---|---|
| `live_0h_24h.csv` | 0h + 24h | first upload: the lot is In-Progress and shows a *forecast* |
| `live_96h.csv` | 96h | second upload (checkpoint): still In-Progress, forecast updated |
| `live_168h.csv` | 168h | third upload: the lot becomes Complete and Module A scores it |
| `full_lot.csv` | all four | one-shot upload of the same lot (compare with the three-step result) |

## Click path

Start the demo with `bash scripts/build_demo.sh --port 8030` (about 2.5 minutes on a clean clone: `npm ci`, the
frontend build and the pre-warm). It prints `Demo ready` a few seconds **before** uvicorn answers: wait until
`http://localhost:8030/health` returns `{"status":"ok"}` (or the Login screen loads) before the first click.
The server preloads two lots, **DEMO-COMPLETE-01** (Complete) and **DEMO-EARLY-01** (In-Progress).

Accounts: `a.sharma` / `1234` and `r.mehta` / `5678`. On the Login screen pick the account by its display name
(**A. Sharma** / **R. Mehta**), type the PIN, **Sign In**. To switch accounts use the round avatar at the top right ->
**Sign out**.

**Part A - the preloaded Complete lot (about 4 minutes)**

1. Sign in as **A. Sharma**. **Project Browser** (left menu) lists both preloaded lots; click **DEMO-COMPLETE-01**.
2. **Lot Dashboard** (DEMO-COMPLETE-01 shows `HOLD`, PDA 3.90%, 4 of 77 flagged; Module B no longer decides a finished lot, so its list shows the same flagged parts ordered by drift risk): verdict badge, `PDA: ...%`, `Flagged Parts`, the one-sentence summary, the metadata panel and the two
   ranked lists (**By Outlier Severity** = Module A, **By Drift Risk** = Module B).
   Rank 1 (the most severe flagged part) is the first row of each list.
3. Click **Generate DPA Work Order**: up to 3 parts, each with its reason.
4. Click a part ID in a ranked list -> **Part Detail**: sentence, confidence qualifier, trajectory chart, 24h Z-Score
   Table, SHAP / MCD / ECOD charts.
5. Every sign-off **requires a written rationale** (the backend answers 422 on an empty one, and the button stays disabled). Type a
   rationale, click **Reject** (first sign-off); the **sign-off status badge** on Part Detail now reads "REJECT: awaiting second sign-off". Click **Reject** again as the same account -> the red message
   "Dual sign-off requires two distinct account IDs, not two role labels". Sign out, sign in as **R. Mehta**, open the same part
   (Project Browser -> lot -> part), type a rationale, **Reject** -> "2 sign-off(s) recorded by distinct accounts", and the status badge reads "REJECT: final" (the part is locked).
   Two sign-offs less than 2 minutes apart add a **Timing Flag** row to **History**.
6. Sign back in as **A. Sharma**. **Settings** shows the worklist with that part and the Corrective Feedback Status
   `INSUFFICIENT DATA` (N=0). On the part: **Record Confirmed Outcome** -> choose **Confirmed Defective** -> **Confirm**.
   Back on **Settings** the worklist is empty and the status reads `FN rate 0.0% (N=1 confirmed outcomes)`, still
   `INSUFFICIENT DATA` (fewer than 10 outcomes).

**Part B - ingest a lot live (about 3 minutes)**

7. **Ingest**. Fill **Lot Metadata** (all five fields are required, and they are needed again for every checkpoint
   upload):
   - Lot ID: `LIVE-01`
   - Part Number: `DEMO-PN` (Module B's models are keyed by the part number)
   - Manufacturer: `Northvale Semiconductor`
   - Date Code: `2603`
   - Test Date: any date (date picker), e.g. today
   Under **Upload Lot CSV** choose `live_0h_24h.csv` (click the drop zone, or drag the file), then **Commit Batch**.
   The result panel says "New lot uploaded ... IN_PROGRESS, 462 readings"; click **Open Lot Dashboard for LIVE-01**.
8. The dashboard shows `LOT AT RISK` with a **FORECAST** chip (never a final verdict), a small Module B list and an empty
   Module A list ("Module A runs when the lot is Complete.").
9. **Ingest** again, same metadata (Lot ID `LIVE-01`); under **Add Checkpoint Reading** click **Select file**, choose
   `live_96h.csv`, **Commit Batch** -> "Checkpoint merged ... IN_PROGRESS, 693 readings"; the dashboard shows the forecast
   refreshed (1 flagged, PDA 1.30% -> 2 flagged, PDA 2.60%).
10. Same again with `live_168h.csv` -> "COMPLETE, 924 readings": the dashboard becomes `REJECT`, PDA 6.49%, 7 of 77
    flagged, and the **By Outlier Severity** (Module A) list appears; the dashboard shows the new result straight away.
11. **Generate Report** (top right of the dashboard) downloads `RPT-<id>.pdf` (about 29 KB, 8 pages).
12. **History** lists Ingest, Checkpoint Added, Analysis Run, Disposition and Timing Flag rows.
13. A page refresh returns to the Login screen (the token lives in memory only, by design).

To see the one-shot path, upload `full_lot.csv` as a new lot (e.g. `LIVE-02`, same metadata): its final verdict and
PDA equal `LIVE-01`'s after step 10.

Note: the component ids inside the files start with `LIVE-01-` whatever lot id you type; that is cosmetic.
Measured on a clean clone (G7, Session 7a, scripted with Playwright): steps 1-11 take about 35 seconds of machine time; a
person clicking through is expected to need 8-10 minutes (not measured).
