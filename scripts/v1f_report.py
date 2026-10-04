"""Tables for F-R4 / F-R5 from docs/evidence_data/adoption/v1f/ (written by scripts.v1f_validate)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from harness import variants as hv

OUT = Path("docs/evidence_data/adoption/v1f")
FR5_SIZES = (30, 50, 60)
PREVS = (3, 5, 8)


def _paired_cost_diff(t: pd.DataFrame, reps: int = 1000, seed: int = hv.BOOTSTRAP_SEED):
    codes, uniq = pd.factorize(t["lot_id"])
    y = t["is_defective"].to_numpy(bool)

    def per_lot(flag):
        fn = np.bincount(codes, weights=(y & ~flag).astype(float), minlength=len(uniq))
        fp = np.bincount(codes, weights=(~y & flag).astype(float), minlength=len(uniq))
        return 10.0 * fn + fp

    a, b = per_lot(t["v1f_review"].to_numpy(bool)), per_lot(t["cur_review"].to_numpy(bool))
    n = np.bincount(codes, minlength=len(uniq)).astype(float)
    idx = np.random.default_rng(seed).integers(0, len(uniq), size=(reps, len(uniq)))
    d = (a[idx].sum(1) - b[idx].sum(1)) / n[idx].sum(1)
    return float((a.sum() - b.sum()) / n.sum()), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def fr4_table() -> pd.DataFrame:
    rows = [json.loads(p.read_text()) for p in sorted(OUT.glob("fr4_n*.json"), key=lambda p: int(p.stem.split("n")[-1]))]
    return pd.DataFrame(rows)


def fr5_tables():
    cells, pooled = [], []
    for n in FR5_SIZES:
        parts = []
        for p in PREVS:
            f = OUT / f"fr5_n{n}_p{p}.csv.gz"
            if not f.exists():
                continue
            t = pd.read_csv(f)
            parts.append(t)
            cells.append(_row(t, f"n={n} prev={p}%"))
        if parts:
            pooled.append(_row(pd.concat(parts, ignore_index=True), f"n={n} pooled"))
    return pd.DataFrame(cells), pd.DataFrame(pooled)


def _row(t: pd.DataFrame, label: str) -> dict:
    out = {"cell": label, "lots": t["lot_id"].nunique(), "parts": len(t), "defective": int(t.is_defective.sum())}
    for key, col in (("v1f", "v1f_review"), ("cur", "cur_review")):
        m = hv.lot_bootstrap_metrics(t, col)
        out.update({f"{key}_cost": m["cost_per_part"], f"{key}_cost_lo": m["cost_per_part_ci_lo"],
                    f"{key}_cost_hi": m["cost_per_part_ci_hi"], f"{key}_recall": m["recall"],
                    f"{key}_recall_lo": m["recall_ci_lo"], f"{key}_recall_hi": m["recall_ci_hi"],
                    f"{key}_flag": m["flag_rate"]})
    d, lo, hi = _paired_cost_diff(t)
    out.update({"cost_diff": d, "cost_diff_lo": lo, "cost_diff_hi": hi,
                "cost_ok": out["v1f_cost"] <= out["cur_cost"], "recall_ok": out["v1f_recall"] >= 0.70})
    return out


def main() -> int:
    pd.set_option("display.width", 250, "display.max_columns", 40)
    f4 = fr4_table()
    f4.to_csv(OUT / "fr4_table.csv", index=False)
    print(f4.round(4).to_string(index=False))
    cells, pooled = fr5_tables()
    cells.to_csv(OUT / "fr5_cells.csv", index=False)
    pooled.to_csv(OUT / "fr5_pooled.csv", index=False)
    print(cells.round(3).to_string(index=False))
    print(pooled.round(3).to_string(index=False))
    return 0
