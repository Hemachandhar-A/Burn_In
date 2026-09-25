"""Session P2.1 stub (IMPLEMENTATION_PLAN.md Part 10): `POST /lots` returns a canned
response so P1's frontend has something to hit early. Real parsing, validation,
incremental merge, and cross-lot checks (E7 steps 3-11) land in sessions P2.2-P2.3.

Not wired behind auth yet: `identity/`'s `get_current_account` dependency (P5) doesn't
exist yet either - session P2.5 is where this route gets the real `Depends(...)`, at the
same time it starts calling `fusion.run_full_pipeline` instead of returning a stub.
"""
from fastapi import APIRouter, Form, UploadFile

from contracts import LotUploadResponse

router = APIRouter(tags=["ingestion"])


@router.post("/lots", response_model=LotUploadResponse)
async def upload_lot(
    file: UploadFile,
    lot_id: str = Form(...),
    part_number: str = Form(...),
    manufacturer: str = Form(...),
    date_code: str = Form(...),
) -> LotUploadResponse:
    return LotUploadResponse(lot_id=lot_id, part_number=part_number, status="IN_PROGRESS", reading_count=0)
