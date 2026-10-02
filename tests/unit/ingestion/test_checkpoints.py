"""P2.3: nominal-checkpoint labeling with real-world timing tolerance."""
from ingestion.checkpoints import label_for_hour


def test_exact_nominal_hours_label_correctly():
    assert label_for_hour(0.0) == "0h"
    assert label_for_hour(24.0) == "24h"
    assert label_for_hour(96.0) == "96h"
    assert label_for_hour(168.0) == "168h"


def test_jittered_hour_within_tolerance_labels_to_nearest_nominal():
    assert label_for_hour(167.6) == "168h"
    assert label_for_hour(23.5) == "24h"


def test_hour_far_from_any_nominal_checkpoint_is_unlabeled():
    assert label_for_hour(60.0) is None


def test_hour_past_168h_with_no_actual_168h_read_is_unlabeled():
    assert label_for_hour(200.0) is None


def test_zero_hour_tolerance_floor_does_not_swallow_nearby_24h():
    # 0h's window is the 1.0h floor (10% of 0 is 0), so a 0.5h read still counts as 0h...
    assert label_for_hour(0.5) == "0h"
    # ...but a 2h read is outside that floor and doesn't fall back to 0h.
    assert label_for_hour(2.0) is None
