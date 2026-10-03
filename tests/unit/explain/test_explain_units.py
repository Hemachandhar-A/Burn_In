"""F24 Part 3, T13: the display-prefix helper round-trips - displayed value times its factor is the canonical value."""
import pytest

from explain.units import format_quantity, scale_for_display

CANONICAL = {"iddq": "uA", "leakage": "nA", "prop_delay": "ns"}
TEN_VALUES = [0.0042, 0.37, 1.0, 4.5, 12.0, 999.0, 1000.0, 10000.0, 52380.0, 3.2e6]


@pytest.mark.parametrize("parameter", sorted(CANONICAL))
def test_t13_round_trip_ten_values_per_parameter(parameter):
    unit = CANONICAL[parameter]
    for v in TEN_VALUES:
        shown, label, factor = scale_for_display(v, unit)
        assert shown * factor == pytest.approx(v, rel=1e-12)
        assert 1.0 - 1e-9 <= abs(shown) < 1000.0 + 1e-6 or label in ("pA", "ps", "A", "s")  # at the family's edge it cannot go further


def test_ten_thousand_nanoamps_is_ten_microamps():
    assert scale_for_display(10000, "nA") == (pytest.approx(10.0), "uA", pytest.approx(1000.0))
    assert format_quantity(10000, "nA") == "10 uA"
    assert format_quantity(45000, "nA") == "45 uA"
    assert format_quantity(7.07, "ns") == "7.07 ns"
    assert format_quantity(0.0042, "uA") == "4.2 nA"
    assert format_quantity(2500, "ns") == "2.5 us"


def test_no_prefix_change_for_zero_missing_or_unknown_units():
    assert scale_for_display(0.0, "nA") == (0.0, "nA", 1.0)
    assert scale_for_display(5.0, None) == (5.0, "", 1.0)
    assert scale_for_display(5.0, "furlongs") == (5.0, "furlongs", 1.0)
    assert format_quantity(5.0, None) == "5"
    assert scale_for_display(float("inf"), "nA")[1] == "nA"


def test_negative_values_keep_their_sign():
    shown, label, factor = scale_for_display(-2500.0, "nA")
    assert (label, shown) == ("uA", pytest.approx(-2.5)) and shown * factor == pytest.approx(-2500.0)
