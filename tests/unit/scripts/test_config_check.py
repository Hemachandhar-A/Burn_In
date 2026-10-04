"""scripts/config_check.py: the app pipeline and the harness live path agree on a small lot, in both scoring modes."""
import pytest

from scripts.config_check import TOLERANCE, config_check


@pytest.mark.parametrize("mode", ["rank", "absolute"])
def test_pipeline_and_harness_live_path_agree_on_two_small_lots(monkeypatch, mode):
    """Class A (demo-v2): the app's default is absolute (V1F), so the harness path must score with the same
    module_a.settings config; the check compares like with like in whichever mode MODULE_A_SCORING selects."""
    monkeypatch.setenv("MODULE_A_SCORING", mode)
    result = config_check(2, n_parts=40)
    assert result["parts_compared"] > 0
    assert result["max_abs_combined_severity_diff"] < TOLERANCE
    assert result["severity_tier_mismatches"] == 0 and result["pass"] is True
