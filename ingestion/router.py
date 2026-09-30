"""Session P2.2 (IMPLEMENTATION_PLAN.md Part 10): E7 steps 1-5 - real upload parsing,
schema validation, incremental merge-by-part-ID, and the demo-lot button.

Session P2.3: E7 steps 6-11 wired in - unit normalization (`ingestion.units`), data-quality
flags (`ingestion.quality`, surfaced via `GET /lots/{lot_id}/quality` since `LotUploadResponse`
has no field for them - a frozen contract, not editable here), optional tester-offset
correction (`ingestion.offset`) when the uploader supplies reference-part expected values, and
per-event attribution (`ingestion.store`'s interim `events` list).

`account_id` is a form field, not `Depends(get_current_account)` - `identity/` (P5) doesn't
exist yet (same interim as P2.1's stub). `ingestion.store` is an in-process placeholder for
`project_data` (P2.6) - not durable, replaced there.

Session P2.5: real pipeline/persistence wiring. `POST /lots` and `POST /lots/{lot_id}/checkpoints`
call `fusion.run_full_pipeline` after a successful save, then `storage.save_analysis_run(...)`,
then `storage.log_event("analysis_run", ...)`. A `storage.Project` row is created on first
upload with `project_id == lot_id` - `Project`/`ProjectData`/`Event` are keyed by `project_id`,
not `lot_id`, but this codebase has no notion of more than one project per lot, so reusing the
lot_id as the project_id avoids inventing a second identifier for the same thing; checkpoints
reuse the same row (`repository.query_project` no-ops the second time). `Project.test_date` has
no form field of its own yet on the checkpoint route (only on the initial upload), so it defaults
to "now" if the lot's first upload didn't supply one.

Session P2 follow-up: the `RiskAssessment`/`AnalysisResults` gap logged by P2.6/P2.7/P2.5 was
resolved on `develop` (`RiskAssessment` now carries `module_a_ran`, `module_b_ran`,
`predicted_168h`, `actual_168h`, `explanation_sentence` per component). `AnalysisResults` is
persisted as-is (`results.model_dump_json()` in the repository) - no reshaping step, so module ranks and
`worst_parameter` reach `GET /lots/{lot_id}` intact.
"""
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Form, HTTPException, UploadFile

from contracts import AnalysisResults, LotDataset, LotUploadResponse, ScreeningConfig
from fusion.pipeline import run_full_pipeline
from generator.lot import generate_lot
from ingestion import store
from ingestion.merge import compute_status, merge_checkpoint
from ingestion.offset import apply_tester_offset_correction
from ingestion.parsing import IngestionValidationError, parse_lot_csv
from ingestion.quality import QualityFlag, check_missing_checkpoints, run_quality_checks
from ingestion.units import normalize_readings
from storage import repository

router = APIRouter(tags=["ingestion"])


def _parse_test_date(test_date: str | None) -> datetime:
    """The lot's physical test date from the metadata form (E7 step 1); now() when none was supplied. A value
    that isn't ISO 8601 is a visible 422 naming the field and what was received (E7 step 5), never a 500."""
    if not test_date:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(test_date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=[
                f"test_date: expected an ISO 8601 date or datetime (e.g. 2026-09-26 or 2026-09-26T14:30:00), "
                f"got {test_date!r}"
            ],
        ) from None


def _ensure_project(dataset: LotDataset, account_id: str, test_date: str | None) -> None:
    if repository.query_project(dataset.lot_id) is not None:
        return
    parsed_test_date = _parse_test_date(test_date)
    repository.save_project(
        project_id=dataset.lot_id, lot_id=dataset.lot_id, part_number=dataset.part_number,
        test_date=parsed_test_date, created_by=account_id,
    )


def _run_pipeline_and_persist(
    dataset: LotDataset, account_id: str, test_date: str | None = None
) -> None:
    _ensure_project(dataset, account_id, test_date)
    results = run_full_pipeline(dataset, ScreeningConfig())
    repository.save_analysis_run(
        project_id=dataset.lot_id,
        raw_data=dataset.model_dump(mode="json"),
        results=results,
    )
    repository.log_event(
        project_id=dataset.lot_id, account_id=account_id, event_type="analysis_run",
        payload={"verdict": results.disposition.verdict, "pda_result": results.disposition.pda_result},
    )


def _log_ingestion_event(
    dataset: LotDataset, account_id: str, event_type: str, test_date: str | None = None
) -> None:
    """Persist an `ingest` / `checkpoint_add` event (E7 step 11, context.md 5.10) alongside the
    `analysis_run` one - previously these only reached the in-process `store.events` list. The Project row
    must exist first (events reference it), so it is ensured here; `_ensure_project` is idempotent."""
    _ensure_project(dataset, account_id, test_date)
    repository.log_event(
        project_id=dataset.lot_id, account_id=account_id, event_type=event_type,
        payload={"reading_count": len(dataset.readings), "status": dataset.status},
    )


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

    # Validated before anything is stored: a 422 must leave no state behind, or the corrected retry would 409.
    _parse_test_date(test_date)

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
    _log_ingestion_event(dataset, account_id, "ingest", test_date)
    _run_pipeline_and_persist(dataset, account_id, test_date=test_date)
    return LotUploadResponse(
        lot_id=dataset.lot_id, part_number=dataset.part_number, status=dataset.status,
        reading_count=len(dataset.readings),
        insufficient_data_components=_insufficient_data_components(dataset.readings),
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
    _log_ingestion_event(merged, account_id, "checkpoint_add")
    _run_pipeline_and_persist(merged, account_id)
    return LotUploadResponse(
        lot_id=merged.lot_id, part_number=merged.part_number, status=merged.status,
        reading_count=len(merged.readings),
        insufficient_data_components=_insufficient_data_components(merged.readings),
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


def _insufficient_data_components(readings: list) -> list[str]:
    """R7 (AGENTS.md): components missing 0h or 24h for some parameter, never a silent drop.
    Only populates LotUploadResponse.insufficient_data_components - never rejects or changes what
    is stored or analysed. Callers pass the full (merged, for checkpoints) reading set so a
    completed component drops off the list rather than staying flagged from a prior upload."""
    flags = check_missing_checkpoints(readings)
    return sorted({flag.component_id for flag in flags if flag.flag_type == "INSUFFICIENT_DATA"})


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
    _log_ingestion_event(generated.dataset, account_id, "ingest")
    _run_pipeline_and_persist(generated.dataset, account_id)  # same sequence as POST /lots (P2.5)
    return LotUploadResponse(
        lot_id=generated.dataset.lot_id, part_number=generated.dataset.part_number,
        status=generated.dataset.status, reading_count=len(generated.dataset.readings),
    )
