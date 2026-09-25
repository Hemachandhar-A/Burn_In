"""Session P2.2 (IMPLEMENTATION_PLAN.md Part 10): E7 steps 1-5 - real upload parsing,
schema validation, incremental merge-by-part-ID, and the demo-lot button.

Session P2.3: E7 steps 6-11 wired in - unit normalization (`ingestion.units`), data-quality
flags (`ingestion.quality`, surfaced via `GET /lots/{lot_id}/quality` since `LotUploadResponse`
has no field for them - a frozen contract, not editable here), optional tester-offset
correction (`ingestion.offset`) when the uploader supplies reference-part expected values, and
per-event attribution (`ingestion.store`'s interim `events` list).

`account_id` is a form field, not `Depends(get_current_account)` - `identity/` (P5) doesn't
exist yet (same interim as P2.1's stub). `ingestion.store` is an in-process placeholder for
`project_data` (P2.6) - not durable, replaced there. Real pipeline/persistence wiring
(`fusion.run_full_pipeline`, `storage.save_analysis_run`) is session P2.5.
"""
import json
import uuid

from fastapi import APIRouter, Form, HTTPException, UploadFile

from contracts import LotDataset, LotUploadResponse
from generator.lot import generate_lot
from ingestion import store
from ingestion.merge import compute_status, merge_checkpoint
from ingestion.offset import apply_tester_offset_correction
from ingestion.parsing import IngestionValidationError, parse_lot_csv
from ingestion.quality import QualityFlag, run_quality_checks
from ingestion.units import normalize_readings

router = APIRouter(tags=["ingestion"])


def _normalize_and_correct(
    readings: list, reference_expected_json: str | None
) -> list:
    """Shared E7 steps 6+8 pipeline: unit normalization, then optional tester-offset
    correction. Raises `HTTPException(422)` on a genuine cross-family unit mismatch, using the
    same visible-error convention as parsing (E7 step 5)."""
    normalized, unit_errors = normalize_readings(readings)
    if unit_errors:
        raise HTTPException(status_code=422, detail=unit_errors)
    reference_expected = json.loads(reference_expected_json) if reference_expected_json else None
    return apply_tester_offset_correction(normalized, reference_expected)


@router.post("/lots", response_model=LotUploadResponse)
async def upload_lot(
    file: UploadFile,
    lot_id: str = Form(...),
    part_number: str = Form(...),
    manufacturer: str = Form(...),
    date_code: str = Form(...),
    account_id: str = Form(...),
    test_date: str | None = Form(default=None),  # CONTRACT_CHANGES.md: no frozen field yet
    reference_expected_json: str | None = Form(default=None),  # E7 step 8, see ingestion/offset.py
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
    readings = _normalize_and_correct(readings, reference_expected_json)

    dataset = LotDataset(
        lot_id=lot_id,
        part_number=part_number,
        status=compute_status(readings),
        readings=readings,
        account_id=account_id,
    )
    store.put(lot_id, dataset, test_date=test_date, event_type="ingest", account_id=account_id)
    return LotUploadResponse(
        lot_id=dataset.lot_id, part_number=dataset.part_number, status=dataset.status,
        reading_count=len(dataset.readings),
    )


@router.post("/lots/{lot_id}/checkpoints", response_model=LotUploadResponse)
async def upload_checkpoint(
    lot_id: str,
    file: UploadFile,
    account_id: str = Form(...),  # E7 step 11: every ingestion event is attributed, not just the first
    reference_expected_json: str | None = Form(default=None),
) -> LotUploadResponse:
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
    new_readings = _normalize_and_correct(new_readings, reference_expected_json)

    merged = merge_checkpoint(existing, new_readings)
    store.put(lot_id, merged, event_type="checkpoint_add", account_id=account_id)
    return LotUploadResponse(
        lot_id=merged.lot_id, part_number=merged.part_number, status=merged.status,
        reading_count=len(merged.readings),
    )


@router.get("/lots/{lot_id}/quality")
async def get_quality_flags(lot_id: str) -> list[dict]:
    """E7 step 7, surfaced separately from `LotUploadResponse` - that response model is frozen
    (`contracts.py`) with no field for quality flags; logged in CONTRACT_CHANGES.md rather than
    hand-edited. Not a contract type itself, so no `response_model` - plain JSON."""
    record = store.get(lot_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"lot '{lot_id}' not found")
    flags = run_quality_checks(record.dataset.readings)
    return [_flag_to_dict(flag) for flag in flags]


def _flag_to_dict(flag: QualityFlag) -> dict:
    return {
        "component_id": flag.component_id, "parameter": flag.parameter,
        "flag_type": flag.flag_type, "message": flag.message,
    }


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
