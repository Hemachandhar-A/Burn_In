"""Session P2.1 stub: POST /lots returns a canned, correctly-shaped LotUploadResponse."""
import io

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ingestion.router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_post_lots_returns_canned_lot_upload_response():
    response = client.post(
        "/lots",
        files={"file": ("lot.csv", io.BytesIO(b"component_id,parameter,value\n"), "text/csv")},
        data={"lot_id": "L1", "part_number": "PN-1", "manufacturer": "ACME", "date_code": "2601"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"lot_id": "L1", "part_number": "PN-1", "status": "IN_PROGRESS", "reading_count": 0}


def test_post_lots_requires_metadata_fields():
    response = client.post(
        "/lots",
        files={"file": ("lot.csv", io.BytesIO(b""), "text/csv")},
        data={"lot_id": "L1"},  # missing part_number/manufacturer/date_code
    )
    assert response.status_code == 422
