"""Session P2.2 (IMPLEMENTATION_PLAN.md Part 10): E7 steps 1-5 - real upload parsing,
schema validation, incremental merge-by-part-ID, and the demo-lot button.

Deferred to later sessions: unit normalization, data-quality/out-of-range flags, tester-offset
correction, cross-lot scope enforcement, and real-data format nuances (wide/long equivalence,
unit mismatch, irregular checkpoints) - E7 steps 6-11, session P2.3, against real data.

`account_id` is a form field, not `Depends(get_current_account)` - `identity/` (P5) doesn't
exist yet (same interim as P2.1's stub). `ingestion.store` is an in-process placeholder for
`project_data` (P2.6) - not durable, replaced there. Real pipeline/persistence wiring
(`fusion.run_full_pipeline`, `storage.save_analysis_run`) is session P2.5.
"""
import uuid

from fastapi import APIRouter, Form, HTTPException, UploadFile

from contracts import LotDataset, LotUploadResponse
from generator.lot import generate_lot
from ingestion import store
from ingestion.merge import compute_status, merge_checkpoint
from ingestion.parsing import IngestionValidationError, parse_lot_csv

router = APIRouter(tags=["ingestion"])


@router.post("/lots", response_model=LotUploadResponse)
async def upload_lot(
    file: UploadFile,
    lot_id: str = Form(...),
    part_number: str = Form(...),
    manufacturer: str = Form(...),
    date_code: str = Form(...),
    account_id: str = Form(...),
    test_date: str | None = Form(default=None),  # CONTRACT_CHANGES.md: no frozen field yet
) -> LotUploadResponse:
    if store.get(lot_id) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"lot '{lot_id}' already exists - use POST /lots/{{lot_id}}/checkpoints to add a checkpoint",
        )

    raw = await file.read()
    try:
        readings = parse_lot_csv(
            raw, lot_id=lot_id, part_number=part_number, manufacturer=manufacturer, date_code=date_code
        )
    except IngestionValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc

    dataset = LotDataset(
        lot_id=lot_id,
        part_number=part_number,
        status=compute_status(readings),
        readings=readings,
        account_id=account_id,
    )
    store.put(lot_id, dataset, test_date=test_date)
    return LotUploadResponse(
        lot_id=dataset.lot_id, part_number=dataset.part_number, status=dataset.status,
        reading_count=len(dataset.readings),
    )


@router.post("/lots/{lot_id}/checkpoints", response_model=LotUploadResponse)
async def upload_checkpoint(lot_id: str, file: UploadFile) -> LotUploadResponse:
    record = store.get(lot_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"lot '{lot_id}' not found - upload it first via POST /lots")

    existing = record.dataset
    first = existing.readings[0]  # upload_lot never stores a lot with zero readings
    raw = await file.read()
    try:
        new_readings = parse_lot_csv(
            raw, lot_id=existing.lot_id, part_number=existing.part_number,
            manufacturer=first.manufacturer, date_code=first.date_code,
        )
    except IngestionValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc

    merged = merge_checkpoint(existing, new_readings)
    store.put(lot_id, merged)
    return LotUploadResponse(
        lot_id=merged.lot_id, part_number=merged.part_number, status=merged.status,
        reading_count=len(merged.readings),
    )


@router.post("/lots/demo", response_model=LotUploadResponse)
async def load_demo_lot(account_id: str = Form(...)) -> LotUploadResponse:
    """E7 step 2: a synthetic demo lot, so the system is demonstrable without a file on hand.
    A fresh lot_id per call (so repeat clicks don't collide); the generator's own seed/family
    defaults otherwise, so the demo lot is deterministic given that lot_id (AGENTS.md rule 9)."""
    lot_id = f"demo-{uuid.uuid4().hex[:8]}"
    generated = generate_lot(lot_id=lot_id, part_number="DEMO-PN", seed=42, account_id=account_id)
    store.put(lot_id, generated.dataset)
    return LotUploadResponse(
        lot_id=generated.dataset.lot_id, part_number=generated.dataset.part_number,
        status=generated.dataset.status, reading_count=len(generated.dataset.readings),
    )
