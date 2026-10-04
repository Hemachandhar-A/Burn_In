"""Session I2a diagnostic: how well does V1's calibration hold when the data ARE Gaussian?

Simulates exactly what V1 assumes: n parts with 3 iid N(0,1) columns (or one column for the z leg), fits sklearn's MinCovDet
the way module_a does (random_state=42, default reweighting), converts squared distances with the chi-square tail (df = 3) and
z-scores with the normal tail, and reports the share of scores with p below 1e-2, 1e-3 and 1e-4 against the nominal share.
The z leg uses the SAMPLE median and sigma = IQR / 1.35 exactly like features.compute._robust_stats.

    python -m scripts.adoption_gaussian_null [--trials 1000]

Any gap here is estimator error at finite n (not the generator's tails); a gap that is larger on the generator's lots
(docs/evidence_data/adoption/calibration_n*.json) than here is due to non-Gaussian healthy noise.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import chi2, norm
from sklearn.covariance import MinCovDet

SIZES = (15, 20, 30, 40, 50, 60, 77, 100, 150)
TS = (1e-2, 1e-3, 1e-4)


def run(trials: int, seed: int = 20261004) -> dict:
    rng = np.random.default_rng(seed)
    out = {}
    for n in SIZES:
        mcd_p, z_p = [], []
        for _ in range(trials):
            X = rng.standard_normal((n, 3))
            if n >= 30:
                sq = MinCovDet(random_state=42).fit(X).mahalanobis(X)
                mcd_p.append(chi2.sf(sq, 3))
            for col in range(3):
                x = X[:, col]
                med = np.median(x)
                q75, q25 = np.percentile(x, [75, 25])
                sig = (q75 - q25) / 1.35
                z_p.append(2 * norm.sf(np.abs((x - med) / sig)))
        row = {"trials": trials, "n_z_scores": int(np.concatenate([np.atleast_1d(a) for a in z_p]).size)}
        zz = np.concatenate([np.atleast_1d(a) for a in z_p])
        row["z"] = {f"{t:g}": float(np.mean(zz < t)) for t in TS}
        if mcd_p:
            mm = np.concatenate(mcd_p)
            row["mcd"] = {f"{t:g}": float(np.mean(mm < t)) for t in TS}
        out[str(n)] = row
        print(n, row["z"], row.get("mcd"), flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1000)
    args = ap.parse_args()
    res = run(args.trials)
    path = Path("docs/evidence_data/adoption/gaussian_null.json")
    path.write_text(json.dumps(res, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
