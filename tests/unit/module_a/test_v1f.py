"""Session I2c: V1F = V1 with the MCD leg active only for lots of at least MCD_MIN_PARTS_ABSOLUTE (77) parts.

(i) at n >= 77 V1F == V1 exactly; (ii) below 77 the MCD leg produces no scores (K = 12); (iii) at 77 K = 16;
(v) default mode (switch unset) is untouched."""
import numpy as np
import pytest

import module_a.scoring as ms
from features.compute import compute
from generator.lot import generate_lot
from harness.variants import clean_family
from module_a.detect import detect
from module_a.scoring import ScoringConfig, compute_lot_raw
from module_a.settings import (ABSOLUTE_REJECT_THRESHOLD, ABSOLUTE_REVIEW_THRESHOLD, DISPLAY_S0, MCD_MIN_PARTS_ABSOLUTE,
                               module_a_scoring_config)


def _v1_cfg():
    """V1 exactly as I2a shipped it: no MCD floor argument."""
    return ScoringConfig(calibration="absolute", combination="max", review_threshold=ABSOLUTE_REVIEW_THRESHOLD,
                         reject_threshold=ABSOLUTE_REJECT_THRESHOLD, display_s0=DISPLAY_S0)


def _frames(n, tag="a", seed=7102):
    return compute(generate_lot(f"I2C-U-{tag}-{n}", "PN-I2C", seed, account_id="i2c", family=clean_family("baseline"),
                                n_parts=n).dataset)


def test_constant_is_77():
    assert MCD_MIN_PARTS_ABSOLUTE == 77


def test_absolute_config_carries_the_floor(monkeypatch):
    monkeypatch.setenv("MODULE_A_SCORING", "absolute")
    assert module_a_scoring_config().mcd_min_parts == 77
    assert _v1_cfg().mcd_min_parts is None  # the experiment harness keeps V1 as it was


@pytest.mark.parametrize("n", [77, 100])
def test_at_or_above_77_v1f_output_equals_v1_exactly(n, monkeypatch):
    monkeypatch.setenv("MODULE_A_SCORING", "absolute")
    frames = _frames(n)
    v1f = detect(frames, scoring=module_a_scoring_config())
    v1 = detect(frames, scoring=_v1_cfg())
    assert [r.model_dump() for r in v1f] == [r.model_dump() for r in v1]


@pytest.mark.parametrize("n", [30, 60, 76])
def test_below_77_the_mcd_leg_produces_no_scores_and_k_is_12(n, monkeypatch):
    monkeypatch.setenv("MODULE_A_SCORING", "absolute")
    frames = _frames(n)
    fits = []
    real = ms.MinCovDet
    monkeypatch.setattr(ms, "MinCovDet", lambda *a, **k: fits.append(1) or real(*a, **k))
    raw = compute_lot_raw(frames, mcd_min_parts=MCD_MIN_PARTS_ABSOLUTE)
    assert fits == [] and np.isnan(raw.mcd_d).all() and np.isnan(raw.mcd_sev1).all()
    assert len(frames[0].robust_z) == 4 and len({f.parameter for f in frames}) == 3  # 3 x 4 = 12 z scores per part
    results = detect(frames, scoring=module_a_scoring_config())
    assert all(r.mcd_distance is None and r.explainable_tags["mcd"] is False for r in results)
    # unchanged V1 would have run it at these sizes
    if n >= 30:
        assert not np.isnan(compute_lot_raw(frames).mcd_d).all()


def test_at_77_k_is_16(monkeypatch):
    frames = _frames(77)
    fits = []
    real = ms.MinCovDet
    monkeypatch.setattr(ms, "MinCovDet", lambda *a, **k: fits.append(1) or real(*a, **k))
    raw = compute_lot_raw(frames, mcd_min_parts=MCD_MIN_PARTS_ABSOLUTE)
    assert len(fits) == len(frames[0].robust_z) == 4  # 4 MCD scores + 12 z scores = 16
    assert not np.isnan(raw.mcd_sev1).any()


def test_default_signature_unchanged():
    frames = _frames(40)
    a, b = compute_lot_raw(frames), compute_lot_raw(frames, mcd_min_parts=None)
    assert np.array_equal(a.mcd_d, b.mcd_d, equal_nan=True) and not np.isnan(a.mcd_d).all()
