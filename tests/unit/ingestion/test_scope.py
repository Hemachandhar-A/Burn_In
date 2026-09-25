"""E7 step 9: cross-lot pooling scope enforcement - stays within one part number."""
import pytest

from contracts import LotDataset, Reading
from ingestion.scope import CrossPartNumberScopeError, assert_same_part_number, filter_by_part_number


def _dataset(lot_id: str, part_number: str) -> LotDataset:
    reading = Reading(
        component_id="c1", lot_id=lot_id, part_number=part_number, manufacturer="ACME",
        date_code="2601", parameter="iddq", checkpoint_hour=0.0, value=1.0, unit="uA",
    )
    return LotDataset(lot_id=lot_id, part_number=part_number, status="IN_PROGRESS", readings=[reading], account_id="a.sharma")


def test_assert_same_part_number_returns_the_shared_value():
    datasets = [_dataset("L1", "PN-1"), _dataset("L2", "PN-1")]
    assert assert_same_part_number(datasets) == "PN-1"


def test_assert_same_part_number_raises_across_different_part_numbers():
    datasets = [_dataset("L1", "PN-1"), _dataset("L2", "PN-2")]
    with pytest.raises(CrossPartNumberScopeError):
        assert_same_part_number(datasets)


def test_filter_by_part_number_keeps_only_matching_lots():
    datasets = [_dataset("L1", "PN-1"), _dataset("L2", "PN-2"), _dataset("L3", "PN-1")]
    filtered = filter_by_part_number(datasets, "PN-1")
    assert [d.lot_id for d in filtered] == ["L1", "L3"]
