"""scripts/config_check.py: the app pipeline and the harness live path agree on a small lot."""
from scripts.config_check import TOLERANCE, config_check


def test_pipeline_and_harness_live_path_agree_on_two_small_lots():
    result = config_check(2, n_parts=40)
    assert result["parts_compared"] > 0
    assert result["max_abs_combined_severity_diff"] < TOLERANCE
    assert result["severity_tier_mismatches"] == 0 and result["pass"] is True
