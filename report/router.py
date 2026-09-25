"""Session P2.7 (IMPLEMENTATION_PLAN.md Part 10): `POST /lots/{lot_id}/report` (Part 5.6's
route table) - binary PDF by default with a `Content-Disposition` header, CSV/JSON via
`Accept` negotiation (E9 steps 3-5).

No `Depends(get_current_account)` yet - `identity/` (P5.4) isn't merged, same interim as
`ingestion/router.py` and `storage/router.py`.
"""
import json

from fastapi import APIRouter, HTTPException, Request, Response

from report import csv_export, json_export
from report.data import build_report_data
from report.pdf import render_pdf
from storage import repository

router = APIRouter(tags=["report"])


def _resolve_project_id(lot_id: str) -> str:
    matches = [p for p in repository.query_projects() if p.lot_id == lot_id]
    if not matches:
        raise HTTPException(status_code=404, detail=f"no project found for lot '{lot_id}'")
    # `query_projects` orders by `created_at` descending - the first match is the most recent
    # project for this `lot_id`.
    return matches[0].project_id


@router.post("/lots/{lot_id}/report")
async def generate_report(lot_id: str, request: Request) -> Response:
    project_id = _resolve_project_id(lot_id)
    try:
        report = build_report_data(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    accept = request.headers.get("accept", "")

    if "application/json" in accept:
        return Response(content=json.dumps(json_export.to_json_dict(report)), media_type="application/json")

    if "text/csv" in accept:
        raw_data = json.loads(repository.query_latest_project_data(project_id).raw_data)
        return Response(
            content=csv_export.render_csv(raw_data), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{report.report_reference_id}.csv"'},
        )

    pdf_bytes = bytes(render_pdf(report))
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.report_reference_id}.pdf"'},
    )
