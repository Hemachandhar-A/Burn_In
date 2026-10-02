"""Write the live-demo upload files into demo_data/ (ingestion long format), deterministically.

    python -m scripts.make_demo_csvs            # write demo_data/{live_0h_24h,live_96h,live_168h,full_lot}.csv
    python -m scripts.make_demo_csvs --scan     # print the LIVE_SEED scan table (no HTTP, no DB) and exit

The readings come from the same generator call as POST /lots/demo (DEMO-PN), so Module B's models match the part
number the demo uses. See demo_data/README.md for the click path.
"""
import argparse
import csv
import sys
from pathlib import Path

LIVE_LOT_ID = "LIVE-01"
LIVE_META = {"part_number": "DEMO-PN", "manufacturer": "Northvale Semiconductor", "date_code": "2603"}
# LIVE_SEED: chosen by `--scan` among seeds 1..LIVE_SCAN_MAX; see the README / session report for the table and why.
LIVE_SEED = 32  # scan 1..40: no seed has 3-8 flagged (floor 13); fewest flagged (13), then most early B REJECT (2): full lot REJECT, PDA 0.0649, 5 Module A REJECT; at 0h+24h LOT_AT_RISK
LIVE_SCAN_MAX = 40
OUT_DIR = Path(__file__).resolve().parent.parent / "demo_data"
FILES = {
    "live_0h_24h.csv": (0, 24),
    "live_96h.csv": (96,),
    "live_168h.csv": (168,),
    "full_lot.csv": (0, 24, 96, 168),
}
HEADER = ["component_id", "parameter", "checkpoint_hour", "value", "unit"]


def live_readings(seed: int = LIVE_SEED):
    from generator.lot import generate_lot

    return generate_lot(lot_id=LIVE_LOT_ID, part_number=LIVE_META["part_number"], seed=seed,
                        account_id="a.sharma").dataset.readings


def csv_text(readings, hours: tuple[int, ...]) -> str:
    """Stable row order (the generator's), fixed line endings, repr() floats: byte-identical on every run."""
    lines = [",".join(HEADER)]
    for r in readings:
        if r.checkpoint_hour in hours:
            lines.append(f"{r.component_id},{r.parameter},{int(r.checkpoint_hour)},{r.value!r},{r.unit}")
    return "\n".join(lines) + "\n"


def write_all(out_dir: Path = OUT_DIR, seed: int = LIVE_SEED) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    readings = live_readings(seed)
    paths = []
    for name, hours in FILES.items():
        path = out_dir / name
        path.write_bytes(csv_text(readings, hours).encode("utf-8"))
        paths.append(path)
    return paths


def scan_seed(seed: int) -> dict:
    from contracts import LotDataset, ScreeningConfig
    from fusion.pipeline import run_full_pipeline

    readings = live_readings(seed)
    def run(status, hours):
        rd = [r for r in readings if r.checkpoint_hour in hours]
        ds = LotDataset(lot_id=LIVE_LOT_ID, part_number=LIVE_META["part_number"], status=status, readings=rd,
                        account_id="a.sharma")
        return run_full_pipeline(ds, ScreeningConfig())

    full = run("COMPLETE", (0, 24, 96, 168))
    early = run("IN_PROGRESS", (0, 24))
    return {
        "seed": seed,
        "full_flagged": sum(a.verdict != "PASS" for a in full.assessments),
        "a_reject": sum(a.verdict == "REJECT" and a.module_a_ran for a in full.assessments),
        "full_verdict": full.disposition.verdict, "full_pda": full.disposition.pda_result,
        "early_b_reject": sum(a.verdict == "REJECT" for a in early.assessments),
        "early_verdict": early.disposition.verdict,
    }


def scan() -> int:
    print("seed full_flagged A_REJECT full_verdict full_pda early_B_REJECT early_verdict")
    for seed in range(1, LIVE_SCAN_MAX + 1):
        r = scan_seed(seed)
        print(f"{seed:>4} {r['full_flagged']:>12} {r['a_reject']:>8} {r['full_verdict']:<12} {r['full_pda']:.4f} "
              f"{r['early_b_reject']:>13} {r['early_verdict']}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scan", action="store_true", help="print the LIVE_SEED scan table and exit")
    args = parser.parse_args(argv)
    if args.scan:
        return scan()
    for path in write_all():
        print(f"wrote {path.relative_to(OUT_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
