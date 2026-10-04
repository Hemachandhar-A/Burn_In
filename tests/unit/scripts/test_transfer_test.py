"""scripts/transfer_test.py: leave-one-family-out thresholds never see the held-out family."""
import numpy as np
import pandas as pd

from harness import scoring as hs
from scripts.transfer_test import lofo_cuts


def _table():
    rng = np.random.default_rng(0)
    rows = []
    for fam, shift in (("a", 0.0), ("b", 0.2), ("c", 5.0)):  # family c is on a different scale: its own data would move the cut
        for i in range(400):
            y = i % 20 == 0
            rows.append({"family": fam, "is_defective": y, "score": rng.normal(shift + (3 if y else 0), 1)})
    return pd.DataFrame(rows)


def test_cut_for_a_held_out_family_is_tuned_on_the_other_families_only():
    t = _table()
    cuts = lofo_cuts(t, "score")
    for fam in ("a", "b", "c"):
        rest = t[t.family != fam]
        assert cuts[fam] == hs.tune_threshold(rest["score"].to_numpy(), rest["is_defective"].to_numpy(bool), hs.FN_FP_COST_RATIO)
    assert cuts["c"] != hs.tune_threshold(t["score"].to_numpy(), t["is_defective"].to_numpy(bool), hs.FN_FP_COST_RATIO)
