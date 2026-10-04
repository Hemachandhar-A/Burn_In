"""Session I2a (ruling 2): is V1 calibrated? Clean-lot flag rate by lot size and detector leg, and the share of p-values
below 1e-2 / 1e-3 / 1e-4 against the nominal share.

    python -m scripts.adoption_calibration [--sizes 15 20 ...] [--out DIR]

For each lot size, clean lots (baseline family, defect prevalence 0, seed 7101) go through `fusion.run_full_pipeline`
with MODULE_A_SCORING=absolute: the "combined" columns are that pipeline's own Module A result (severity_log10p, tier).
The z-leg and MCD-leg columns, and the per-score calibration, are computed from the SAME lots with module_a.scoring's
own code (compute_lot_raw, the same chi-square / normal tail functions); the per-checkpoint MCD distances are refitted
the way compute_lot_raw fits them. Nothing here changes any default. Resumable: one JSON per lot size.

Counts: 100 lots for n <= 40, 40 lots above. Scores per part (K): see docs/ADOPTION_RESULT.md.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

SEED = 7101
SIZES = (15, 20, 30, 40, 50, 60, 77, 100, 150)
THRESHOLDS = (1e-2, 1e-3, 1e-4)
REVIEW_S = 2.956
OUT_DEFAULT = Path("docs/evidence_data/adoption")


def lots_for(n: int) -> int:
    return 100 if n <= 40 else 40


def _share(values: np.ndarray, t: float) -> float:
    return float(np.mean(values >= -math.log10(t))) if values.size else float("nan")


def run_size(n: int) -> dict:
    os.environ["MODULE_A_SCORING"] = "absolute"
    from sklearn.covariance import MinCovDet

    from contracts import ScreeningConfig
    from features.compute import build_mcd_matrix, compute
    from fusion.pipeline import run_full_pipeline
    from generator.lot import generate_lot
    from harness.variants import clean_family
    from module_a.detect import _MCD_LOT_SIZE_FLOOR, _RANDOM_STATE
    from module_a.scoring import _sev_z_absolute, chi2_neg_log10_sf, compute_lot_raw

    family = clean_family("baseline")
    comb, zleg, mleg = [], [], []        # part-level s (max over the part's scores)
    comb_tier = []                       # part-level tier != PASS from the pipeline
    z_scores, mcd_scores = [], []        # per-score s (every checkpoint x parameter / checkpoint)
    for i in range(lots_for(n)):
        lot = generate_lot(f"I2A-DIAG-{n}-{i:03d}", "PN-I2A", SEED, account_id="i2a", family=family, n_parts=n).dataset
        res = run_full_pipeline(lot, ScreeningConfig())
        for a in res.module_a_results.values():
            comb.append(a.severity_log10p)
            comb_tier.append(a.severity_tier != "PASS")
        frames = compute(lot)
        raw = compute_lot_raw(frames)
        part_z: dict[str, float] = {}
        part_m: dict[str, float] = {}
        sz = _sev_z_absolute(raw.z)
        for cid, s_z, s_m in zip(raw.component_ids, sz, raw.mcd_sev1):
            part_z[cid] = max(part_z.get(cid, 0.0), float(s_z))
            if not np.isnan(s_m):
                part_m[cid] = max(part_m.get(cid, 0.0), float(s_m))
        zleg += [part_z[c] for c in sorted(part_z)]
        mleg += [part_m[c] for c in sorted(part_m)]
        for f in frames:  # every per-checkpoint |z| of every frame
            for v in f.robust_z.values():
                z_scores.append(float(_sev_z_absolute(np.array([abs(v)]))[0]))
        if frames[0].lot_size >= _MCD_LOT_SIZE_FLOOR:
            for ck in sorted({c for f in frames for c in f.robust_z}):
                ids, _params, matrix = build_mcd_matrix(frames, ck)
                if len(ids) < _MCD_LOT_SIZE_FLOOR or not matrix:
                    continue
                X = np.array(matrix, dtype=float)
                try:
                    sq = MinCovDet(random_state=_RANDOM_STATE).fit(X).mahalanobis(X)
                except (ValueError, np.linalg.LinAlgError):
                    continue
                mcd_scores += [float(v) for v in chi2_neg_log10_sf(sq, X.shape[1])]
    comb, zleg, mleg = map(np.array, (comb, zleg, mleg))
    z_scores, mcd_scores = np.array(z_scores), np.array(mcd_scores)
    out = {
        "n": n, "lots": lots_for(n), "parts": int(comb.size), "seed": SEED, "family": "baseline, defect prevalence 0",
        "part_level_share_at_or_above_REVIEW_s2.956": {
            "combined_pipeline_tier": float(np.mean(comb_tier)),
            "combined_pipeline_s": _share(comb, 10 ** -REVIEW_S),
            "z_leg_alone": _share(zleg, 10 ** -REVIEW_S),
            "mcd_leg_alone": _share(mleg, 10 ** -REVIEW_S) if mleg.size else None,
        },
        "part_level_share_p_below": {
            f"{t:g}": {"combined": _share(comb, t), "z_leg": _share(zleg, t),
                       "mcd_leg": _share(mleg, t) if mleg.size else None} for t in THRESHOLDS},
        "per_score_share_p_below": {
            f"{t:g}": {"nominal": t, "z": _share(z_scores, t), "mcd": _share(mcd_scores, t) if mcd_scores.size else None}
            for t in THRESHOLDS},
        "n_scores": {"z": int(z_scores.size), "mcd": int(mcd_scores.size)},
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sizes", type=int, nargs="*", default=list(SIZES))
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for n in args.sizes:
        path = args.out / f"calibration_n{n}.json"
        if path.exists():
            print(f"n={n}: exists, skipped", flush=True)
            continue
        result = run_size(n)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"n={n}: done {result['part_level_share_at_or_above_REVIEW_s2.956']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
