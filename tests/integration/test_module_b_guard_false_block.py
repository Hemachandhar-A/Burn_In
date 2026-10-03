"""F24 Part 1, T4: the guard's false-block rate on in-distribution data. Every held-out generator family, 100 lots
each (seeds 1000-1099, fixed before looking at any result), through the real module_b.predict path: the fraction of
parts declined for being out of range must stay at or below 1%. (20 lots would not do: one whole lot is 5% of
them, so the rate at that size measures which lots were drawn, not the guard.)"""

import pytest

from contracts import to_module_b_input
from features.compute import compute
from generator.families import HELD_OUT_FAMILY_NAMES
from generator.lot import generate_lot
from module_b import predict

N_LOTS = 100
MAX_RATE = 0.01
PART_NUMBER = "PN-T4"


@pytest.mark.parametrize("family", HELD_OUT_FAMILY_NAMES)
def test_guard_false_block_rate_is_at_most_one_percent(family, capsys):
    declined = total = 0
    for seed in range(1000, 1000 + N_LOTS):
        lot = generate_lot(f"HO-{family}-{seed}", PART_NUMBER, seed, account_id="harness", family=family)
        results = predict([to_module_b_input(f) for f in compute(lot.dataset)])
        total += len(results)
        declined += sum(r.forecast_unavailable for r in results)
    with capsys.disabled():
        print(f"\nT4 {family}: {declined}/{total} parts declined = {100 * declined / total:.3f}%")
    assert declined / total <= MAX_RATE
