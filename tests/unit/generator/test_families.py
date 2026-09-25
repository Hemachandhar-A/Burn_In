"""E1 step 9: five named, structurally distinct generator configurations for held-out validation.

7.3 checklist (Generator row): "all 5 held-out families present" - this file's named deliverable. Beyond
presence, each family is checked to (a) differ from baseline in its named structural knob, and (b) show
that difference in the generated data itself, not just in its config object.
"""
import numpy as np
import pytest
from scipy.stats import spearmanr

from contracts import LotDataset, ScreeningConfig
from generator.baselines import generate_lot_baselines
from generator.families import FAMILIES, HELD_OUT_FAMILY_NAMES, GeneratorFamily, get_family
from generator.lot import generate_lot
from generator.parameters import PARAMETERS

EXPECTED = ("baseline", "wider_drift_exponent", "higher_defect_prevalence",
            "different_noise_regime", "altered_correlation")


def _lot(family, seed=1, n_parts=77, **kwargs):
    return generate_lot(lot_id="L1", part_number="PN-1", seed=seed, account_id="acct-test",
                        family=family, n_parts=n_parts, **kwargs)


# --- presence (7.3) ------------------------------------------------------------------

def test_all_five_held_out_families_present():
    assert set(FAMILIES) == set(EXPECTED)
    assert HELD_OUT_FAMILY_NAMES == EXPECTED
    assert len(FAMILIES) == 5


@pytest.mark.parametrize("name", EXPECTED)
def test_each_family_is_named_described_and_generates_a_valid_lot(name):
    family = get_family(name)
    assert isinstance(family, GeneratorFamily)
    assert family.name == name
    assert family.description.strip()
    lot = _lot(name)
    assert LotDataset.model_validate(lot.dataset.model_dump()) == lot.dataset
    assert lot.ground_truth.family == name


@pytest.mark.parametrize("name", EXPECTED)
def test_each_family_is_deterministic(name):
    assert _lot(name, seed=3) == _lot(name, seed=3)


def test_family_object_accepted_directly():
    assert _lot(FAMILIES["baseline"]).dataset == _lot("baseline").dataset


def test_family_registry_is_read_only():
    with pytest.raises(TypeError):
        FAMILIES["baseline"] = FAMILIES["altered_correlation"]


def test_get_family_rejects_unknown():
    with pytest.raises(ValueError):
        get_family("nope")


def test_families_are_pairwise_distinct_configurations():
    keys = [(f.config, f.trajectory_params, f.measurement_params, f.die_correlation) for f in FAMILIES.values()]
    assert len(set(keys)) == 5


def test_every_non_baseline_family_changes_exactly_its_named_component():
    base = FAMILIES["baseline"]

    def changed(f):
        return {
            label for label, a, b in [
                ("config", f.config, base.config),
                ("trajectory_params", f.trajectory_params, base.trajectory_params),
                ("measurement_params", f.measurement_params, base.measurement_params),
                ("die_correlation", f.die_correlation, base.die_correlation),
            ] if a != b
        }

    assert changed(FAMILIES["wider_drift_exponent"]) == {"config"}
    assert changed(FAMILIES["higher_defect_prevalence"]) == {"config"}
    assert changed(FAMILIES["different_noise_regime"]) == {"measurement_params"}
    assert changed(FAMILIES["altered_correlation"]) == {"trajectory_params", "die_correlation"}


def test_baseline_family_uses_the_locked_defaults():
    base = FAMILIES["baseline"]
    assert base.config == ScreeningConfig()
    assert base.die_correlation == 0.0


# --- each family's structure shows up in the generated data --------------------------

def _parts(family, seeds, n_parts=77):
    return [p for s in seeds for p in _lot(family, seed=s, n_parts=n_parts).ground_truth.trajectories.parts]


def test_wider_drift_exponent_family_samples_outside_the_baseline_range():
    lo, hi = ScreeningConfig().power_law_exponent_range
    wide = [p.drift_exponent["iddq"] for p in _parts("wider_drift_exponent", range(3))]
    base = [p.drift_exponent["iddq"] for p in _parts("baseline", range(3))]
    assert all(lo <= n <= hi for n in base)
    assert min(wide) < lo and max(wide) > hi
    assert all(0 < n < 1 for n in wide)  # still sub-linear drift


def test_higher_defect_prevalence_family_has_more_defective_parts():
    def rate(family):
        parts = _parts(family, range(20))
        return np.mean([p.is_defective for p in parts])

    base_hi = ScreeningConfig().defect_prevalence_range[1]
    assert rate("baseline") <= base_hi
    assert rate("higher_defect_prevalence") > base_hi
    assert get_family("higher_defect_prevalence").config.defect_prevalence_range[0] >= base_hi


def _relative_residuals(family, seeds):
    out = []
    for s in seeds:
        lot = _lot(family, seed=s, n_parts=300)
        true = {p.component_id: p.values["iddq"] for p in lot.ground_truth.trajectories.parts}
        hours = lot.ground_truth.trajectories.checkpoint_hours
        for r in lot.dataset.readings:
            if r.parameter == "iddq":
                t = true[r.component_id][hours.index(r.checkpoint_hour)]
                out.append((r.value - t) / t)
    return np.asarray(out)


def test_different_noise_regime_is_noisier_and_heavier_tailed():
    from scipy.stats import kurtosis

    base = _relative_residuals("baseline", range(3))
    noisy = _relative_residuals("different_noise_regime", range(3))
    assert np.std(noisy) > 2 * np.std(base)
    assert kurtosis(noisy) > kurtosis(base) + 1.0


def test_different_noise_regime_is_coarser_quantized():
    fam = get_family("different_noise_regime").measurement_params
    base = get_family("baseline").measurement_params
    for name in PARAMETERS:
        assert fam.resolution[name] > base.resolution[name]
        assert fam.tester_offset_sigma[name] > base.tester_offset_sigma[name]
    assert fam.n_reference_parts < base.n_reference_parts


def _log_baseline_corr(family, seeds):
    fam = get_family(family)
    logs = []
    for s in seeds:
        lot = generate_lot_baselines("L1", "PN-1", n_parts=300, seed=s, config=fam.config,
                                     die_correlation=fam.die_correlation)
        centers = lot.lot_center
        logs += [[np.log(p.baseline[n] / centers[n]) for n in PARAMETERS] for p in lot.parts]
    return spearmanr(np.asarray(logs)).statistic


def test_altered_correlation_family_correlates_healthy_die_variation():
    base = _log_baseline_corr("baseline", range(3))
    altered = _log_baseline_corr("altered_correlation", range(3))
    off_diag = ~np.eye(len(PARAMETERS), dtype=bool)
    assert np.all(np.abs(base[off_diag]) < 0.1)  # baseline: near-independent (E1 step 6)
    assert np.all(altered[off_diag] > 0.4)


def test_altered_correlation_family_decorrelates_defect_severity():
    def severity_corr(family):
        parts = [p for p in _parts(family, range(6), n_parts=200) if p.is_defective]
        logs = np.log([[p.defect_severity[n] for n in PARAMETERS] for p in parts])
        return spearmanr(logs).statistic

    off_diag = ~np.eye(len(PARAMETERS), dtype=bool)
    # 6 lots x 200 parts at each family's own 1-8% prevalence: enough defective parts for a stable rank correlation.
    assert np.all(severity_corr("baseline")[off_diag] > 0.6)
    assert np.all(np.abs(severity_corr("altered_correlation")[off_diag]) < 0.35)


# --- die_correlation knob on baselines ---------------------------------------------------

def test_zero_die_correlation_reproduces_the_original_baselines_exactly():
    assert generate_lot_baselines("L1", "PN-1", 50, seed=4) == \
        generate_lot_baselines("L1", "PN-1", 50, seed=4, die_correlation=0.0)


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), "0.5", True])
def test_invalid_die_correlation_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        generate_lot_baselines("L1", "PN-1", 10, seed=1, die_correlation=bad)
