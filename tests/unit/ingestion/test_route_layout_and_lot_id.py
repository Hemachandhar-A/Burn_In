"""Session 7b F4/F5: POST /lots and POST /lots/{lot_id}/checkpoints pick the CSV parser from the header row
(long vs the pinned wide layout), and POST /lots refuses a lot_id no later route could address."""
import csv
import importlib
import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ingestion import store
from ingestion.router import router

DEMO = Path(__file__).resolve().parents[3] / "demo_data"
META = {"part_number": "DEMO-PN", "manufacturer": "Northvale", "date_code": "2603", "account_id": "a.sharma"}

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    from storage import database

    importlib.reload(database)
    from storage import repository

    importlib.reload(repository)
    repository.init_db()
    store.clear()
    yield
    store.clear()


def _to_wide(long_csv: bytes) -> bytes:
    wide: dict[tuple[str, str], dict[str, str]] = {}
    for r in csv.DictReader(io.StringIO(long_csv.decode())):
        wide.setdefault((r["component_id"], r["checkpoint_hour"]), {})[f"{r['parameter']}_{r['unit']}"] = r["value"]
    cols = sorted({c for v in wide.values() for c in v})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["component_id", "checkpoint_hour", *cols])
    for (cid, hour), vals in wide.items():
        w.writerow([cid, hour, *[vals.get(c, "") for c in cols]])
    return buf.getvalue().encode()


def _post(lot_id, data: bytes):
    return client.post("/lots", files={"file": ("lot.csv", data, "text/csv")}, data={"lot_id": lot_id, **META})


def _checkpoint(lot_id, data: bytes):
    return client.post(
        f"/lots/{lot_id}/checkpoints", files={"file": ("cp.csv", data, "text/csv")}, data={"account_id": "a.sharma"}
    )


def _fingerprint(lot_id):
    from storage import repository

    from contracts import AnalysisResults

    row = repository.query_latest_project_data(lot_id)
    assert row is not None
    res = AnalysisResults.model_validate_json(row.results_json)
    return (
        res.disposition.verdict,
        res.disposition.pda_result,
        sorted((a.component_id.split("-", 2)[-1], a.verdict, a.module_a_rank, a.module_b_rank) for a in res.assessments),
        sum(a.verdict != "PASS" for a in res.assessments),
    )


def test_wide_and_long_new_lot_give_identical_analysis():
    long_csv = (DEMO / "full_lot.csv").read_bytes()
    assert _post("W-LONG", long_csv).status_code == 200
    wide = _post("W-WIDE", _to_wide(long_csv))
    assert wide.status_code == 200, wide.text
    a, b = _fingerprint("W-LONG"), _fingerprint("W-WIDE")
    assert a == b
    assert a[3] > 0  # the comparison is not vacuous: something was flagged


def test_wide_checkpoint_equals_long_checkpoint():
    base = (DEMO / "live_0h_24h.csv").read_bytes()
    cp = (DEMO / "live_96h.csv").read_bytes()
    for lot in ("C-LONG", "C-WIDE"):
        assert _post(lot, base).status_code == 200
    assert _checkpoint("C-LONG", cp).status_code == 200
    r = _checkpoint("C-WIDE", _to_wide(cp))
    assert r.status_code == 200, r.text
    assert _fingerprint("C-LONG") == _fingerprint("C-WIDE")


def test_header_matching_neither_layout_is_422_naming_both():
    r = _post("BAD-HDR", b"foo,bar\n1,2\n")
    assert r.status_code == 422
    text = str(r.json()["detail"])
    assert "component_id" in text and "checkpoint_hour" in text
    assert "parameter" in text and "value" in text and "unit" in text
    assert "<parameter>_<unit>" in text
    assert store.get("BAD-HDR") is None


def test_checkpoint_header_matching_neither_layout_is_422():
    assert _post("CP-BAD", (DEMO / "live_0h_24h.csv").read_bytes()).status_code == 200
    assert _checkpoint("CP-BAD", b"foo,bar\n1,2\n").status_code == 422


@pytest.mark.parametrize("lot_id", ["A/B", "..", ".", "", "x" * 65, "has space", "-leading", ".hidden", "tab\t", "é1"])
def test_bad_lot_ids_are_422_and_leave_no_state(lot_id):
    r = _post(lot_id, (DEMO / "live_0h_24h.csv").read_bytes())
    assert r.status_code == 422, (lot_id, r.status_code)
    if lot_id:  # an empty form field never reaches the handler: FastAPI itself answers "Field required" (422)
        assert "1 to 64" in str(r.json()["detail"])
    assert store.get(lot_id) is None


@pytest.mark.parametrize("lot_id", ["LIVE-01", "DEMO-COMPLETE-01", "a", "x" * 64, "L.1_b-2"])
def test_valid_lot_ids_are_accepted(lot_id):
    r = _post(lot_id, (DEMO / "live_0h_24h.csv").read_bytes())
    assert r.status_code == 200, r.text
