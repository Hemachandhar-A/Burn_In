"""Gate logic of scripts/system_benchmark.py (docs/SYSTEM_LEVEL_BENCHMARK.md), pinned before the run."""
from scripts.system_benchmark import evaluate_gates


def row(cost, recall, lo, hi):
    return {"cost_per_part": cost, "recall": recall, "cost_per_part_ci_lo": lo, "cost_per_part_ci_hi": hi,
            "recall_ci_lo": recall - 0.02, "recall_ci_hi": recall + 0.02}


def test_gflip_holds_when_cost_and_recall_within_margins():
    g = evaluate_gates(row(0.10, 0.90, 0.09, 0.11), row(0.11, 0.88, 0.1, 0.12), row(0.03, 0.98, 0.02, 0.05))
    assert g["G_flip"]["holds"] is True


def test_gflip_fails_on_cost_or_recall():
    assert evaluate_gates(row(0.30, 0.90, .2, .4), row(0.10, 0.90, .09, .11), row(0.03, .98, .02, .05))["G_flip"]["holds"] is False
    assert evaluate_gates(row(0.10, 0.80, .09, .11), row(0.10, 0.90, .09, .11), row(0.03, .98, .02, .05))["G_flip"]["holds"] is False


def test_t1_needs_both_gaps_and_separated_cis():
    g = evaluate_gates(row(0.12, 0.85, 0.11, 0.13), row(0.12, 0.85, .11, .13), row(0.03, 0.98, 0.02, 0.05))
    assert g["T1"]["fired"] is True and g["T2"]["fired"] is False
    overlap = evaluate_gates(row(0.12, 0.85, 0.04, 0.2), row(0.12, 0.85, .11, .13), row(0.03, 0.98, 0.02, 0.05))
    assert overlap["T1"]["fired"] is False


def test_t2_when_within_003_or_lower():
    g = evaluate_gates(row(0.05, 0.95, .04, .06), row(0.1, 0.9, .09, .11), row(0.03, 0.98, 0.02, 0.05))
    assert g["T2"]["fired"] is True and g["T1"]["fired"] is False
