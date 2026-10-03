"""Session I2a: the MODULE_A_SCORING switch, the display transform and the additive contract field.

(i) the default is rank and nothing changes; (iv) T is monotone; (vi) old stored JSON parses; the severity-index wording."""
import json
import math

import pytest

from contracts import AnalysisResults, ModuleAResult, ScreeningConfig
from features.compute import compute
from fusion.pipeline import run_full_pipeline
from generator.lot import generate_lot
from module_a.detect import detect
from module_a.scoring import ScoringConfig
from module_a.settings import (ABSOLUTE_REJECT_THRESHOLD, ABSOLUTE_REVIEW_THRESHOLD, DISPLAY_S0, display_transform,
                               module_a_scoring, module_a_scoring_config, severity_index_phrase)


def _absolute_cfg():
    return ScoringConfig(calibration="absolute", combination="max", review_threshold=ABSOLUTE_REVIEW_THRESHOLD,
                         reject_threshold=ABSOLUTE_REJECT_THRESHOLD, display_s0=DISPLAY_S0)


def test_default_is_rank_and_config_is_none(monkeypatch):
    monkeypatch.delenv("MODULE_A_SCORING", raising=False)
    assert module_a_scoring() == "rank"
    assert module_a_scoring_config() is None
    monkeypatch.setenv("MODULE_A_SCORING", "")
    assert module_a_scoring() == "rank"
    monkeypatch.setenv("MODULE_A_SCORING", "rank")
    assert module_a_scoring_config() is None


def test_absolute_config_and_invalid_value(monkeypatch):
    monkeypatch.setenv("MODULE_A_SCORING", "absolute")
    cfg = module_a_scoring_config()
    assert cfg.calibration == "absolute" and cfg.combination == "max" and cfg.display_s0 == DISPLAY_S0
    assert (cfg.review_threshold, cfg.reject_threshold) == (ABSOLUTE_REVIEW_THRESHOLD, ABSOLUTE_REJECT_THRESHOLD)
    assert (ABSOLUTE_REVIEW_THRESHOLD, ABSOLUTE_REJECT_THRESHOLD) == (2.956, 3.419)
    monkeypatch.setenv("MODULE_A_SCORING", "percentile")
    with pytest.raises(ValueError):
        module_a_scoring()


def test_rank_mode_pipeline_output_is_unchanged(monkeypatch):
    """Rank mode: the pipeline's Module A numbers equal a direct detect(frames) call and carry no severity_log10p."""
    monkeypatch.delenv("MODULE_A_SCORING", raising=False)
    lot = generate_lot("I2A-RANK-0", "PN-I2A", 7001, account_id="i2a").dataset
    direct = {(r.component_id, r.parameter): r for r in detect(compute(lot))}
    results = run_full_pipeline(lot, ScreeningConfig(), _explain_cache=False)
    assert results.module_a_results
    for cid, got in results.module_a_results.items():
        want = direct[(cid, got.parameter)]
        assert got.severity_log10p is None
        assert got.model_dump(exclude={"severity_log10p"}) == want.model_dump(exclude={"severity_log10p"})


def test_transform_is_monotone_bounded_and_documented_values():
    grid = [0.0, 0.1, 1.0, 2.956, 3.419, 5.0, 15.0, 55.0, 100.0, 140.0, 400.0, 1e6]
    vals = [display_transform(s) for s in grid]
    assert vals == sorted(vals)
    assert vals[0] == 0.0 and all(0.0 <= v < 1.0 for v in vals)
    assert all(a < b for a, b in zip(vals[:9], vals[1:9]))  # strictly increasing up to s = 100
    assert math.isclose(display_transform(3.419), 0.4952, abs_tol=1e-3)
    assert math.isclose(display_transform(2.956), 0.4465, abs_tol=1e-3)
    assert display_transform(-1e-17) == 0.0


def test_order_of_combined_severity_follows_s():
    """Under absolute scoring a strictly larger s never has a smaller combined_severity (T is monotone)."""
    lot = generate_lot("I2A-MONO-0", "PN-I2A", 7002, account_id="i2a").dataset
    res = detect(compute(lot), scoring=_absolute_cfg())
    by_s = sorted(res, key=lambda r: r.severity_log10p)
    for a, b in zip(by_s, by_s[1:]):
        assert b.combined_severity >= a.combined_severity
    top3_s = {(r.component_id, r.parameter) for r in by_s[-3:]}
    top3_t = {(r.component_id, r.parameter) for r in sorted(res, key=lambda r: r.combined_severity)[-3:]}
    assert top3_s == top3_t


def test_experiment_path_is_unchanged_without_display_s0():
    """display_s0=None (the experiment harness) keeps the raw severity in combined_severity and no s field."""
    cfg = ScoringConfig(calibration="absolute", review_threshold=2.956, reject_threshold=3.419)
    lot = generate_lot("I2A-EXP-0", "PN-I2A", 7003, account_id="i2a", family="higher_defect_prevalence").dataset
    res = detect(compute(lot), scoring=cfg)
    assert all(r.severity_log10p is None for r in res)
    assert max(r.combined_severity for r in res) > 1.0  # raw -log10 p, unbounded


def test_old_stored_json_without_the_new_field_still_parses():
    lot = generate_lot("I2A-JSON-0", "PN-I2A", 7004, account_id="i2a").dataset
    results = run_full_pipeline(lot, ScreeningConfig(), _explain_cache=False)
    blob = json.loads(results.model_dump_json())
    assert all("severity_log10p" in v for v in blob["module_a_results"].values())
    for v in blob["module_a_results"].values():
        del v["severity_log10p"]
    parsed = AnalysisResults.model_validate_json(json.dumps(blob))
    assert all(r.severity_log10p is None for r in parsed.module_a_results.values())
    assert ModuleAResult.model_fields["severity_log10p"].default is None


@pytest.mark.parametrize("s,expect", [
    (None, None),
    (0.3, "severity index 0.3; flag threshold 2.96"),
    (5.1, "severity index 5.1; flag threshold 2.96"),
    (14.44, "severity index 14.4; flag threshold 2.96"),
    (55.0, "severity index 55.0; flag threshold 2.96"),
])
def test_severity_index_phrase(s, expect):
    """I2c: the V1 p-values are not calibrated, so s is shown as an INDEX with the flag threshold, never as a 'one in N' claim."""
    got = severity_index_phrase(s)
    assert got == expect
    if got is not None:
        for banned in ("1 in", "one in", "10^", "healthy parts", "Gaussian", "rarer", "probab"):
            assert banned not in got
