"""Session P2.2: POST /lots, /lots/{lot_id}/checkpoints, /lots/demo - real parsing,
validation, merge, and the demo-lot button, over the interim in-process store."""
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ingestion import store
from ingestion.router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    store.clear()
    yield
    store.clear()


def _csv_file(text: str):
    return {"file": ("lot.csv", io.BytesIO(text.encode()), "text/csv")}


VALID_CSV = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,0,1.2,uA\nc2,iddq,0,1.1,uA\n"
METADATA = {"lot_id": "L1", "part_number": "PN-1", "manufacturer": "ACME", "date_code": "2601", "account_id": "a.sharma"}


def test_post_lots_parses_and_stores_a_real_upload():
    response = client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    assert response.status_code == 200
    assert response.json() == {"lot_id": "L1", "part_number": "PN-1", "status": "IN_PROGRESS", "reading_count": 2}


def test_post_lots_requires_metadata_fields():
    response = client.post("/lots", files=_csv_file(VALID_CSV), data={"lot_id": "L1"})
    assert response.status_code == 422


def test_post_lots_returns_422_with_specific_errors_on_bad_csv():
    bad_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,not-a-number,1.2,uA\n"
    response = client.post("/lots", files=_csv_file(bad_csv), data=METADATA)
    assert response.status_code == 422
    assert any("checkpoint_hour" in e for e in response.json()["detail"])


def test_post_lots_rejects_a_second_upload_for_the_same_lot_id():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    response = client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    assert response.status_code == 409


def test_post_lots_checkpoints_merges_into_the_existing_lot():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    checkpoint_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,24,1.3,uA\nc2,iddq,24,1.2,uA\n"
    response = client.post("/lots/L1/checkpoints", files=_csv_file(checkpoint_csv))
    assert response.status_code == 200
    assert response.json() == {"lot_id": "L1", "part_number": "PN-1", "status": "IN_PROGRESS", "reading_count": 4}


def test_post_lots_checkpoints_flips_status_to_complete_at_168h():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    checkpoint_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,168,1.5,uA\nc2,iddq,168,1.4,uA\n"
    response = client.post("/lots/L1/checkpoints", files=_csv_file(checkpoint_csv))
    assert response.json()["status"] == "COMPLETE"


def test_post_lots_checkpoints_404s_on_an_unknown_lot():
    response = client.post("/lots/does-not-exist/checkpoints", files=_csv_file(VALID_CSV))
    assert response.status_code == 404


def test_post_lots_demo_returns_a_complete_synthetic_lot():
    response = client.post("/lots/demo", data={"account_id": "a.sharma"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETE"
    assert body["reading_count"] > 0
    assert body["lot_id"].startswith("demo-")


def test_post_lots_demo_returns_a_fresh_lot_id_each_call():
    first = client.post("/lots/demo", data={"account_id": "a.sharma"}).json()
    second = client.post("/lots/demo", data={"account_id": "a.sharma"}).json()
    assert first["lot_id"] != second["lot_id"]
