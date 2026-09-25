"""Handover review of P1.1-P1.4: issues found on a final whole-generator pass, each pinned by a test written
before its fix.
"""
import dataclasses

import pytest

from generator.lot import generate_lot
from generator.parameters import PARAMETERS
from generator.realism import run_realism_comparisons


def _lot(**kwargs):
    return generate_lot("L1", "PN-1", 7, account_id="acct-test", **kwargs)


# --- lot status: COMPLETE means the 168h read exists, as generate_lot's docstring states ------------------

def test_schedule_that_skips_the_168h_read_is_not_complete():
    # A COMPLETE lot feeds Full Disposition, which needs a measured 168h value; this lot has none.
    lot = _lot(checkpoint_hours=(0.0, 24.0, 200.0))
    assert 168.0 not in {r.checkpoint_hour for r in lot.dataset.readings}
    assert lot.dataset.status == "IN_PROGRESS"


def test_schedule_that_reads_168h_and_continues_is_complete():
    assert _lot(checkpoint_hours=(0.0, 24.0, 96.0, 168.0, 336.0)).dataset.status == "COMPLETE"


def test_jittered_168h_read_still_counts_as_the_168h_read():
    lot = _lot(checkpoint_jitter_hours=2.0)
    assert 168.0 not in {r.checkpoint_hour for r in lot.dataset.readings}  # actually read at 166-170h
    assert lot.dataset.status == "COMPLETE"


def test_status_agrees_with_what_the_realism_check_accepts():
    # One definition of "full campaign" across the generator: realism needs the 168h read too.
    assert _lot(checkpoint_hours=(0.0, 24.0, 200.0)).dataset.status == "IN_PROGRESS"
    assert all(r.computable for r in run_realism_comparisons(n_lots=1))


# --- the parameter registry is read-only, like DEFECT_ARCHETYPES and FAMILIES ------------------------------

def test_parameter_registry_cannot_be_mutated():
    with pytest.raises(TypeError):
        PARAMETERS["extra"] = PARAMETERS["iddq"]
    with pytest.raises((TypeError, AttributeError)):
        PARAMETERS.pop("iddq")
    assert set(PARAMETERS) == {"iddq", "leakage", "prop_delay"}


def test_parameter_specs_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        PARAMETERS["iddq"].defect_scale = 99.0


def test_parameter_registry_keeps_its_order():
    # Draw order depends on it (determinism, rule 9).
    assert tuple(PARAMETERS) == ("iddq", "leakage", "prop_delay")
