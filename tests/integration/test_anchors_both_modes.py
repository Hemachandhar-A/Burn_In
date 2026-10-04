"""demo-v2 (session I2b 2c): the demo anchors in BOTH scoring modes through the pipeline (no DB, no HTTP).

default (absolute, V1F)  -> the demo-v2 seeds (scripts.load_demo_lots.COMPLETE_SEED, scripts.make_demo_csvs.LIVE_SEED) and numbers
MODULE_A_SCORING=rank    -> the demo-v1.2 seeds (5 and 32) and their old numbers, so the legacy path stays covered
DEMO-EARLY-01 is Module B only (Module A never runs on an in-progress lot): identical in both modes."""
import pytest

from contracts import LotDataset, ScreeningConfig
from fusion.pipeline import run_full_pipeline
from scripts import load_demo_lots as demo
from scripts import make_demo_csvs as live

OLD_COMPLETE_SEED, OLD_LIVE_SEED = 5, 32  # demo-v1.2 (rank scoring)


def _run(lot_id, seed, status, hours=None, maker=None):
    readings = maker(seed)
    if hours is not None:
        readings = [r for r in readings if r.checkpoint_hour in hours]
    ds = LotDataset(lot_id=lot_id, part_number="DEMO-PN", status=status, readings=readings, account_id="a.sharma")
    r = run_full_pipeline(ds, ScreeningConfig())
    flagged = [a for a in r.assessments if a.verdict != "PASS"]
    top = min((a for a in flagged if a.module_a_rank), key=lambda a: (a.module_a_rank, a.component_id), default=None)
    return r.disposition.verdict, round(r.disposition.pda_result, 4), len(flagged), top.component_id if top else None


def _complete(seed):
    return lambda s: demo.generated_readings("DEMO-COMPLETE-01", s)


def test_default_mode_anchors_are_the_demo_v2_numbers(monkeypatch):
    monkeypatch.delenv("MODULE_A_SCORING", raising=False)
    assert demo.COMPLETE_SEED == 2 and live.LIVE_SEED == 2
    assert _run("DEMO-COMPLETE-01", demo.COMPLETE_SEED, "COMPLETE", maker=_complete(0)) == (
        "HOLD", 0.0390, 4, "DEMO-COMPLETE-01-0052")  # demo-v2.1: was REJECT, 0.0779, 7 until Module B stopped deciding finished lots
    verdict, pda, flagged, _ = _run("LIVE-01", live.LIVE_SEED, "COMPLETE", maker=live.live_readings)
    assert (verdict, pda, flagged) == ("REJECT", 0.0649, 7)


def test_rank_mode_keeps_the_demo_v1_2_anchors(monkeypatch):
    monkeypatch.setenv("MODULE_A_SCORING", "rank")
    monkeypatch.setenv("MODULE_B_FINISHED_LOT_ROLE", "current")  # the demo-v1.2 numbers are rank scoring WITH Module B counting on a finished lot
    assert _run("DEMO-COMPLETE-01", OLD_COMPLETE_SEED, "COMPLETE", maker=_complete(0)) == (
        "REJECT", 0.0779, 15, "DEMO-COMPLETE-01-0004")
    verdict, pda, flagged, _ = _run("LIVE-01", OLD_LIVE_SEED, "COMPLETE", maker=live.live_readings)
    assert (verdict, pda, flagged) == ("REJECT", 0.0649, 13)


@pytest.mark.parametrize("mode", ["rank", "absolute"])
def test_early_lot_is_module_b_only_and_identical_in_both_modes(monkeypatch, mode):
    monkeypatch.setenv("MODULE_A_SCORING", mode)
    verdict, pda, flagged, _ = _run("DEMO-EARLY-01", demo.EARLY_SEED, "IN_PROGRESS", demo.EARLY_CHECKPOINTS,
                                    maker=lambda s: demo.generated_readings("DEMO-EARLY-01", s))
    assert (verdict, pda, flagged) == ("LOT_AT_RISK", 0.1429, 11)


def test_role_current_reproduces_the_demo_v2_finished_lot_numbers(monkeypatch):
    """MODULE_B_FINISHED_LOT_ROLE=current is the demo-v2 behaviour: V1F scoring with Module B counting on a finished lot."""
    monkeypatch.delenv("MODULE_A_SCORING", raising=False)
    monkeypatch.setenv("MODULE_B_FINISHED_LOT_ROLE", "current")
    assert _run("DEMO-COMPLETE-01", demo.COMPLETE_SEED, "COMPLETE", maker=_complete(0)) == (
        "REJECT", 0.0779, 7, "DEMO-COMPLETE-01-0052")
    verdict, pda, flagged, _ = _run("LIVE-01", live.LIVE_SEED, "COMPLETE", maker=live.live_readings)
    assert (verdict, pda, flagged) == ("REJECT", 0.0649, 7)
