"""G5 gate, Part D (Block 4b): every P5 route in IMPLEMENTATION_PLAN.md Part 5.6 exercised TOGETHER
through the real app (`api.main.app`, every router registered), one isolated DB, real data: the golden
lot (COMPLETE, uploaded as a CSV through POST /lots) plus one IN_PROGRESS lot. Per route:
  (i)   valid token -> success code, body validates against the route's declared response model
  (ii)  no token -> 401 wherever the plan says auth is required
  (iii) malformed body/query -> 422 where a body/required query exists
  (iv)  unknown id -> 404 where an id is in the path
then one flow across routes. The final test prints the route x check table (run with -s).

`GET /lots/{lot_id}` is planned as auth-required (Part 5.6) but fusion/router.py registers no
get_current_account dependency on it: that check is marked xfail(strict=True) as an OPEN G5 finding -
it turns red the moment the route is fixed, so the marker can never go stale.
"""
import csv
import io
import os

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from contracts import (
    ConfirmedOutcomeRecord, CorrectiveStatusResponse, DispositionRecord, DPAWorkOrderResponse,
    LotSummaryResponse, PartDetailResponse, PendingSettingChange, SettingsResponse, TokenResponse,
    WorklistResponse,
)
from harness.golden import GOLDEN_COMPONENT_ID, GOLDEN_LOT_ID, golden_lot

IN_PROGRESS_LOT_ID = "IP-LOT-01"
IN_PROGRESS_PART = "G-005"  # its 24h leakage is inflated so Module B forecasts a real early reject
TABLE: dict[str, dict[str, str]] = {}


def _record(route: str, check: str, result: str = "ok") -> None:
    TABLE.setdefault(route, {})[check] = result


def _csv_bytes(readings) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["component_id", "parameter", "checkpoint_hour", "value", "unit"])
    for r in readings:
        w.writerow([r.component_id, r.parameter, r.checkpoint_hour, r.value, r.unit])
    return buf.getvalue().encode()


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """One isolated DB + the real app + both lots uploaded through POST /lots."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from ingestion import store
    from storage import database, repository

    mp = pytest.MonkeyPatch()
    db = tmp_path_factory.mktemp("g5routes") / "routes.db"
    engine = create_engine(f"sqlite:///{db}")
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    mp.setattr(database, "engine", engine)
    mp.setattr(database, "SessionLocal", session_local)
    mp.setattr(repository, "SessionLocal", session_local)
    repository.init_db()
    store.clear()
    hasher = PasswordHasher()
    repository.save_account("a.sharma", "A. Sharma", "Quality Engineer", hasher.hash("1234"))
    repository.save_account("r.mehta", "R. Mehta", "Reliability Engineer", hasher.hash("5678"))

    from api.main import app
    client = TestClient(app)

    def login(account_id, pin):
        r = client.post("/auth/login", json={"account_id": account_id, "pin": pin})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    sharma, mehta = login("a.sharma", "1234"), login("r.mehta", "5678")

    def upload(lot_id, readings):
        meta = {"lot_id": lot_id, "part_number": "PN-GOLDEN", "manufacturer": "GOLDEN-MFR",
                "date_code": "2601", "account_id": "a.sharma"}
        r = client.post("/lots", files={"file": ("lot.csv", _csv_bytes(readings), "text/csv")}, data=meta,
                        headers=sharma)
        assert r.status_code == 200, r.text
        return r.json()

    gold = golden_lot()
    up_gold = upload(GOLDEN_LOT_ID, gold.readings)
    assert up_gold["status"] == "COMPLETE"
    ip_readings = []
    for r in gold.readings:
        if r.checkpoint_hour not in (0, 24):
            continue
        if r.component_id == IN_PROGRESS_PART and r.parameter == "leakage" and r.checkpoint_hour == 24:
            r = r.model_copy(update={"value": r.value * 3.0})
        ip_readings.append(r)
    up_ip = upload(IN_PROGRESS_LOT_ID, ip_readings)
    assert up_ip["status"] == "IN_PROGRESS"

    yield {"client": client, "sharma": sharma, "mehta": mehta, "login": login}
    mp.undo()
    store.clear()


def _part_ids(env):
    """(project_id, analysis_run_id) for a part, straight from GET /parts - the documented round trip."""
    r = env["client"].get(f"/parts/{GOLDEN_COMPONENT_ID}", headers=env["sharma"])
    assert r.status_code == 200
    return r.json()["project_id"], r.json()["analysis_run_id"]


# --- POST /auth/login -------------------------------------------------------------------------------

def test_login(env):
    c = env["client"]
    r = c.post("/auth/login", json={"account_id": "a.sharma", "pin": "1234"})
    assert r.status_code == 200
    TokenResponse.model_validate(r.json()); _record("POST /auth/login", "200+model")
    assert c.post("/auth/login", json={"account_id": "a.sharma"}).status_code == 422
    _record("POST /auth/login", "422")
    assert c.post("/auth/login", json={"account_id": "a.sharma", "pin": "0000"}).status_code == 401
    assert c.post("/auth/login", json={"account_id": "nobody", "pin": "1234"}).status_code == 401
    _record("POST /auth/login", "wrong pin/unknown acct=401")


# --- GET /lots/{lot_id} -----------------------------------------------------------------------------

def test_get_lot_valid_and_404(env):
    c = env["client"]
    for lot_id, status, forecast in ((GOLDEN_LOT_ID, "COMPLETE", False), (IN_PROGRESS_LOT_ID, "IN_PROGRESS", True)):
        r = c.get(f"/lots/{lot_id}", headers=env["sharma"])
        assert r.status_code == 200
        body = LotSummaryResponse.model_validate(r.json())
        assert body.disposition.status == status and body.disposition.is_forecast is forecast
    _record("GET /lots/{lot_id}", "200+model")
    assert c.get("/lots/NO-SUCH-LOT", headers=env["sharma"]).status_code == 404
    _record("GET /lots/{lot_id}", "404")


@pytest.mark.xfail(strict=True, reason="OPEN G5 finding: GET /lots/{lot_id} (fusion/router.py:25) has no "
                                       "get_current_account dependency; Part 5.6 says auth required")
def test_get_lot_requires_auth_per_plan(env):
    r = env["client"].get(f"/lots/{GOLDEN_LOT_ID}")
    _record("GET /lots/{lot_id}", "401", f"FAIL (got {r.status_code})")
    assert r.status_code == 401


# --- GET /parts/{component_id} ----------------------------------------------------------------------

def test_get_part(env):
    c = env["client"]
    for cid in (GOLDEN_COMPONENT_ID, IN_PROGRESS_PART):
        lot = GOLDEN_LOT_ID if cid == GOLDEN_COMPONENT_ID else IN_PROGRESS_LOT_ID
        r = c.get(f"/parts/{cid}?lot_id={lot}", headers=env["sharma"])
        assert r.status_code == 200, r.text
        body = PartDetailResponse.model_validate(r.json())
        assert body.component_id == cid and body.verdict == "REJECT"
        assert (body.module_a is not None) == (cid == GOLDEN_COMPONENT_ID)  # Module A never runs in-progress
    _record("GET /parts/{component_id}", "200+model")
    assert c.get(f"/parts/{GOLDEN_COMPONENT_ID}").status_code == 401
    _record("GET /parts/{component_id}", "401")
    assert c.get("/parts/NO-SUCH-PART", headers=env["sharma"]).status_code == 404
    assert c.get(f"/parts/{GOLDEN_COMPONENT_ID}?lot_id=NO-SUCH-LOT", headers=env["sharma"]).status_code == 404
    _record("GET /parts/{component_id}", "404")


# --- POST /parts/{component_id}/disposition ---------------------------------------------------------

def test_disposition_checks(env):
    c = env["client"]
    project_id, run_id = _part_ids(env)
    url = f"/parts/{GOLDEN_COMPONENT_ID}/disposition?project_id={project_id}&analysis_run_id={run_id}"
    body = {"verdict": "HOLD", "rationale": "route check"}
    assert c.post(url, json=body).status_code == 401
    _record("POST /parts/{id}/disposition", "401")
    assert c.post(url, json={"verdict": "MAYBE", "rationale": "x"}, headers=env["sharma"]).status_code == 422
    assert c.post(f"/parts/{GOLDEN_COMPONENT_ID}/disposition", json=body, headers=env["sharma"]).status_code == 422
    _record("POST /parts/{id}/disposition", "422")
    r = c.post(url, json=body, headers=env["sharma"])
    assert r.status_code == 200
    DispositionRecord.model_validate(r.json())
    _record("POST /parts/{id}/disposition", "200+model")


@pytest.mark.xfail(strict=True, reason="OPEN G5 finding: POST /parts/{id}/disposition (identity/router.py:41) "
                                       "never checks the component exists - an unknown id is accepted (200)")
def test_disposition_unknown_component_is_404(env):
    project_id, run_id = _part_ids(env)
    r = env["client"].post(f"/parts/NO-SUCH-PART/disposition?project_id={project_id}&analysis_run_id={run_id}",
                           json={"verdict": "HOLD", "rationale": "x"}, headers=env["sharma"])
    _record("POST /parts/{id}/disposition", "404", f"FAIL (got {r.status_code})")
    assert r.status_code == 404


# --- GET /settings, POST /settings/propose, POST /settings/signoff ----------------------------------

def test_settings_routes(env):
    c = env["client"]
    assert c.get("/settings").status_code == 401
    _record("GET /settings", "401")
    r = c.get("/settings", headers=env["sharma"])
    assert r.status_code == 200
    SettingsResponse.model_validate(r.json()); _record("GET /settings", "200+model")

    prop = {"field": "pda_threshold", "proposed_value": 0.07}
    assert c.post("/settings/propose", json=prop).status_code == 401
    _record("POST /settings/propose", "401")
    assert c.post("/settings/propose", json={"field": "not_a_field", "proposed_value": 1}, headers=env["sharma"]).status_code == 422
    assert c.post("/settings/propose", json={"field": "pda_threshold"}, headers=env["sharma"]).status_code == 422
    _record("POST /settings/propose", "422")
    r = c.post("/settings/propose", json=prop, headers=env["sharma"])
    assert r.status_code == 200
    PendingSettingChange.model_validate(r.json()); _record("POST /settings/propose", "200+model")

    assert c.post("/settings/signoff", json={"field": "pda_threshold"}).status_code == 401
    _record("POST /settings/signoff", "401")
    assert c.post("/settings/signoff", json={"field": "not_a_field"}, headers=env["mehta"]).status_code == 422
    assert c.post("/settings/signoff", json={}, headers=env["mehta"]).status_code == 422
    _record("POST /settings/signoff", "422")
    assert c.post("/settings/signoff", json={"field": "pda_threshold"}, headers=env["sharma"]).status_code == 400  # same acct
    r = c.post("/settings/signoff", json={"field": "pda_threshold"}, headers=env["mehta"])
    assert r.status_code == 200
    assert SettingsResponse.model_validate(r.json()).pda_threshold == 0.07
    _record("POST /settings/signoff", "200+model")


# --- POST /parts/{component_id}/confirmed-outcome ---------------------------------------------------

def test_confirmed_outcome_checks(env):
    c = env["client"]
    url = f"/parts/{GOLDEN_COMPONENT_ID}/confirmed-outcome?lot_id={GOLDEN_LOT_ID}"
    body = {"confirmed_outcome": "Confirmed Defective", "note": "DPA found a leakage path"}
    assert c.post(url, json=body).status_code == 401
    _record("POST /parts/{id}/confirmed-outcome", "401")
    assert c.post(url, json={"confirmed_outcome": "Kinda"}, headers=env["sharma"]).status_code == 422
    assert c.post(url, json={}, headers=env["sharma"]).status_code == 422
    _record("POST /parts/{id}/confirmed-outcome", "422")
    assert c.post("/parts/NO-SUCH-PART/confirmed-outcome", json=body, headers=env["sharma"]).status_code == 404
    _record("POST /parts/{id}/confirmed-outcome", "404")
    r = c.post(url, json=body, headers=env["sharma"])
    assert r.status_code == 200
    ConfirmedOutcomeRecord.model_validate(r.json()); _record("POST /parts/{id}/confirmed-outcome", "200+model")


# --- GET /settings/worklist, GET /settings/corrective-status ----------------------------------------

def test_worklist_and_corrective_status(env):
    c = env["client"]
    for path, model in (("/settings/worklist", WorklistResponse), ("/settings/corrective-status", CorrectiveStatusResponse)):
        assert c.get(path).status_code == 401
        _record(f"GET {path}", "401")
        r = c.get(path, headers=env["sharma"])
        assert r.status_code == 200
        model.model_validate(r.json()); _record(f"GET {path}", "200+model")


# --- POST /lots/{lot_id}/dpa-work-order -------------------------------------------------------------

def test_dpa_work_order_checks(env):
    c = env["client"]
    assert c.post(f"/lots/{GOLDEN_LOT_ID}/dpa-work-order").status_code == 401
    _record("POST /lots/{id}/dpa-work-order", "401")
    assert c.post("/lots/NO-SUCH-LOT/dpa-work-order", headers=env["sharma"]).status_code == 404
    _record("POST /lots/{id}/dpa-work-order", "404")
    assert c.post(f"/lots/{IN_PROGRESS_LOT_ID}/dpa-work-order", headers=env["sharma"]).status_code == 409
    r = c.post(f"/lots/{GOLDEN_LOT_ID}/dpa-work-order", headers=env["sharma"])
    assert r.status_code == 200
    body = DPAWorkOrderResponse.model_validate(r.json())
    assert 1 <= len(body.recommendations) <= 3 and body.recommendations[0].component_id == GOLDEN_COMPONENT_ID
    _record("POST /lots/{id}/dpa-work-order", "200+model")
    # 422 is n/a here: the route has no body and no query parameter to malform.
    _record("POST /lots/{id}/dpa-work-order", "422", "n/a (no body/query)")


# --- The flow across routes -------------------------------------------------------------------------

def test_full_flow_across_routes(env):
    """login -> (lot already uploaded through POST /lots) -> GET lot -> GET part -> two disposition
    sign-offs -> confirmed outcome -> worklist shrinks -> corrective status -> DPA work order."""
    c = env["client"]
    sharma = env["login"]("a.sharma", "1234")   # a fresh login, as the flow's first step
    mehta = env["login"]("r.mehta", "5678")

    lot = LotSummaryResponse.model_validate(c.get(f"/lots/{GOLDEN_LOT_ID}", headers=sharma).json())
    flagged = {a.component_id: a.verdict for a in lot.assessments if a.verdict == "REJECT"}
    assert GOLDEN_COMPONENT_ID in flagged

    # Use the lot's other REJECT part (not the golden part, which earlier route checks touched) so the
    # worklist arithmetic below is exact.
    cid = next(k for k in flagged if k != GOLDEN_COMPONENT_ID)
    part = PartDetailResponse.model_validate(c.get(f"/parts/{cid}?lot_id={GOLDEN_LOT_ID}", headers=sharma).json())
    assert part.verdict == "REJECT" and part.disposition_history == []
    url = f"/parts/{cid}/disposition?project_id={part.project_id}&analysis_run_id={part.analysis_run_id}"
    body = {"verdict": "REJECT", "rationale": "flow test"}

    before = WorklistResponse.model_validate(c.get("/settings/worklist", headers=sharma).json()).pending
    assert c.post(url, json=body, headers=sharma).status_code == 200
    assert c.post(url, json=body, headers=sharma).status_code == 400          # same account again
    assert c.post(url, json=body, headers=mehta).status_code == 200            # distinct second account
    after_disp = WorklistResponse.model_validate(c.get("/settings/worklist", headers=sharma).json()).pending
    assert len(after_disp) > len(before) and {d.component_id for d in after_disp} >= {cid}

    hist = PartDetailResponse.model_validate(c.get(f"/parts/{cid}?lot_id={GOLDEN_LOT_ID}", headers=sharma).json())
    assert {h.account_id for h in hist.disposition_history} == {"a.sharma", "r.mehta"}

    out = c.post(f"/parts/{cid}/confirmed-outcome?lot_id={GOLDEN_LOT_ID}", headers=sharma,
                 json={"confirmed_outcome": "Confirmed Defective", "note": "flow"})
    assert out.status_code == 200
    after_outcome = WorklistResponse.model_validate(c.get("/settings/worklist", headers=sharma).json()).pending
    assert len(after_outcome) == len(after_disp) - 2      # both of this part's sign-offs leave the worklist
    assert cid not in {d.component_id for d in after_outcome}

    status = CorrectiveStatusResponse.model_validate(c.get("/settings/corrective-status", headers=sharma).json())
    assert status.status == "INSUFFICIENT_DATA" and status.confirmed_outcome_count >= 2  # far below 10

    dpa = DPAWorkOrderResponse.model_validate(c.post(f"/lots/{GOLDEN_LOT_ID}/dpa-work-order", headers=sharma).json())
    assert dpa.recommendations and dpa.recommendations[0].component_id == GOLDEN_COMPONENT_ID
    _record("FLOW", "login>lot>part>2 signoffs>outcome>worklist>status>dpa")


def test_zz_print_route_table(env):
    rows = sorted(TABLE.items())
    print("\n\nroute | checks")
    for route, checks in rows:
        print(f"{route:40} | " + ", ".join(f"{k}: {v}" for k, v in checks.items()))
    assert len(rows) >= 11
