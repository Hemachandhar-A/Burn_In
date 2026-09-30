"""Load the two deterministic demo lots into the database behind DATABASE_URL, through the REAL routes.

    python -m scripts.load_demo_lots            # log in as a.sharma, POST /lots twice (skips lots that exist)
    python -m scripts.load_demo_lots --scan     # print the LOT 2 seed scan table (no HTTP, no DB) and exit

The app runs in-process (TestClient), so ingestion, fusion and storage behave exactly as in production; nothing
is written to any table directly. Run `python -m scripts.seed` first (the login needs the seeded accounts).

    DEMO-GOLDEN-01  the harness golden dataset (77 parts, 924 rows): HOLD, GOLDEN-045 REJECT first.
    DEMO-EARLY-01   a generated in-progress lot (0h + 24h only): a forecast verdict, several early REJECT parts.

Note: ingestion.store (the lot's in-memory readings) is per process, so a later checkpoint upload to these lots
from a different server process answers 404 "upload it first" - viewing them (everything read from storage) works.
"""
import argparse
import csv
import io
import sys

GOLDEN_LOT_ID = "DEMO-GOLDEN-01"
EARLY_LOT_ID = "DEMO-EARLY-01"
ACCOUNT_ID, ACCOUNT_PIN = "a.sharma", "1234"  # the seeded demo login (scripts/seed.py)

# Fictional part / manufacturer: the readings are synthetic, so no real vendor is named.
GOLDEN_META = {"part_number": "BX-4720-Q1", "manufacturer": "Northvale Semiconductor", "date_code": "2601"}
EARLY_META = {"part_number": "DEMO-PN", "manufacturer": "Northvale Semiconductor", "date_code": "2603"}

# LOT 2's generator seed: the smallest seed in 1..40 with >= 2 Module B REJECT parts, a forecast lot verdict of
# LOT_AT_RISK or STOP_RUN_RECOMMENDED and <= 15 flagged parts (`--scan` prints the table this was chosen from).
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


def early_readings(seed: int):
    """The POST /lots/demo code path (generator.lot.generate_lot, DEMO-PN), cut to 0h/24h."""
    from generator.lot import generate_lot

    generated = generate_lot(lot_id=EARLY_LOT_ID, part_number=EARLY_META["part_number"], seed=seed,
                             account_id=ACCOUNT_ID)
    return [r for r in generated.dataset.readings if r.checkpoint_hour in EARLY_CHECKPOINTS]


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
    from harness.golden import golden_lot

    client = TestClient(app)
    login = client.post("/auth/login", json={"account_id": ACCOUNT_ID, "pin": ACCOUNT_PIN})
    if login.status_code != 200:
        print(f"login as {ACCOUNT_ID} failed ({login.status_code}): run `python -m scripts.seed` first", file=sys.stderr)
        return 1
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    lots = (
        (GOLDEN_LOT_ID, GOLDEN_META, golden_lot().readings, "COMPLETE"),
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
    parser.add_argument("--scan", action="store_true", help="print the LOT 2 seed scan table and exit")
    args = parser.parse_args(argv)
    return scan() if args.scan else load()


if __name__ == "__main__":
    sys.exit(main())
