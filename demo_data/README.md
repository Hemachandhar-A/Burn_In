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

Sign in as `a.sharma` / `1234` (the second sign-off below is `r.mehta` / `5678`).

1. **Ingest** -> enter the lot metadata exactly as below (Module B's models are keyed by the part number):
   - Lot ID: `LIVE-01`
   - Part number: `DEMO-PN`
   - Manufacturer: `Northvale Semiconductor`
   - Date code: `2603`
   - Test date: any ISO date, e.g. today
   - File: `live_0h_24h.csv` -> upload.
2. **Lot Dashboard** opens In-Progress with a forecast verdict (`LOT_AT_RISK` / `STOP_RUN_RECOMMENDED` wording, never
   a final verdict) and a few early REJECT parts from Module B.
3. Upload `live_96h.csv` as a checkpoint of `LIVE-01` -> still In-Progress, forecast refreshed.
4. Upload `live_168h.csv` as a checkpoint of `LIVE-01` -> **Lot Complete**: final verdict, PDA, and the Module A
   (outlier) ranking appears next to the Module B drift ranking.
5. Open the top part from the ranking -> Part Detail: trajectory, SHAP / MCD / ECOD explanations, sentence.
6. Sign off as `a.sharma` (rationale + Reject), sign out, sign in as `r.mehta`, sign off again -> two sign-offs by
   distinct accounts (a second sign-off inside 2 minutes is shown with a timing flag).
7. Record a **confirmed outcome** for that part (physical analysis result) from its Part Detail screen.

To see the one-shot path, upload `full_lot.csv` as a new lot (e.g. `LIVE-02`, same metadata): its final verdict and
PDA equal `LIVE-01`'s after step 4.

Note: the component ids inside the files start with `LIVE-01-` whatever lot id you type; that is cosmetic.
