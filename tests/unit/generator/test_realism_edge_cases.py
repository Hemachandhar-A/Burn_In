"""E1 step 10 edge cases: input hygiene, schedule handling, malformed/mismatched lots, non-finite values,
reference-file parsing, immutability, seed-sweep bookkeeping and the CLI of generator.realism.

Written before the fixes they drive - each test names the failure it guards against.
"""
import dataclasses
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from generator import realism
from generator.families import FAMILIES, GeneratorFamily, get_family
from generator.lot import generate_lot
from generator.parameters import PARAMETERS
from generator.realism import (
    ALPHA,
    GeneratorStatistics,
    RealismComparison,
    SeedSweep,
    compare_to_references,
    extract_generator_statistics,
    format_report,
    literature_drift_exponents,
    ljmu_inset_power_law_fit,
    main,
    run_realism_comparisons,
    sweep_seeds,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _lot(lot_id="R1", seed=7, **kwargs):
    return generate_lot(lot_id, "PN-R", seed, account_id="acct-test", **kwargs)


def _replace_readings(lot, readings):
    return dataclasses.replace(lot, dataset=lot.dataset.model_copy(update={"readings": readings}))


def _replace_parts(lot, parts):
    trajectories = dataclasses.replace(lot.ground_truth.trajectories, parts=tuple(parts))
    return dataclasses.replace(lot, ground_truth=dataclasses.replace(lot.ground_truth, trajectories=trajectories))


def _first_healthy(lot):
    return next(p for p in lot.ground_truth.trajectories.parts if not p.is_defective)


# --- what counts as a valid input collection -----------------------------------------------------

def test_string_instead_of_lots_is_a_type_error_not_an_attribute_error():
    with pytest.raises(TypeError):
        extract_generator_statistics("R1")


def test_single_lot_not_wrapped_in_a_list_is_a_clear_type_error():
    with pytest.raises(TypeError, match="sequence"):
        extract_generator_statistics(_lot())


def test_non_lot_element_rejected_even_in_first_position():
    with pytest.raises(TypeError, match="GeneratedLot"):
        extract_generator_statistics([object(), _lot()])


def test_generator_expression_of_lots_accepted():
    stats = extract_generator_statistics(_lot(f"R{k}") for k in range(2))
    assert stats.n_lots == 2


def test_same_lot_passed_twice_is_rejected_as_pseudo_replication():
    lot = _lot()
    with pytest.raises(ValueError, match="duplicate"):
        extract_generator_statistics([lot, lot])


def test_same_lot_id_under_two_part_numbers_is_two_lots():
    a = generate_lot("R1", "PN-A", 7, account_id="acct-test")
    b = generate_lot("R1", "PN-B", 7, account_id="acct-test")
    assert extract_generator_statistics([a, b]).n_lots == 2


def test_lots_from_different_families_are_rejected():
    with pytest.raises(ValueError, match="famil"):
        extract_generator_statistics([_lot("R1"), _lot("R2", family="higher_defect_prevalence")])


def test_statistics_record_the_family_and_comparisons_use_it():
    stats = extract_generator_statistics([_lot(family="altered_correlation")])
    assert stats.family == "altered_correlation"
    assert {r.family for r in compare_to_references(stats)} == {"altered_correlation"}


# --- checkpoint schedules ------------------------------------------------------------------------

def test_schedule_extending_past_168h_still_measures_drift_at_168h():
    lot = _lot(checkpoint_hours=(0.0, 24.0, 96.0, 168.0, 336.0))
    stats = extract_generator_statistics([lot])
    part = _first_healthy(lot)
    values = {r.checkpoint_hour: r.value for r in lot.dataset.readings
              if r.component_id == part.component_id and r.parameter == "iddq"}
    assert stats.relative_drift_168h[0] == pytest.approx(values[168.0] / values[0.0] - 1)
    assert stats.campaign_hours == (0.0, 24.0, 96.0, 168.0)


def test_knee_reference_uses_the_168h_read_not_the_last_read():
    stats = extract_generator_statistics([_lot(checkpoint_hours=(0.0, 24.0, 96.0, 168.0, 336.0))])
    knee = next(r for r in compare_to_references(stats) if r.name == "time_to_knee_lot")
    assert knee.reference_median == pytest.approx(np.median((24.0 / 168.0) ** literature_drift_exponents()))


def test_schedule_without_an_exact_168h_read_is_rejected():
    with pytest.raises(ValueError, match="168"):
        extract_generator_statistics([_lot(checkpoint_hours=(0.0, 24.0, 200.0))])


def test_schedule_with_no_read_between_0h_and_168h_is_rejected():
    with pytest.raises(ValueError, match="between"):
        extract_generator_statistics([_lot(checkpoint_hours=(0.0, 168.0, 336.0))])


def test_schedule_without_a_0h_read_is_rejected():
    with pytest.raises(ValueError, match="0h"):
        extract_generator_statistics([_lot(checkpoint_hours=(24.0, 96.0, 168.0))])


def test_single_jittered_lot_is_accepted_and_uses_its_actual_hours():
    lot = _lot(checkpoint_jitter_hours=2.0)
    stats = extract_generator_statistics([lot])
    assert stats.campaign_hours == lot.ground_truth.trajectories.checkpoint_hours


def test_differently_jittered_lots_are_rejected_with_a_jitter_hint():
    lots = [_lot(f"R{k}", checkpoint_jitter_hours=2.0) for k in range(2)]
    with pytest.raises(ValueError, match="jitter"):
        extract_generator_statistics(lots)


# --- dataset / sidecar consistency ---------------------------------------------------------------

def test_dataset_and_sidecar_from_different_lots_are_rejected():
    a, b = _lot("R1"), _lot("R2")
    mixed = dataclasses.replace(a, dataset=b.dataset)
    with pytest.raises(ValueError, match="sidecar"):
        extract_generator_statistics([mixed])


def test_missing_reading_is_a_clear_value_error_not_a_key_error():
    lot = _lot()
    part = _first_healthy(lot)
    readings = [r for r in lot.dataset.readings
                if not (r.component_id == part.component_id and r.parameter == "iddq" and r.checkpoint_hour == 96.0)]
    with pytest.raises(ValueError, match="missing"):
        extract_generator_statistics([_replace_readings(lot, readings)])


def test_duplicate_reading_is_rejected_not_silently_overwritten():
    lot = _lot()
    readings = list(lot.dataset.readings)
    with pytest.raises(ValueError, match="duplicate"):
        extract_generator_statistics([_replace_readings(lot, readings + readings[:1])])


# --- degenerate values ---------------------------------------------------------------------------

def test_lot_with_no_healthy_parts_does_not_crash_and_is_counted():
    lot = _lot()
    parts = [dataclasses.replace(p, is_defective=True) for p in lot.ground_truth.trajectories.parts]
    stats = extract_generator_statistics([_replace_parts(lot, parts)])
    assert stats.lots_without_healthy_parts == 1
    assert len(stats.relative_drift_168h) == 0
    results = compare_to_references(stats)  # every comparison reported, none computable - no crash
    assert len(results) == len(realism.COMPARISON_POLICY)
    assert all(r.generator_n == 0 and not r.computable for r in results)


def test_one_empty_lot_does_not_hide_the_others():
    lot = _lot("R1")
    empty = _replace_parts(lot, [dataclasses.replace(p, is_defective=True) for p in lot.ground_truth.trajectories.parts])
    stats = extract_generator_statistics([empty, _lot("R2")])
    assert stats.lots_without_healthy_parts == 1
    assert len(stats.drift_exponent_lot_fit) + stats.lot_fits_excluded == len(PARAMETERS)


@pytest.mark.parametrize("bad_value", [0.0, -1.5])
def test_non_positive_measured_baseline_is_excluded_and_counted_not_inf(bad_value):
    lot = _lot()
    part = _first_healthy(lot)
    readings = [r.model_copy(update={"value": bad_value})
                if (r.component_id == part.component_id and r.parameter == "iddq" and r.checkpoint_hour == 0.0) else r
                for r in lot.dataset.readings]
    stats = extract_generator_statistics([_replace_readings(lot, readings)])
    assert stats.relative_drift_excluded == 1
    assert np.all(np.isfinite(stats.relative_drift_168h))


def test_zero_true_drift_is_excluded_from_noise_to_signal_not_inf():
    lot = _lot()
    part = _first_healthy(lot)
    flat = {**part.values, "iddq": (part.values["iddq"][0],) * len(part.values["iddq"])}
    parts = [dataclasses.replace(p, values=flat) if p.component_id == part.component_id else p
             for p in lot.ground_truth.trajectories.parts]
    stats = extract_generator_statistics([_replace_parts(lot, parts)])
    assert stats.noise_to_signal_excluded == 3  # the part's three post-0h reads
    assert np.all(np.isfinite(stats.noise_to_signal))


@pytest.mark.parametrize("family", list(FAMILIES))
def test_every_family_yields_only_finite_statistics(family):
    stats = extract_generator_statistics([_lot(f"R{k}", family=family) for k in range(3)])
    for field in ("relative_drift_168h", "drift_exponent_prior", "drift_exponent_lot_fit", "time_to_knee_lot",
                  "noise_to_signal", "drift_exponent_per_part_fit"):
        assert np.all(np.isfinite(getattr(stats, field))), (family, field)


def test_every_healthy_series_is_accounted_for():
    lots = [_lot(f"R{k}", family="different_noise_regime") for k in range(3)]
    stats = extract_generator_statistics(lots)
    n_series = sum(not p.is_defective for lot in lots for p in lot.ground_truth.trajectories.parts) * len(PARAMETERS)
    assert len(stats.relative_drift_168h) + stats.relative_drift_excluded == n_series
    assert len(stats.drift_exponent_per_part_fit) + stats.part_fits_excluded == n_series
    assert len(stats.noise_to_signal) + stats.noise_to_signal_excluded == 3 * n_series
    assert len(stats.drift_exponent_lot_fit) + stats.lot_fits_excluded == 3 * len(PARAMETERS)


# --- comparisons with nothing (or something non-finite) to compare --------------------------------

def test_empty_generator_sample_gives_a_not_computable_result_not_a_crash():
    r = realism._compare("drift_exponent_lot_fit", "baseline", np.array([]), literature_drift_exponents(), 5)
    assert not r.computable
    assert r.generator_n == 0 and r.generator_excluded == 5
    assert math.isnan(r.p_value) and math.isnan(r.ks_statistic)
    assert "not computable" in format_report([r])


def test_non_finite_sample_is_refused_rather_than_fed_to_ks():
    with pytest.raises(ValueError, match="finite"):
        realism._compare("drift_exponent_prior", "baseline", np.array([0.2, np.nan]), literature_drift_exponents())
    with pytest.raises(ValueError, match="finite"):
        realism._compare("drift_exponent_prior", "baseline", np.array([0.2, 0.3]), np.array([0.2, np.inf]))


def test_not_computable_results_compare_equal_and_hash_consistently():
    make = lambda: realism._compare("time_to_knee_lot", "baseline", np.array([]), literature_drift_exponents())
    a, b = make(), make()
    assert a == b
    assert hash(a) == hash(b)


# --- immutability and equality of the result objects ------------------------------------------------

def test_statistics_arrays_are_read_only():
    stats = extract_generator_statistics([_lot()])
    with pytest.raises(ValueError):
        stats.noise_to_signal[0] = 99.0


def test_statistics_compare_by_value():
    a = extract_generator_statistics([_lot()])
    b = extract_generator_statistics([_lot()])
    c = extract_generator_statistics([_lot(seed=8)])
    assert a == b
    assert a != c
    with pytest.raises(TypeError):
        hash(a)


def test_inset_fit_arrays_are_read_only_and_compare_by_value():
    fit = ljmu_inset_power_law_fit()
    with pytest.raises(ValueError):
        fit.relative_residuals[0] = 1.0
    assert fit == ljmu_inset_power_law_fit()


def test_mutating_a_returned_reference_array_does_not_change_the_next_call():
    n = literature_drift_exponents()
    n[:] = 0.0
    assert literature_drift_exponents().min() > 0.1
    latif = realism.latif_168h_relative_changes()
    latif[:] = 0.0
    assert realism.latif_168h_relative_changes().max() == pytest.approx(0.435)


# --- reference CSV parsing -----------------------------------------------------------------------

def _write_csv(tmp_path, body, newline="\n", encoding="utf-8"):
    path = tmp_path / "inset.csv"
    path.write_bytes(body.replace("\n", newline).encode(encoding))
    return path


def _real_rows():
    return realism._INSET_POINTS_CSV.read_text(encoding="utf-8").splitlines()


def test_csv_with_crlf_line_endings_parses_identically(tmp_path):
    path = _write_csv(tmp_path, "\n".join(_real_rows()) + "\n", newline="\r\n")
    assert ljmu_inset_power_law_fit(path) == ljmu_inset_power_law_fit()


def test_csv_with_bom_and_trailing_blank_lines_parses_identically(tmp_path):
    path = _write_csv(tmp_path, "﻿" + "\n".join(_real_rows()) + "\n\n\n")
    assert ljmu_inset_power_law_fit(path) == ljmu_inset_power_law_fit()


def test_csv_without_its_header_is_refused_not_silently_short_one_point(tmp_path):
    rows = [r for r in _real_rows() if not r.startswith("pdf_x_pt")]
    with pytest.raises(ValueError, match="header"):
        ljmu_inset_power_law_fit(_write_csv(tmp_path, "\n".join(rows) + "\n"))


@pytest.mark.parametrize("bad_row", ["450.1", "450.1,299.2,1", "abc,299.2", "nan,299.2", "450.1,inf"])
def test_csv_malformed_row_is_refused(tmp_path, bad_row):
    with pytest.raises(ValueError):
        ljmu_inset_power_law_fit(_write_csv(tmp_path, "\n".join(_real_rows() + [bad_row]) + "\n"))


def test_csv_point_outside_the_inset_frame_is_refused(tmp_path):
    with pytest.raises(ValueError, match="frame"):
        ljmu_inset_power_law_fit(_write_csv(tmp_path, "\n".join(_real_rows() + ["300.0,299.2"]) + "\n"))


def test_csv_with_too_few_points_is_refused(tmp_path):
    with pytest.raises(ValueError, match="points"):
        ljmu_inset_power_law_fit(_write_csv(tmp_path, "pdf_x_pt,pdf_y_pt\n450.59,299.19\n"))


# --- run / sweep argument handling ---------------------------------------------------------------

@pytest.mark.parametrize("seed, error", [(True, TypeError), (-1, ValueError), (1.5, TypeError), ("1", TypeError)])
def test_run_rejects_bad_seed(seed, error):
    with pytest.raises(error):
        run_realism_comparisons(n_lots=1, seed=seed)


def test_numpy_integer_arguments_match_python_ints():
    assert run_realism_comparisons(n_lots=np.int64(2), seed=np.int64(3)) == run_realism_comparisons(n_lots=2, seed=3)


def test_custom_family_object_is_reported_under_its_own_name():
    base = get_family("baseline")
    custom = GeneratorFamily(name="my_custom", description="custom test family", config=base.config,
                             trajectory_params=base.trajectory_params, measurement_params=base.measurement_params)
    assert {r.family for r in run_realism_comparisons(custom, n_lots=2)} == {"my_custom"}


def test_sweep_rejects_duplicate_seeds_that_would_double_count():
    with pytest.raises(ValueError, match="duplicate"):
        sweep_seeds(n_lots=1, seeds=(1, 1))


def test_sweep_rejects_a_bare_int_instead_of_a_seed_list():
    with pytest.raises(TypeError):
        sweep_seeds(n_lots=1, seeds=3)


def test_sweep_accepts_a_generator_of_seeds():
    assert all(s.n_seeds == 2 for s in sweep_seeds(n_lots=1, seeds=(k for k in (1, 2))))


def test_sweep_counts_not_computable_runs_separately_from_non_rejections(monkeypatch):
    real = run_realism_comparisons(n_lots=1)

    def fake(family="baseline", n_lots=1, seed=0):
        if seed == 0:
            return real
        return tuple(dataclasses.replace(r, generator_n=0, ks_statistic=math.nan, p_value=math.nan) for r in real)

    monkeypatch.setattr(realism, "run_realism_comparisons", fake)
    for s in sweep_seeds(n_lots=1, seeds=(0, 1)):
        assert isinstance(s, SeedSweep)
        assert s.not_computable == 1
        assert s.rejections == int(next(r for r in real if r.name == s.name).p_value < ALPHA)
        assert math.isfinite(s.median_p_value)


# --- report and CLI ------------------------------------------------------------------------------

def test_report_with_no_results_is_just_the_header():
    assert format_report([]).startswith("Realism validation")


def test_cli_prints_the_report(capsys):
    main(["--n-lots", "2", "--sweep-seeds", "0"])
    out = capsys.readouterr().out
    assert "degradation_magnitude_168h" in out and "p = " in out


@pytest.mark.parametrize("argv", [["--n-lots", "0"], ["--sweep-seeds", "-1"], ["--family", "no_such_family"],
                                  ["--seed", "-3"], ["--n-lots", "abc"]])
def test_cli_bad_arguments_exit_with_a_usage_error_not_a_traceback(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


# --- determinism across processes --------------------------------------------------------------------

def test_results_identical_across_processes_with_different_hash_seeds():
    code = ("from generator.realism import run_realism_comparisons as r;"
            "print(repr([(x.name, x.ks_statistic, x.p_value) for x in r(n_lots=3, seed=5)]))")
    outputs = set()
    for hash_seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(REPO_ROOT)}
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                              check=True)
        outputs.add(proc.stdout)
    assert len(outputs) == 1


def test_comparison_result_type_is_frozen_and_hashable():
    r = run_realism_comparisons(n_lots=1)[0]
    assert isinstance(r, RealismComparison)
    assert hash(r) == hash(dataclasses.replace(r))
    assert isinstance(extract_generator_statistics([_lot()]), GeneratorStatistics)
