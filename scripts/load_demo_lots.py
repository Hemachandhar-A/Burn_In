"""Load the two deterministic demo lots into the database behind DATABASE_URL, through the REAL routes.

    python -m scripts.load_demo_lots            # log in as a.sharma, POST /lots twice (skips lots that exist)
    python -m scripts.load_demo_lots --scan     # print the DEMO-EARLY-01 seed scan table (no HTTP, no DB) and exit
    python -m scripts.load_demo_lots --scan-complete   # the same for DEMO-COMPLETE-01 (seeds 1..60)

The app runs in-process (TestClient), so ingestion, fusion and storage behave exactly as in production; nothing
is written to any table directly. Run `python -m scripts.seed` first (the login needs the seeded accounts).

    DEMO-COMPLETE-01  a generated complete lot (all four checkpoints): a small, explainable set of flagged parts.
    DEMO-EARLY-01     a generated in-progress lot (0h + 24h only): a forecast verdict, several early REJECT parts.

The harness golden dataset is NOT a demo lot any more: through POST /lots its uA leakage is normalized to nA, outside
the scale Module B is calibrated on (BLOCKERS.md 2026-09-30). It stays a test fixture.

Note: ingestion.store (the lot's in-memory readings) is per process, so a later checkpoint upload to these lots
from a different server process answers 404 "upload it first" - viewing them (everything read from storage) works.
"""
import argparse
import csv
import io
import sys

COMPLETE_LOT_ID = "DEMO-COMPLETE-01"
EARLY_LOT_ID = "DEMO-EARLY-01"
ACCOUNT_ID, ACCOUNT_PIN = "a.sharma", "1234"  # the seeded demo login (scripts/seed.py)

# Fictional part / manufacturer: the readings are synthetic, so no real vendor is named.
COMPLETE_META = {"part_number": "DEMO-PN", "manufacturer": "Northvale Semiconductor", "date_code": "2601"}
EARLY_META = {"part_number": "DEMO-PN", "manufacturer": "Northvale Semiconductor", "date_code": "2603"}

# LOT 2's generator seed: the smallest seed in 1..40 with >= 2 Module B REJECT parts, a forecast lot verdict of
# LOT_AT_RISK or STOP_RUN_RECOMMENDED and <= 15 flagged parts (`--scan` prints the table this was chosen from).
# DEMO-COMPLETE-01's generator seed: the smallest seed in 1..60 (`--scan-complete`) with a COMPLETE lot, <= 15 flagged
# parts, >= 1 REJECT part scored by Module A with stored MCD and ECOD explanation rows, lot verdict HOLD/REJECT, PDA <= 0.15.
# Seed 5 -> 15 flagged, 6 Module A REJECT, verdict REJECT, PDA 0.0779, top part DEMO-COMPLETE-01-0004 (iddq).
COMPLETE_SEED = 5
COMPLETE_SCAN_SEEDS = range(1, 61)
COMPLETE_MAX_FLAGGED, COMPLETE_MAX_PDA = 15, 0.15
EARLY_SEED = 1  # scan 2026-09-30: seed 1 -> 11 flagged, 11 Module B REJECT, LOT_AT_RISK
SCAN_SEEDS = range(1, 41)
MIN_B_REJECT, MAX_FLAGGED = 2, 15
EARLY_CHECKPOINTS = (0, 24)


def _csv_bytes(readings) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["component_id", "parameter", "checkpoint_hour", "value", "unit"])
    for r in readings:
        w.writerow([r.component_id, r.parameter, r.checkpoint_hour, r.value, r.unit])
    return buf.getvalue().encode()


def generated_readings(lot_id: str, seed: int, checkpoints: tuple[int, ...] | None = None):
    """The POST /lots/demo code path (generator.lot.generate_lot, DEMO-PN), optionally cut to some checkpoints."""
    from generator.lot import generate_lot

    generated = generate_lot(lot_id=lot_id, part_number=EARLY_META["part_number"], seed=seed, account_id=ACCOUNT_ID)
    readings = generated.dataset.readings
    return readings if checkpoints is None else [r for r in readings if r.checkpoint_hour in checkpoints]


def early_readings(seed: int):
    return generated_readings(EARLY_LOT_ID, seed, EARLY_CHECKPOINTS)


def scan_complete_seed(seed: int) -> dict:
    from contracts import LotDataset, ScreeningConfig
    from fusion.pipeline import run_full_pipeline

    readings = generated_readings(COMPLETE_LOT_ID, seed)
    dataset = LotDataset(lot_id=COMPLETE_LOT_ID, part_number=COMPLETE_META["part_number"], status="COMPLETE",
                         readings=readings, account_id=ACCOUNT_ID)
    results = run_full_pipeline(dataset, ScreeningConfig())
    flagged = [a for a in results.assessments if a.verdict != "PASS"]
    a_reject = [a for a in results.assessments if a.verdict == "REJECT" and a.module_a_ran]

    def has_rows(a) -> bool:
        e = results.part_explanations.get(a.component_id)
        return bool(e and e.mcd_contributions and e.ecod_dimensions)

    top = min(flagged, key=lambda a: (a.module_a_rank, a.component_id)) if flagged else None
    d = results.disposition
    return {"seed": seed, "status": dataset.status, "flagged": len(flagged), "a_reject": len(a_reject),
            "a_watch": sum(a.verdict == "WATCH" for a in results.assessments), "lot_verdict": d.verdict,
            "pda": d.pda_result, "top": top.component_id if top else "-",
            "worst": top.worst_parameter if top else "-", "top_rows": bool(top and has_rows(top)),
            "any_reject_rows": any(has_rows(a) for a in a_reject)}


def qualifies_complete(row: dict) -> bool:
    return (row["status"] == "COMPLETE" and row["flagged"] <= COMPLETE_MAX_FLAGGED and row["any_reject_rows"]
            and row["lot_verdict"] in ("HOLD", "REJECT") and row["pda"] <= COMPLETE_MAX_PDA)


def scan_complete() -> int:
    print("seed status   flagged A_REJECT A_WATCH verdict   pda    top                     worst      mcd+ecod qualifies")
    chosen = None
    for seed in COMPLETE_SCAN_SEEDS:
        row = scan_complete_seed(seed)
        ok = qualifies_complete(row)
        chosen = chosen if chosen is not None or not ok else seed
        print(f"{seed:>4} {row['status']:<9} {row['flagged']:>6} {row['a_reject']:>8} {row['a_watch']:>7} "
              f"{row['lot_verdict']:<8} {row['pda']:.4f} {row['top']:<23} {row['worst']:<10} {str(row['top_rows']):<8} "
              f"{'YES' if ok else ''}")
    print(f"smallest qualifying seed: {chosen}")
    return 0


def scan_seed(seed: int) -> dict:
    from contracts import LotDataset, ScreeningConfig
    from fusion.pipeline import run_full_pipeline

    readings = early_readings(seed)
    dataset = LotDataset(lot_id=EARLY_LOT_ID, part_number=EARLY_META["part_number"], status="IN_PROGRESS",
                         readings=readings, account_id=ACCOUNT_ID)
    results = run_full_pipeline(dataset, ScreeningConfig())
    verdicts = [a.verdict for a in results.assessments]
    return {"seed": seed, "flagged": sum(v != "PASS" for v in verdicts),
            "b_reject": sum(v == "REJECT" for v in verdicts), "lot_verdict": results.disposition.verdict}


def qualifies(row: dict) -> bool:
    return (row["b_reject"] >= MIN_B_REJECT and row["flagged"] <= MAX_FLAGGED
            and row["lot_verdict"] in ("LOT_AT_RISK", "STOP_RUN_RECOMMENDED"))


def scan() -> int:
    print(f"{'seed':>4} {'flagged':>8} {'B REJECT':>9}  {'lot forecast verdict':<22} qualifies")
    chosen = None
    for seed in SCAN_SEEDS:
        row = scan_seed(seed)
        ok = qualifies(row)
        chosen = chosen if chosen is not None or not ok else seed
        print(f"{row['seed']:>4} {row['flagged']:>8} {row['b_reject']:>9}  {row['lot_verdict']:<22} {'YES' if ok else ''}")
    print(f"smallest qualifying seed: {chosen}")
    return 0


def load() -> int:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    login = client.post("/auth/login", json={"account_id": ACCOUNT_ID, "pin": ACCOUNT_PIN})
    if login.status_code != 200:
        print(f"login as {ACCOUNT_ID} failed ({login.status_code}): run `python -m scripts.seed` first", file=sys.stderr)
        return 1
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    lots = (
        (COMPLETE_LOT_ID, COMPLETE_META, generated_readings(COMPLETE_LOT_ID, COMPLETE_SEED), "COMPLETE"),
        (EARLY_LOT_ID, EARLY_META, early_readings(EARLY_SEED), "IN_PROGRESS"),
    )
    for lot_id, meta, readings, expected_status in lots:
        if client.get(f"/lots/{lot_id}", headers=headers).status_code == 200:
            print(f"skipped {lot_id} (already exists)")
            continue
        r = client.post("/lots", headers=headers, data={"lot_id": lot_id, "account_id": ACCOUNT_ID, **meta},
                        files={"file": ("lot.csv", _csv_bytes(readings), "text/csv")})
        if r.status_code != 200:
            print(f"upload of {lot_id} failed ({r.status_code}): {r.text[:300]}", file=sys.stderr)
            return 1
        if r.json()["status"] != expected_status:
            print(f"{lot_id}: expected status {expected_status}, got {r.json()['status']}", file=sys.stderr)
            return 1
        summary = client.get(f"/lots/{lot_id}", headers=headers).json()["disposition"]
        print(f"loaded {lot_id}: status {summary['status']}, verdict {summary['verdict']}, PDA {summary['pda_result']:.4f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scan", action="store_true", help="print the DEMO-EARLY-01 seed scan table and exit")
    parser.add_argument("--scan-complete", action="store_true", help="print the DEMO-COMPLETE-01 seed scan table and exit")
    args = parser.parse_args(argv)
    if args.scan_complete:
        return scan_complete()
    return scan() if args.scan else load()


if __name__ == "__main__":
    sys.exit(main())
