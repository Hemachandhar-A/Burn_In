"""Session I2c Part 1c: V1F validation on FRESH seeds (docs/ADOPTION_PLAN_ADDENDUM.md).

    python -m scripts.v1f_validate fr4 [--sizes ...]   # clean-lot flag rate through run_full_pipeline (seed 7102)
    python -m scripts.v1f_validate fr5                 # lots WITH defects, V1F vs current rank scoring, n in {30, 50, 60}
    python -m scripts.v1f_validate report              # tables from the saved files

Resumable: one JSON / csv.gz per cell under docs/evidence_data/adoption/v1f/. Thresholds are NOT re-tuned.
"""
import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("docs/evidence_data/adoption/v1f")
FR4_SEED = 7102
FR4_SIZES = (15, 20, 30, 40, 50, 60, 77, 100, 150)
FR5_SEEDS = {0.03: 7103, 0.05: 7104, 0.08: 7105}
FR5_SIZES = (30, 50, 60)
LOTS_PER_FAMILY = 12
REVIEW_V1 = 2.956
BOOT_REPS, BOOT_SEED = 1000, 20261004


def fr4_lots(n: int) -> int:
    return 100 if n <= 60 else 40


def _lot_boot_ci(per_lot_flag: np.ndarray, per_lot_n: np.ndarray) -> tuple[float, float]:
    idx = np.random.default_rng(BOOT_SEED).integers(0, len(per_lot_n), size=(BOOT_REPS, len(per_lot_n)))
    v = per_lot_flag[idx].sum(1) / per_lot_n[idx].sum(1)
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def run_fr4(n: int) -> dict:
    os.environ["MODULE_A_SCORING"] = "absolute"
    from contracts import ScreeningConfig
    from fusion.pipeline import run_full_pipeline
    from generator.lot import generate_lot
    from harness.variants import clean_family

    family = clean_family("baseline")
    flagged, total = [], []
    for i in range(fr4_lots(n)):
        lot = generate_lot(f"I2C-CLEAN-{n}-{i:03d}", "PN-I2C", FR4_SEED, account_id="i2c", family=family, n_parts=n).dataset
        res = run_full_pipeline(lot, ScreeningConfig(), _explain_cache=False)
        vals = list(res.module_a_results.values())
        flagged.append(sum(a.severity_tier != "PASS" for a in vals))
        total.append(len(vals))
    f, t = np.array(flagged, float), np.array(total, float)
    lo, hi = _lot_boot_ci(f, t)
    return {"n": n, "lots": len(t), "parts": int(t.sum()), "seed": FR4_SEED, "flag_rate": float(f.sum() / t.sum()),
            "ci_lo": lo, "ci_hi": hi, "criterion_le_0.05": bool(f.sum() / t.sum() <= 0.05) if n >= 30 else None}


def run_fr5_cell(n: int, prev: float) -> pd.DataFrame:
    from features.compute import compute
    from generator.families import FAMILIES
    from generator.lot import generate_lot
    from harness.held_out import ground_truth_labels
    from module_a import detect as md
    from module_a.settings import ABSOLUTE_REVIEW_THRESHOLD, MCD_MIN_PARTS_ABSOLUTE
    from module_a.scoring import ScoringConfig
    from module_a.settings import ABSOLUTE_REJECT_THRESHOLD, DISPLAY_S0

    os.environ["MODULE_A_SCORING"] = "absolute"
    from module_a.settings import module_a_scoring_config
    v1f = module_a_scoring_config()
    assert v1f.mcd_min_parts == MCD_MIN_PARTS_ABSOLUTE
    cur_review = md._THRESHOLDS.module_a_review_threshold
    rows = []
    for fam_name, fam in FAMILIES.items():
        family = dataclasses.replace(fam, name=f"{fam.name}__p{int(prev*100)}",
                                     config=fam.config.model_copy(update={"defect_prevalence_range": (prev, prev)}))
        for i in range(LOTS_PER_FAMILY):
            lot = generate_lot(f"I2C-DEF-{fam_name}-{n}-{int(prev*100)}-{i:02d}", "PN-I2C", FR5_SEEDS[prev],
                               account_id="i2c", family=family, n_parts=n)
            frames = compute(lot.dataset)
            labels = ground_truth_labels(lot)
            a = pd.DataFrame([(r.component_id, r.severity_log10p) for r in md.detect(frames, scoring=v1f)],
                             columns=["component_id", "v1f_s"]).groupby("component_id", as_index=False).max()
            c = pd.DataFrame([(r.component_id, r.combined_severity) for r in md.detect(frames)],
                             columns=["component_id", "cur_score"]).groupby("component_id", as_index=False).max()
            t = labels.merge(a, on="component_id", validate="one_to_one").merge(c, on="component_id", validate="one_to_one")
            t["family_key"], t["n"], t["prevalence"] = fam_name, n, prev
            rows.append(t)
    t = pd.concat(rows, ignore_index=True)
    t["v1f_review"] = t["v1f_s"] >= ABSOLUTE_REVIEW_THRESHOLD
    t["cur_review"] = t["cur_score"] >= cur_review
    return t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("fr4", "fr5", "report"))
    ap.add_argument("--sizes", type=int, nargs="*")
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.what == "fr4":
        for n in args.sizes or FR4_SIZES:
            p = OUT / f"fr4_n{n}.json"
            if p.exists():
                print(f"n={n}: exists", flush=True)
                continue
            r = run_fr4(n)
            p.write_text(json.dumps(r, indent=2), encoding="utf-8")
            print(r, flush=True)
    elif args.what == "fr5":
        for n in args.sizes or FR5_SIZES:
            for prev in FR5_SEEDS:
                p = OUT / f"fr5_n{n}_p{int(prev*100)}.csv.gz"
                if p.exists():
                    print(f"n={n} prev={prev}: exists", flush=True)
                    continue
                t = run_fr5_cell(n, prev)
                t.to_csv(p, index=False, compression="gzip")
                print(f"n={n} prev={prev}: {len(t)} parts, defective {int(t.is_defective.sum())}", flush=True)
    else:
        from scripts.v1f_report import main as rep
        return rep()
    return 0


if __name__ == "__main__":
    sys.exit(main())
