"""Session I3 Part 4a: Module A's cost-optimal (REVIEW s, REJECT s) per FN:FP ratio, on the TUNING side only (seed 6101, five families).

    python -m scripts.fnfp_threshold_table          # prints the table and writes docs/evidence_data/fnfp/threshold_table.csv

For a Settings ratio R the REJECT cut is the cost-optimal V1F score threshold at FN:FP = R and the REVIEW cut the one at 2R: the same
pairing the shipped constants have (REVIEW tuned at 20:1, REJECT at 10:1, module_a/settings.py), so R = 10 is the default.
Optimizer: harness.scoring.tune_threshold. Scores: docs/evidence_data/adoption/transfer/tuning_v1f_scores.csv.gz (V1F score of every
tuning part, seed 6101); labels: docs/evidence_data/adoption/v1f/baseline_tuning_parts.csv.gz. No published-protocol (seed 2026) data is read.
"""
from pathlib import Path

import pandas as pd

from harness import scoring as hs

RATIOS = (1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 100)
OUT = Path("docs/evidence_data/fnfp/threshold_table.csv")


def table() -> pd.DataFrame:
    labels = pd.read_csv("docs/evidence_data/adoption/v1f/baseline_tuning_parts.csv.gz", usecols=["lot_id", "component_id", "is_defective"])
    scores = pd.read_csv("docs/evidence_data/adoption/transfer/tuning_v1f_scores.csv.gz")
    m = scores.merge(labels, on=["lot_id", "component_id"], validate="one_to_one")
    s, y = m["v1f_score"].to_numpy(float), m["is_defective"].astype(bool).to_numpy()
    rows = []
    for r in RATIOS:
        review, reject = hs.tune_threshold(s, y, 2 * r), hs.tune_threshold(s, y, r)
        rows.append({"ratio": r, "review_s": round(review, 4), "reject_s": round(reject, 4),
                     "tuning_flag_rate_at_review": round(float((s >= review).mean()), 4),
                     "tuning_recall_at_review": round(float((y & (s >= review)).sum() / y.sum()), 4)})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    t = table()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(OUT, index=False)
    print(t.to_string(index=False))
