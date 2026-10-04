"""demo-v2 Part 3: under absolute scoring the data the Part Detail screen labels its MCD / ECOD views from is right at both
lot sizes: n = 60 (MCD leg off, so no mcd_distance and tag mcd False) and n = 77 (MCD leg on). ECOD never scores."""
import pytest

from contracts import ScreeningConfig
from fusion.pipeline import run_full_pipeline
from generator.lot import generate_lot


def _flagged_module_a_part(n_parts):
    for seed in range(1, 40):
        lot = generate_lot(f"EV-{n_parts}", "DEMO-PN", seed, account_id="a.sharma", n_parts=n_parts).dataset
        results = run_full_pipeline(lot, ScreeningConfig())
        flagged = [a for a in results.assessments if a.verdict != "PASS" and a.module_a_ran]
        if flagged:
            return results, min(flagged, key=lambda a: (a.module_a_rank, a.component_id))
    pytest.fail("no flagged part in seeds 1..39")


@pytest.mark.parametrize("n_parts, mcd_leg_on", [(60, False), (77, True)])
def test_mcd_leg_signal_follows_lot_size_and_ecod_is_never_a_driver(monkeypatch, n_parts, mcd_leg_on):
    monkeypatch.delenv("MODULE_A_SCORING", raising=False)  # the default is absolute
    results, top = _flagged_module_a_part(n_parts)
    a = results.module_a_results[top.component_id]
    assert a.severity_log10p is not None                     # absolute scoring: the screen labels views from this
    assert a.explainable_tags["mcd"] is mcd_leg_on
    assert (a.mcd_distance is not None) is mcd_leg_on
    assert a.explainable_tags["ecod"] is False and a.explainable_tags["isolation_forest"] is False
    sentence = results.part_explanations[top.component_id].explanation_sentence
    assert "MCD" not in sentence and "ECOD" not in sentence  # the sentence never names a detector that did not drive it
