"""E13 step 2/3 (Part 2 of Block 4a): the confirmed-outcome vs. verdict-tier match definition and
FN/FP rate computation, as a pure function - no I/O, no storage, no FastAPI. Six-cell match table:
    Confirmed Defective + PASS            = miss
    Confirmed Defective + WATCH/REJECT    = caught
    Confirmed Good + REJECT               = false_alarm
    Confirmed Good + PASS/WATCH           = fine
    Unknown + anything                    = excluded (never counted, never in the minimum count)
FN rate = misses / confirmed-defective; FP rate = false_alarms / confirmed-good. Two independent
numbers, never blended. Division by zero returns None, not 0 (AGENTS.md rule 7 - no silent
imputation of a value that can't actually be computed)."""
import pytest

from capa.logic import classify_confirmed_outcome_match, compute_match_rates


@pytest.mark.parametrize(
    "confirmed_outcome, verdict, expected",
    [
        ("Confirmed Defective", "PASS", "miss"),
        ("Confirmed Defective", "WATCH", "caught"),
        ("Confirmed Defective", "REJECT", "caught"),
        ("Confirmed Good", "REJECT", "false_alarm"),
        ("Confirmed Good", "PASS", "fine"),
        ("Confirmed Good", "WATCH", "fine"),
        ("Unknown", "PASS", "excluded"),
        ("Unknown", "WATCH", "excluded"),
        ("Unknown", "REJECT", "excluded"),
    ],
)
def test_classify_every_cell_of_the_match_table(confirmed_outcome, verdict, expected):
    assert classify_confirmed_outcome_match(confirmed_outcome, verdict) == expected


def test_classify_rejects_an_unrecognized_confirmed_outcome():
    with pytest.raises(ValueError):
        classify_confirmed_outcome_match("Not A Real Outcome", "PASS")


def test_classify_rejects_an_unrecognized_verdict():
    with pytest.raises(ValueError):
        classify_confirmed_outcome_match("Confirmed Good", "NOT_A_VERDICT")


def test_compute_match_rates_all_six_cells_present():
    pairs = [
        ("Confirmed Defective", "PASS"),      # miss
        ("Confirmed Defective", "WATCH"),     # caught
        ("Confirmed Defective", "REJECT"),    # caught
        ("Confirmed Good", "REJECT"),         # false_alarm
        ("Confirmed Good", "PASS"),           # fine
        ("Confirmed Good", "WATCH"),          # fine
        ("Unknown", "REJECT"),                # excluded
    ]
    rates = compute_match_rates(pairs)
    assert rates.confirmed_defective_count == 3
    assert rates.confirmed_good_count == 3
    assert rates.miss_count == 1
    assert rates.caught_count == 2
    assert rates.false_alarm_count == 1
    assert rates.fine_count == 2
    assert rates.fn_rate == pytest.approx(1 / 3)
    assert rates.fp_rate == pytest.approx(1 / 3)


def test_compute_match_rates_unknown_excluded_from_every_rate_and_minimum_count():
    pairs = [("Unknown", "PASS")] * 20  # would look like plenty of data if miscounted
    rates = compute_match_rates(pairs)
    assert rates.confirmed_defective_count == 0
    assert rates.confirmed_good_count == 0
    assert rates.fn_rate is None
    assert rates.fp_rate is None


def test_compute_match_rates_zero_denominator_returns_none_not_zero():
    # only Confirmed Good outcomes -> no confirmed-defective denominator for FN rate
    pairs = [("Confirmed Good", "PASS"), ("Confirmed Good", "REJECT")]
    rates = compute_match_rates(pairs)
    assert rates.fn_rate is None
    assert rates.fp_rate == pytest.approx(0.5)


def test_compute_match_rates_fn_and_fp_move_independently_fp_bad_fn_good():
    pairs = [
        ("Confirmed Defective", "WATCH"),   # caught
        ("Confirmed Defective", "REJECT"),  # caught
        ("Confirmed Good", "REJECT"),       # false_alarm
        ("Confirmed Good", "REJECT"),       # false_alarm
    ]
    rates = compute_match_rates(pairs)
    assert rates.fn_rate == pytest.approx(0.0)
    assert rates.fp_rate == pytest.approx(1.0)


def test_compute_match_rates_fn_and_fp_move_independently_fn_bad_fp_good():
    pairs = [
        ("Confirmed Defective", "PASS"),  # miss
        ("Confirmed Defective", "PASS"),  # miss
        ("Confirmed Good", "PASS"),       # fine
        ("Confirmed Good", "WATCH"),      # fine
    ]
    rates = compute_match_rates(pairs)
    assert rates.fn_rate == pytest.approx(1.0)
    assert rates.fp_rate == pytest.approx(0.0)


def test_compute_match_rates_empty_input():
    rates = compute_match_rates([])
    assert rates.fn_rate is None
    assert rates.fp_rate is None
    assert rates.confirmed_defective_count == 0
    assert rates.confirmed_good_count == 0
