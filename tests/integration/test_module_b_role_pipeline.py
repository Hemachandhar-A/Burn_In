"""Session I3 Part 3b: the Module B finished-lot role through the real pipeline.

* a COMPLETE lot's verdicts under each role equal the pre-registered offline combination (scripts/module_b_role_experiment.py);
* an in-progress lot (DEMO-EARLY-01) is identical under every role;
* under `advisory` a part whose forecast exceeds the slope carries an information note, under no other role."""
import pytest

from contracts import LotDataset, ScreeningConfig
from fusion.pipeline import run_full_pipeline
from fusion.settings import MODULE_B_ROLES
from harness.held_out import generate_held_out_set, ground_truth_labels
from scripts import load_demo_lots as demo
from scripts.module_b_role_experiment import add_variants, extract_lot


@pytest.fixture(scope="module")
def noisy_lot():
    hset = generate_held_out_set("different_noise_regime", seed=7301, min_lots=1, min_per_archetype=1, lot_id_prefix="V7301")
    return hset.lots[0]


@pytest.fixture(scope="module")
def offline(noisy_lot):
    return add_variants(extract_lot(noisy_lot.dataset, ground_truth_labels(noisy_lot))).set_index("component_id")


def _run(lot, monkeypatch, role):
    monkeypatch.setenv("MODULE_B_FINISHED_LOT_ROLE", role)
    return run_full_pipeline(lot.dataset, ScreeningConfig(), _explain_cache=False)


@pytest.mark.parametrize("role", MODULE_B_ROLES)
def test_complete_lot_verdicts_equal_the_offline_combination(noisy_lot, offline, monkeypatch, role):
    res = _run(noisy_lot, monkeypatch, role)
    got = {a.component_id: a.verdict for a in res.assessments}
    assert got == offline[f"verdict_{role}"].to_dict()
    rejects = sum(v == "REJECT" for v in got.values())
    assert res.disposition.pda_result == pytest.approx(rejects / len(got))  # failures = REJECT parts on a finished lot


def test_roles_actually_differ_on_this_lot(noisy_lot, monkeypatch):
    flagged = {r: sum(a.verdict != "PASS" for a in _run(noisy_lot, monkeypatch, r).assessments) for r in MODULE_B_ROLES}
    assert flagged["current"] > flagged["advisory"] == flagged["off"]
    assert flagged["tiered"] == flagged["current"]  # B REVIEW is still WATCH: flagged either way, only the tier differs


def test_advisory_note_only_under_advisory(noisy_lot, offline, monkeypatch):
    b_exceeds = {cid for cid, r in offline.iterrows() if r["b_exceeds"] is True or r["b_exceeds"] == "True"}
    assert b_exceeds
    res = _run(noisy_lot, monkeypatch, "advisory")
    assert set(res.module_b_advisory_notes) == b_exceeds
    some_pass = [a.component_id for a in res.assessments if a.verdict == "PASS" and a.component_id in b_exceeds]
    assert some_pass, "the experiment's point: parts that B alone used to flag are now PASS but still carry the forecast note"
    note = res.module_b_advisory_notes[some_pass[0]]
    assert "information" in note.lower() and "Module A" in note
    for role in ("current", "tiered", "off"):
        assert _run(noisy_lot, monkeypatch, role).module_b_advisory_notes == {}


@pytest.mark.parametrize("role", MODULE_B_ROLES)
def test_in_progress_lot_is_identical_under_every_role(monkeypatch, role):
    monkeypatch.setenv("MODULE_B_FINISHED_LOT_ROLE", role)
    readings = demo.generated_readings("DEMO-EARLY-01", demo.EARLY_SEED, demo.EARLY_CHECKPOINTS)
    ds = LotDataset(lot_id="DEMO-EARLY-01", part_number="DEMO-PN", status="IN_PROGRESS", readings=readings, account_id="a.sharma")
    r = run_full_pipeline(ds, ScreeningConfig())
    flagged = [a for a in r.assessments if a.verdict != "PASS"]
    assert (r.disposition.verdict, round(r.disposition.pda_result, 4), len(flagged)) == ("LOT_AT_RISK", 0.1429, 11)
    assert r.module_b_advisory_notes == {}
