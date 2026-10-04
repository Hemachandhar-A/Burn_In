"""Session I2a: Module A absolute scoring through the application pipeline (fusion.run_full_pipeline).

(ii) clean-lot flag share at lot sizes 15, 30, 77, 150; (iii) the golden fixture; (v) no ties at the top for 100
generated lots; (vii) the DPA highest-severity part is module_a_rank 1. MODULE_A_SCORING=absolute throughout."""
import math

import pytest

from contracts import ScreeningConfig
from features.compute import compute
from fusion.pipeline import run_full_pipeline
from generator.lot import generate_lot
from harness import golden
from harness.variants import clean_family
from module_a.detect import detect
from module_a.settings import DISPLAY_S0, module_a_scoring_config

N_CLEAN_LOTS = 20
CLEAN_SEED = 7101  # not a tuning / evaluation / sensitivity / shipped-threshold seed


@pytest.fixture(autouse=True)
def absolute_mode(monkeypatch):
    monkeypatch.setenv("MODULE_A_SCORING", "absolute")


def _clean_flag_share(n_parts: int) -> tuple[float, int]:
    family = clean_family("baseline")
    flagged = total = 0
    for i in range(N_CLEAN_LOTS):
        lot = generate_lot(f"I2A-CLEAN-{n_parts}-{i:02d}", "PN-I2A", CLEAN_SEED, account_id="i2a", family=family,
                           n_parts=n_parts).dataset
        results = run_full_pipeline(lot, ScreeningConfig(), _explain_cache=False)
        assert all(r.severity_log10p is not None for r in results.module_a_results.values())
        for a in results.module_a_results.values():
            total += 1
            flagged += a.severity_tier != "PASS"
    return flagged / total, total


@pytest.mark.parametrize("n_parts", [
    30,  # was a strict xfail under V1 (0.2233); V1F (MCD leg only from 77 parts) passes it - session I2c
    77, 150])
def test_p1_clean_lot_flag_share_through_the_app_is_at_most_5_percent(n_parts, capsys):
    share, total = _clean_flag_share(n_parts)
    with capsys.disabled():
        print(f"\nP1 through run_full_pipeline, size {n_parts}: {share:.4f} of {total} parts at or above REVIEW")
    assert total == N_CLEAN_LOTS * n_parts
    assert share <= 0.05


def test_p1_clean_lot_flag_share_at_size_15_is_reported(capsys):
    """Size 15 is below the MCD floor (30), so only the robust-z leg scores; the value is reported, not bounded."""
    share, total = _clean_flag_share(15)
    with capsys.disabled():
        print(f"\nP1 through run_full_pipeline, size 15 (z leg only): {share:.4f} of {total} parts at or above REVIEW")
    assert 0.0 <= share <= 1.0 and total == N_CLEAN_LOTS * 15


def test_golden_part_is_reject_and_rank_one():
    lot = golden.golden_lot()
    results = run_full_pipeline(lot, ScreeningConfig(), _explain_cache=False)
    a = next(x for x in results.assessments if x.component_id == golden.GOLDEN_COMPONENT_ID)
    m = results.module_a_results[golden.GOLDEN_COMPONENT_ID]
    assert m.severity_tier == "REJECT" and m.severity_log10p > 10.0
    assert 0.9 < m.combined_severity < 1.0
    assert a.verdict == "REJECT"
    assert a.module_a_rank == 1.0


def test_no_ties_at_the_top_for_100_generated_lots():
    cfg = module_a_scoring_config()
    for i in range(100):
        lot = generate_lot(f"I2A-TIE-{i:03d}", "PN-I2A", 7201, account_id="i2a").dataset
        part_s: dict[str, float] = {}
        part_t: dict[str, float] = {}
        for r in detect(compute(lot), scoring=cfg):
            part_s[r.component_id] = max(part_s.get(r.component_id, -1.0), r.severity_log10p)
            part_t[r.component_id] = max(part_t.get(r.component_id, -1.0), r.combined_severity)
        top = sorted(part_s.values(), reverse=True)
        assert top[0] > top[1], f"tie at the top on s in lot {i}"
        assert max(part_t.values()) < 1.0
        assert all(math.isfinite(v) for v in part_s.values())


def test_dpa_highest_severity_part_is_module_a_rank_one():
    from capa.logic import select_dpa_work_order

    checked = 0
    for i in range(12):
        lot = generate_lot(f"I2A-DPA-{i:02d}", "PN-I2A", 7301, account_id="i2a").dataset
        results = run_full_pipeline(lot, ScreeningConfig(), _explain_cache=False)
        top = next(a for a in results.assessments if a.module_a_rank == 1.0)
        if top.verdict == "PASS":
            continue
        recs = select_dpa_work_order(results)
        assert recs[0].reason.startswith("Highest combined severity in the lot (")
        assert recs[0].component_id == top.component_id
        assert "severity index " in recs[0].reason and "flag threshold 2.96" in recs[0].reason
        assert "1 in" not in recs[0].reason and "healthy parts" not in recs[0].reason
        checked += 1
    assert checked >= 6


def test_top_of_a_defective_lot_scores_far_above_the_reject_threshold():
    lot = generate_lot("I2A-DEF-0", "PN-I2A", 7401, account_id="i2a", family="higher_defect_prevalence").dataset
    results = run_full_pipeline(lot, ScreeningConfig(), _explain_cache=False)
    best = max(results.module_a_results.values(), key=lambda r: r.severity_log10p)
    assert best.severity_tier == "REJECT" and best.severity_log10p > 3.419
    assert best.combined_severity > 1 - math.exp(-3.419 / DISPLAY_S0)
