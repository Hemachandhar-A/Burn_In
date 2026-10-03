"""S6X: the optional `scoring` argument of module_a.detect.detect (module_a/scoring.py).

Two jobs. (1) Prove the default is untouched: scoring=None or a rank/max config reproduces today's output exactly,
and the new raw-score code agrees with detect()'s own MCD / ECOD numbers. (2) The pre-registered mechanism
properties P1-P5 (docs/SCORING_EXPERIMENT_PLAN.md section 3), parametrised over every variant.

The unit-level P1 and P2 use a-priori severity cut-offs (3.0 and 4.0, i.e. p <= 1e-3 and p <= 1e-4), not tuned
thresholds; the formal P1 / P2 at the tuned thresholds are measured by scripts/scoring_experiment.py.
"""
import math

import numpy as np
import pytest

from contracts import ScreeningConfig
from features.compute import compute
from generator.families import GeneratorFamily
from generator.lot import generate_lot
from generator.measurement import MeasurementParams
from generator.trajectories import TrajectoryParams
from harness import golden
from module_a.detect import detect
from module_a.scoring import (ScoringConfig, ScoringReference, compute_lot_raw, conformal_severity,
                              frame_severities)

REVIEW_CUT, REJECT_CUT = 3.0, 4.0
VARIANTS = ("V1-C0", "V1-C1", "V1-C2", "V2-C0", "V2-C1", "V2-C2")
CLEAN = GeneratorFamily(name="s6x_clean", description="Baseline with no defective parts.",
                        config=ScreeningConfig(defect_prevalence_range=(0.0, 0.0)),
                        trajectory_params=TrajectoryParams(), measurement_params=MeasurementParams())


@pytest.fixture(scope="module")
def clean_lots():
    """Six clean lots; the first five are the reference / anchor, the sixth is the lot scored."""
    lots = [generate_lot(f"S6X-CLEAN-{i}", "PN-S6X", 6001, account_id="s6x", family=CLEAN) for i in range(6)]
    frames = [compute(lot.dataset) for lot in lots]
    return lots, frames, [compute_lot_raw(f) for f in frames]


@pytest.fixture(scope="module")
def configs(clean_lots):
    _, _, raws = clean_lots
    ref = ScoringReference.from_raw(raws[:5])
    assert ref.n_parts == 5 * 77 >= 300
    common = dict(review_threshold=REVIEW_CUT, reject_threshold=REJECT_CUT)
    out = {}
    for cal in ("V1", "V2"):
        for comb_name, comb in (("C0", "max"), ("C1", "mean"), ("C2", "hybrid")):
            out[f"{cal}-{comb_name}"] = ScoringConfig(
                calibration="absolute" if cal == "V1" else "reference", combination=comb,
                reference=ref if cal == "V2" else None, ecod_anchor=ref, **common)
    return out


def _part_scores(results):
    scores = {}
    for r in results:
        scores[r.component_id] = max(scores.get(r.component_id, -np.inf), r.combined_severity)
    return scores


def _dump(results):
    return [r.model_dump() for r in results]


# --- the default is untouched ----------------------------------------------------------------------------------

def test_scoring_none_and_rank_max_reproduce_todays_output_exactly():
    frames = golden.golden_feature_frames()
    base = _dump(detect(frames))
    assert _dump(detect(frames, scoring=None)) == base
    assert _dump(detect(frames, scoring=ScoringConfig())) == base
    assert _dump(detect(frames, scoring=ScoringConfig(calibration="rank", combination="max"))) == base


def test_raw_scores_agree_exactly_with_detects_own_numbers(clean_lots):
    _, frames, raws = clean_lots
    results = detect(frames[0])
    raw = raws[0]
    assert [r.component_id for r in results] == raw.component_ids
    np.testing.assert_array_equal([r.ecod_score for r in results], raw.ecod)
    np.testing.assert_array_equal([r.robust_z for r in results], raw.z)
    mcd = np.array([np.nan if r.mcd_distance is None else r.mcd_distance for r in results])
    np.testing.assert_array_equal(mcd, raw.mcd_d)
    assert [r.direction == "below_median" for r in results] == raw.below_median.tolist()


def test_invalid_configs_are_refused():
    with pytest.raises(ValueError):
        ScoringConfig(calibration="rank", combination="mean")
    with pytest.raises(ValueError):
        ScoringConfig(calibration="nonsense")
    with pytest.raises(ValueError):
        ScoringConfig(n_min=0)
    with pytest.raises(ValueError, match="review_threshold"):
        detect(golden.golden_feature_frames(), scoring=ScoringConfig(calibration="absolute"))
    with pytest.raises(ValueError):
        frame_severities(compute_lot_raw(golden.golden_feature_frames()), ScoringConfig())


def test_conformal_severity_formula():
    ref = np.sort(np.array([1.0, 2.0, 3.0, 4.0]))
    sev = conformal_severity(np.array([0.0, 2.5, 4.0, 9.0]), ref)
    p = np.array([5 / 5, 3 / 5, 2 / 5, 1 / 5])  # (1 + #ref >= v) / (1 + N)
    np.testing.assert_allclose(sev, -np.log10(p))


def test_scored_detect_returns_contracted_results_in_input_order(clean_lots, configs):
    _, frames, _ = clean_lots
    mixed = frames[5][:6] + frames[4][:6]
    for cfg in (configs["V1-C0"], configs["V2-C1"]):
        out = detect(mixed, scoring=cfg)
        assert [(r.lot_id, r.component_id, r.parameter) for r in out] == [(f.lot_id, f.component_id, f.parameter)
                                                                          for f in mixed]
        assert all(r.isolation_forest_score is None and r.explainable_tags["isolation_forest"] is False
                   for r in out)


def test_isolation_forest_is_ignored_by_non_rank_variants(clean_lots, configs):
    _, frames, _ = clean_lots
    a = _dump(detect(frames[5], scoring=configs["V1-C0"]))
    b = _dump(detect(frames[5], prior_frames=frames[0] + frames[1], scoring=configs["V1-C0"]))
    assert a == b


def test_cold_start_falls_back_to_absolute(clean_lots):
    _, _, raws = clean_lots
    small = ScoringReference.from_raw(raws[:2])  # 154 parts < n_min = 300
    kwargs = dict(review_threshold=REVIEW_CUT, reject_threshold=REJECT_CUT, ecod_anchor=ScoringReference.from_raw(raws[:5]))
    v1 = frame_severities(raws[5], ScoringConfig(calibration="absolute", **kwargs))
    v2 = frame_severities(raws[5], ScoringConfig(calibration="reference", reference=small, **kwargs))
    np.testing.assert_array_equal(v1.combined, v2.combined)


def test_absolute_without_an_anchor_leaves_ecod_out(clean_lots):
    _, _, raws = clean_lots
    sev = frame_severities(raws[5], ScoringConfig(calibration="absolute", review_threshold=1, reject_threshold=2))
    assert np.isnan(sev.sev_ecod).all() and not np.isnan(sev.sev_z).any()


def test_hybrid_override_fires_only_on_an_extreme_single_detector(clean_lots):
    _, _, raws = clean_lots
    anchor = ScoringReference.from_raw(raws[:5])
    cfg = ScoringConfig(calibration="absolute", combination="hybrid", ecod_anchor=anchor)
    sev = frame_severities(raws[5], cfg)
    stack = np.vstack([sev.sev_z, sev.sev_mcd, sev.sev_ecod])
    assert (sev.override == (np.nan_to_num(stack, nan=-1) >= 4.0).any(axis=0)).all()
    np.testing.assert_allclose(sev.combined, np.nanmean(stack, axis=0))
    assert not frame_severities(raws[5], ScoringConfig(calibration="absolute", combination="mean",
                                                       ecod_anchor=anchor)).override.any()


# --- P1-P5 over every variant ---------------------------------------------------------------------------------

def test_p1_v0_rank_percentile_flags_a_large_share_of_a_clean_lot(clean_lots):
    """Expected result, recorded: today's rank-percentile scoring flags a big slice of a lot with no defects."""
    from harness import bakeoff, scoring as hs
    _, frames, _ = clean_lots
    thresholds = bakeoff.load_harness_thresholds()
    res = detect(frames[5])
    parts = hs.part_detector_scores(res)
    score = parts[list(hs.DETECTORS)].max(axis=1)
    share = float((score >= thresholds.module_a_review_threshold).mean())
    print(f"P1 V0 clean-lot share at shipped REVIEW: {share:.3f}")
    assert share > 0.05


@pytest.mark.parametrize("name", VARIANTS)
def test_p1_clean_lot_flag_rate_at_a_priori_cutoff(name, clean_lots, configs):
    _, frames, _ = clean_lots
    scores = _part_scores(detect(frames[5], scoring=configs[name]))
    share = float(np.mean([s >= REVIEW_CUT for s in scores.values()]))
    print(f"P1 {name} clean-lot share >= {REVIEW_CUT}: {share:.3f}")
    assert share <= 0.05


@pytest.mark.parametrize("name", VARIANTS)
def test_p2_golden_outlier_is_top_and_extreme(name, clean_lots, configs):
    cfg = configs[name]
    results = detect(golden.golden_feature_frames(), scoring=cfg)
    scores = _part_scores(results)
    gid = golden.GOLDEN_COMPONENT_ID
    assert scores[gid] == max(scores.values())
    assert scores[gid] > sorted(scores.values())[-2]
    if cfg.calibration == "reference":
        # Severity saturates at log10(1 + N_ref). Only the max combination is asserted to reach the cap: the golden
        # fixture's three parameters share one offset pattern, so its MCD covariance is singular (sklearn warns
        # "not full rank") and its MCD distance is not a clean signal (see the deviations in the plan).
        if cfg.combination == "max":
            assert scores[gid] >= 0.99 * math.log10(1 + cfg.reference.n_parts)
    else:
        assert scores[gid] >= REJECT_CUT
        assert [r for r in results if r.component_id == gid and r.severity_tier != "PASS"]
    # (V2 saturates at log10(1 + N_ref) = 2.59 here, below the a-priori 3.0 / 4.0 cut-offs: its tier at the TUNED
    # thresholds is checked by scripts/scoring_experiment.py, not by a fixed cut-off.)


def _golden_with(leakage=None, scale_iddq=1.0, order=None):
    lot = golden.golden_lot()
    for r in lot.readings:
        if leakage is not None and r.component_id == golden.GOLDEN_COMPONENT_ID and r.parameter == "leakage":
            r.value = leakage
        if r.parameter == "iddq":
            r.value *= scale_iddq
    frames = compute(lot)
    if order is not None:
        frames = [frames[i] for i in order]
    return frames


@pytest.mark.parametrize("name", VARIANTS)
def test_p3_monotone_in_outlier_deviation(name, clean_lots, configs):
    """A generated (not hand-built) lot: scale one part's leakage up through a ladder; its score never drops.
    (The golden fixture is unsuitable here: its parameters are perfectly correlated, so MCD's covariance is
    singular and the raw MCD distance itself is non-monotone - recorded as a deviation in the plan.)"""
    lots, _, _ = clean_lots
    cfg = configs[name]
    cid = lots[5].dataset.readings[0].component_id
    seen = []
    for scale in (1.0, 1.2, 1.5, 2.0, 3.0, 5.0, 10.0, 30.0):
        dataset = lots[5].dataset.model_copy(deep=True)
        for r in dataset.readings:
            if r.component_id == cid and r.parameter == "leakage":
                r.value *= scale
        seen.append(_part_scores(detect(compute(dataset), scoring=cfg))[cid])
    assert all(b >= a - 1e-9 for a, b in zip(seen, seen[1:])), seen


@pytest.mark.parametrize("name", VARIANTS)
def test_p4_scale_invariance(name, configs):
    cfg = configs[name]
    a = _part_scores(detect(_golden_with(), scoring=cfg))
    b = _part_scores(detect(_golden_with(scale_iddq=1000.0), scoring=cfg))
    assert a.keys() == b.keys()
    np.testing.assert_allclose([b[k] for k in a], [a[k] for k in a], rtol=1e-6, atol=1e-6)


@pytest.mark.parametrize("name", VARIANTS)
def test_p5_permutation_invariance(name, configs):
    cfg = configs[name]
    base = detect(_golden_with(), scoring=cfg)
    n = len(base)
    order = np.random.default_rng(0).permutation(n)
    shuffled = detect(_golden_with(order=order), scoring=cfg)
    by_key = {(r.component_id, r.parameter): r.combined_severity for r in base}
    diffs = [abs(by_key[(r.component_id, r.parameter)] - r.combined_severity) for r in shuffled]
    assert max(diffs) <= 1e-6, max(diffs)


def test_p5_also_holds_for_todays_rank_scoring():
    base = detect(_golden_with())
    order = np.random.default_rng(0).permutation(len(base))
    shuffled = detect(_golden_with(order=order))
    by_key = {(r.component_id, r.parameter): r.combined_severity for r in base}
    assert max(abs(by_key[(r.component_id, r.parameter)] - r.combined_severity) for r in shuffled) <= 1e-6
