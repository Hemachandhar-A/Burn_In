"""E1 step 10: quantitative realism validation - Kolmogorov-Smirnov (scipy.stats.ks_2samp) comparisons of
statistics extracted from generator output against statistics extracted from real published measurements
(context.md 3.4 (4)).

Every comparison's actual KS statistic and p-value is printed to the terminal (not just asserted), and the
assertion policy is fixed per comparison in generator.realism.COMPARISON_POLICY and judged over a 20-seed sweep,
not one seed (a single-seed pass or fail would be seed-picked):
    "gate"      - fails if the KS test rejects at alpha = 0.05 on any seed
    "marginal"  - fails if the median p over the sweep drops below alpha, or if it stops being rejected on any
                  seed (then it should be promoted to "gate" deliberately)
    "divergent" - a documented, known mismatch with the reference; fails if it stops diverging on any seed, so
                  the disclosure can't silently go stale (a tripwire, not a pass)
This checks plausibility of shape/rate statistics, not "validated on real data" (context.md 3.2, 8.1).
"""
import dataclasses
import math

import numpy as np
import pytest

from generator import realism
from generator.families import get_family
from generator.lot import generate_lot
from generator.realism import (
    ALPHA,
    COMPARISON_POLICY,
    DEFAULT_SWEEP_SEEDS,
    RealismComparison,
    extract_generator_statistics,
    format_report,
    latif_168h_relative_changes,
    literature_drift_exponents,
    ljmu_inset_power_law_fit,
    run_realism_comparisons,
    sweep_seeds,
)

EXPECTED_COMPARISONS = (
    "degradation_magnitude_168h",
    "drift_exponent_prior",
    "drift_exponent_lot_fit",
    "time_to_knee_lot",
    "noise_to_signal_per_part",
    "drift_exponent_per_part_fit",
)


@pytest.fixture(scope="module")
def results():
    return run_realism_comparisons()


@pytest.fixture(scope="module")
def sweep():
    return {s.name: s for s in sweep_seeds()}


def _names(policy):
    return [n for n in EXPECTED_COMPARISONS if COMPARISON_POLICY[n][0] == policy]


# --- the reference data really is what the cited sources say ------------------------------------

def test_latif_reference_is_table5_percent_changes():
    # Latif et al. arXiv:1510.01370, Table 5: DNL, INL, gain error, offset error, output current.
    assert latif_168h_relative_changes().tolist() == pytest.approx([0.0648, 0.0468, 0.4350, 0.0490, 0.02])


def test_literature_exponents_digitized_from_ljmu_fig1a_plus_latif():
    n = literature_drift_exponents()
    assert len(n) == 21  # 20 "data from references" markers in LJMU Fig. 1a + Latif's n = 0.181
    assert 0.181 in n.tolist()
    # The figure's y-axis spans ~0.12-0.32; every digitized marker must land inside it.
    assert np.all((n > 0.12) & (n < 0.32))
    # Spot checks against values legible in the rendered figure (to the figure's ~0.005 reading precision).
    for legible in (0.30, 0.28, 0.25, 0.16, 0.13):
        assert np.min(np.abs(n - legible)) < 0.005, legible


def test_ljmu_fig1a_axis_calibration_is_linear():
    # The four labeled major ticks must map back onto their labels - a check the digitization is sound.
    for label, y_pt in realism._FIG1A_Y_TICKS_PT.items():
        assert realism._fig1a_exponent(y_pt) == pytest.approx(label, abs=1e-3)


def test_ljmu_inset_refit_recovers_the_papers_printed_exponent():
    # The inset prints its own fitted exponent, n = 0.2035; refitting our digitized points must recover it,
    # which validates both the log-axis calibration and the point extraction.
    fit = ljmu_inset_power_law_fit()
    assert fit.n_points == 484
    assert fit.exponent == pytest.approx(0.2035, abs=0.01)
    assert np.all(np.isfinite(fit.relative_residuals))
    assert abs(np.median(fit.relative_residuals)) < 0.01  # a fit, so residuals center on zero


# --- the comparisons themselves --------------------------------------------------------------------

def test_every_named_comparison_runs_and_has_a_policy(results):
    assert tuple(r.name for r in results) == EXPECTED_COMPARISONS
    assert set(COMPARISON_POLICY) == set(EXPECTED_COMPARISONS)
    for r in results:
        assert isinstance(r, RealismComparison)
        assert 0.0 <= r.ks_statistic <= 1.0
        assert 0.0 <= r.p_value <= 1.0
        assert r.generator_n > 0 and r.reference_n > 0
        assert r.reference_source.strip() and r.caveat.strip()


def test_report_prints_the_actual_statistic_and_p_value(results, sweep, capsys):
    report = format_report(results, tuple(sweep.values()))
    for r in results:
        assert r.name in report
        assert f"{r.ks_statistic:.4f}" in report
        assert f"{r.p_value:.4g}" in report
    for s in sweep.values():
        assert f"rejected {s.rejections}/{s.n_seeds}" in report
    with capsys.disabled():  # always visible in the terminal, not only under `pytest -s`
        print("\n" + report)


def test_every_comparison_is_classified():
    assert {policy for policy, _ in COMPARISON_POLICY.values()} <= {"gate", "marginal", "divergent"}
    for name, (policy, reason) in COMPARISON_POLICY.items():
        assert policy == "gate" or reason.strip(), f"{name}: a non-gate classification needs its reason disclosed"


def test_sweep_covers_every_comparison_and_seed(sweep):
    assert tuple(sweep) == EXPECTED_COMPARISONS
    assert all(s.n_seeds == len(DEFAULT_SWEEP_SEEDS) for s in sweep.values())


def test_every_comparison_is_computable_on_every_seed(results, sweep):
    # Otherwise "0 rejections" could mean "nothing was compared" - a gate must never pass by being empty.
    assert all(r.computable for r in results)
    assert all(s.not_computable == 0 for s in sweep.values()), {n: s.not_computable for n, s in sweep.items()}


@pytest.mark.parametrize("name", _names("gate"))
def test_gated_comparison_is_not_rejected_on_the_default_seed(results, name):
    r = next(r for r in results if r.name == name)
    assert r.p_value >= ALPHA, (
        f"{name}: KS rejects the generator against the real reference (D={r.ks_statistic:.4f}, "
        f"p={r.p_value:.4g} < {ALPHA})"
    )


@pytest.mark.parametrize("name", _names("gate"))
def test_gated_comparison_is_not_rejected_on_any_seed(sweep, name):
    s = sweep[name]
    assert s.rejections == 0, f"{name}: rejected on {s.rejections}/{s.n_seeds} seeds (min p = {s.min_p_value:.4g})"


@pytest.mark.parametrize("name", _names("marginal"))
def test_marginal_comparison_is_not_rejected_on_a_typical_seed(sweep, name):
    s = sweep[name]
    assert s.median_p_value >= ALPHA, f"{name}: median p over the sweep = {s.median_p_value:.4g} < {ALPHA}"


@pytest.mark.parametrize("name", _names("marginal"))
def test_marginal_comparison_is_still_marginal(sweep, name):
    # Tripwire: never rejected any more -> promote to "gate"; this keeps the classification honest both ways.
    s = sweep[name]
    assert s.rejections > 0, f"{name}: no longer rejected on any seed - promote it to 'gate' in COMPARISON_POLICY"


@pytest.mark.parametrize("name", _names("divergent"))
def test_documented_divergence_still_diverges_on_every_seed(sweep, name):
    # Tripwire: if this stops diverging, the generator (or reference) changed and the disclosure in
    # COMPARISON_POLICY is stale - reclassify it deliberately rather than let it drift.
    s = sweep[name]
    assert s.rejections == s.n_seeds, (
        f"{name}: not rejected on {s.n_seeds - s.rejections}/{s.n_seeds} seeds; update COMPARISON_POLICY"
    )


# --- determinism and input handling --------------------------------------------------------------

def test_realism_comparisons_are_deterministic(results):
    assert run_realism_comparisons() == results


def test_rejects_empty_seed_sweep():
    with pytest.raises(ValueError):
        sweep_seeds(seeds=())


def test_generator_statistics_use_only_healthy_parts():
    lots = [generate_lot(f"R{k}", "PN-R", 7, account_id="acct-test", family="higher_defect_prevalence")
            for k in range(3)]
    stats = extract_generator_statistics(lots)
    n_healthy = sum(not p.is_defective for lot in lots for p in lot.ground_truth.trajectories.parts)
    assert len(stats.drift_exponent_prior) == 3 * n_healthy
    assert len(stats.relative_drift_168h) == 3 * n_healthy


def test_generator_statistics_read_the_measured_dataset_not_the_noise_free_truth():
    lot = generate_lot("R1", "PN-R", 7, account_id="acct-test")
    stats = extract_generator_statistics([lot])
    # Measured drift carries noise relative to the true drift, so the residuals can't all be zero.
    assert np.std(stats.noise_to_signal) > 0


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "40"])
def test_rejects_bad_lot_count(bad):
    with pytest.raises((TypeError, ValueError)):
        run_realism_comparisons(n_lots=bad)


def test_rejects_empty_lot_list():
    with pytest.raises(ValueError):
        extract_generator_statistics([])


def test_rejects_a_lot_without_the_full_168h_campaign():
    lot = generate_lot("R1", "PN-R", 7, account_id="acct-test", checkpoint_hours=(0.0, 24.0))
    with pytest.raises(ValueError, match="168"):
        extract_generator_statistics([lot])


def test_family_is_recorded_and_other_families_run():
    for r in run_realism_comparisons(family=get_family("different_noise_regime"), n_lots=5):
        assert r.family == "different_noise_regime"
        assert math.isfinite(r.p_value)


def test_comparison_result_is_frozen(results):
    with pytest.raises(dataclasses.FrozenInstanceError):
        results[0].p_value = 1.0
