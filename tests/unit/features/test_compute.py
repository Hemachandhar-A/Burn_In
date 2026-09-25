"""Session P2.1 stub: features.compute() returns a correctly-shaped FeatureFrame list.
Real statistics arrive in session P2.4 (E8) - this only pins the stub's contract shape.
"""
from contracts import LotDataset, Reading
from features.compute import compute


def _reading(component_id: str, parameter: str, checkpoint_hour: float, value: float) -> Reading:
    return Reading(
        component_id=component_id,
        lot_id="L1",
        part_number="PN-1",
        manufacturer="m",
        date_code="2601",
        parameter=parameter,
        checkpoint_hour=checkpoint_hour,
        value=value,
        unit="uA",
    )


def _lot(component_ids: list[str], parameters: list[str]) -> LotDataset:
    readings = [
        _reading(cid, param, 0.0, 1.0) for cid in component_ids for param in parameters
    ]
    return LotDataset(
        lot_id="L1", part_number="PN-1", status="IN_PROGRESS", readings=readings, account_id="a.sharma"
    )


def test_one_frame_per_component_parameter_pair():
    lot = _lot(["c1", "c2"], ["iddq", "leakage"])
    frames = compute(lot)
    pairs = {(f.component_id, f.parameter) for f in frames}
    assert pairs == {("c1", "iddq"), ("c1", "leakage"), ("c2", "iddq"), ("c2", "leakage")}


def test_lot_id_and_part_number_carried_through_from_the_lot():
    lot = _lot(["c1"], ["iddq"])
    frame = compute(lot)[0]
    assert frame.lot_id == "L1"
    assert frame.part_number == "PN-1"


def test_small_lot_triggers_pooled_fallback_flag():
    lot = _lot([f"c{i}" for i in range(5)], ["iddq"])
    frames = compute(lot)
    assert all(f.used_pooled_fallback for f in frames)
    assert all(f.lot_size == 5 for f in frames)


def test_lot_of_30_or_more_does_not_trigger_pooled_fallback():
    lot = _lot([f"c{i}" for i in range(30)], ["iddq"])
    frames = compute(lot)
    assert not any(f.used_pooled_fallback for f in frames)
