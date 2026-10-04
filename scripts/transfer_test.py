"""Session I2b Part 6 (optional): leave-one-family-out transfer test.

    python -m scripts.transfer_test score     # V1F scores on the tuning side (seed 6101), saved
    python -m scripts.transfer_test report    # per held-out family: cuts tuned on the other four families, evaluated on the published protocol

For each held-out family F, the single cut of fixed delta, dynamic PAT and V1F (REVIEW) is tuned with harness.scoring.tune_threshold
(FN:FP 10:1, flag at score >= cut) on the tuning-side parts (seed 6101) of the OTHER four families, then applied to F's published-protocol
parts (seed 2026, live configuration). Same optimiser, same cost ratio, same data for all three methods. Measurement only.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ADOPT = Path("docs/evidence_data/adoption")
OUT = ADOPT / "transfer"
TUNING_BASELINES = ADOPT / "v1f" / "baseline_tuning_parts.csv.gz"
LIVE = Path("docs/evidence_data/live_benchmark/parts_live.csv.gz")
ABS = ADOPT / "parts_absolute_live.csv.gz"
METHODS = ("fixed_delta", "dynamic_pat", "v1f")


def lofo_cuts(tune: pd.DataFrame, score_col: str, family_col: str = "family") -> dict[str, float]:
    """Cut for each family, tuned on the OTHER families' parts only (FN:FP 10:1)."""
    from harness import scoring as hs

    cuts = {}
    for fam in sorted(tune[family_col].unique()):
        rest = tune[tune[family_col] != fam]
        rest = rest[rest[score_col].notna()]
        cuts[fam] = hs.tune_threshold(rest[score_col].to_numpy(float), rest["is_defective"].to_numpy(bool), hs.FN_FP_COST_RATIO)
    return cuts


def score_tuning_side() -> Path:
    """V1F part scores s for the tuning-side lots (5 families x 100 lots, seed 6101), merged onto the baseline tuning table."""
    from harness import scoring as hs
    from harness import variants as hv
    from module_a.scoring import ScoringConfig
    from module_a.settings import (ABSOLUTE_REJECT_THRESHOLD, ABSOLUTE_REVIEW_THRESHOLD, MCD_MIN_PARTS_ABSOLUTE)

    path = OUT / "tuning_v1f_scores.csv.gz"
    if path.exists():
        return path
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = ScoringConfig(calibration="absolute", combination="max", review_threshold=ABSOLUTE_REVIEW_THRESHOLD,
                        reject_threshold=ABSOLUTE_REJECT_THRESHOLD, mcd_min_parts=MCD_MIN_PARTS_ABSOLUTE)

    class _Set:
        pass

    frames = []
    side = hv.SIDES["tune"]
    for key in hv.FAMILY_NAMES:
        s = _Set()
        s.lots = hv.generate_lots(side, key, hv.setting_family(key))
        sc = hs.variant_part_scores(hs.run_module_a(s, scoring=cfg)).rename(columns={"score": "v1f_score"})
        sc["family_key"] = key
        frames.append(sc)
        print(key, len(sc), flush=True)
    pd.concat(frames, ignore_index=True).to_csv(path, index=False, compression="gzip")
    return path


def report() -> int:
    from harness import variants as hv

    keys = ["lot_id", "component_id"]
    tune = pd.read_csv(TUNING_BASELINES).merge(pd.read_csv(score_tuning_side())[keys + ["v1f_score"]], on=keys, how="left",
                                               validate="one_to_one")
    assert tune["v1f_score"].notna().all()
    test = pd.read_csv(LIVE).merge(pd.read_csv(ABS)[keys + ["absolute_score"]], on=keys, how="left", validate="one_to_one")
    test = test.rename(columns={"absolute_score": "v1f_score"})
    test["v1f_evaluable"] = True
    for b in ("fixed_delta", "dynamic_pat"):
        test[f"{b}_evaluable"] = test[f"{b}_evaluable"].astype(bool)
    cuts = {m: lofo_cuts(tune.assign(family=tune["family_key"]), f"{m}_score") for m in METHODS}
    rows, flagged_cols = [], {}
    for m in METHODS:
        col = f"{m}_lofo_flagged"
        test[col] = False
        for fam, cut in cuts[m].items():
            sel = (test["family"] == fam) & test[f"{m}_evaluable"]
            test.loc[sel, col] = test.loc[sel, f"{m}_score"].to_numpy(float) >= cut
        flagged_cols[m] = col
    for m in METHODS:
        for fam, g in [*test.groupby("family", sort=True), ("ALL (pooled)", test)]:
            r = hv.lot_bootstrap_metrics(g, flagged_cols[m], judged_col=f"{m}_evaluable")
            rows.append({"method": m, "family": fam, "cut": cuts[m].get(fam), **{k: r[k] for k in (
                "n_parts", "n_defective", "n_flagged", "flag_rate", "recall", "cost_per_part", "cost_per_part_ci_lo",
                "cost_per_part_ci_hi")}})
    table = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT / "transfer_table.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 40)
    print(table.round(3).to_string(index=False))
    fam_only = table[table.family != "ALL (pooled)"]
    print("\nmean over the five held-out families (equal weight):")
    print(fam_only.groupby("method")[["flag_rate", "recall", "cost_per_part"]].mean().round(3).to_string())
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("score", "report"))
    a = ap.parse_args(argv)
    if a.what == "score":
        score_tuning_side()
        return 0
    return report()


if __name__ == "__main__":
    sys.exit(main())
