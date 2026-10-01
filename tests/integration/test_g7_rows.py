"""G7 gate (Session 7a, Lead as verifier): IMPLEMENTATION_PLAN.md Part 7.3 rows that the existing suites cover only
at unit level or not at all, exercised cheaply through the real app (`api.main.app`, every router registered, one
isolated DB, the committed live demo CSVs). Part 7.4: this file is new; no existing test file is edited.

  * route-level checkpoint rules  - missing 96h is allowed and flagged, a missing 24h is INSUFFICIENT_DATA
  * determinism through the route - the same CSV into two lots gives the same verdict and PDA (rule 9)
  * wide-format CSV through POST /lots, and a lot_id no later route can address - both are documented OPEN gaps
    (BLOCKERS.md 2026-09-26 P1) and are pinned here as strict xfail so that fixing them turns the test green
  * frontend rule 14 - no raw fetch outside the generated-client wrapper, no `any` in the typed API layer
  * no route carries a stub - the OpenAPI paths are all real, authenticated routers
"""
import csv
import io
import re
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo_data"
META = {"part_number": "DEMO-PN", "manufacturer": "Northvale Semiconductor", "date_code": "2603",
        "account_id": "a.sharma"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from ingestion import store
    from storage import database, repository

    engine = create_engine(f"sqlite:///{tmp_path / 'g7.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(repository, "SessionLocal", session_local)
    repository.init_db()
    store.clear()
    repository.save_account("a.sharma", "A. Sharma", "Quality Engineer", PasswordHasher().hash("1234"))

    from api.main import app

    c = TestClient(app)
    token = c.post("/auth/login", json={"account_id": "a.sharma", "pin": "1234"}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"
    yield c
    store.clear()


def _upload(client, lot_id: str, data: bytes, name: str = "lot.csv"):
    return client.post("/lots", files={"file": (name, data, "text/csv")}, data={"lot_id": lot_id, **META})


def _live_0h_24h() -> bytes:
    return (DEMO / "live_0h_24h.csv").read_bytes()


def test_missing_96h_is_allowed_and_flagged_not_an_error(client):
    r = _upload(client, "G7-NO96", _live_0h_24h())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "IN_PROGRESS"
    flags = client.get("/lots/G7-NO96/quality").json()
    assert any("96" in str(f) for f in flags), flags  # a missing-96h flag exists, and the upload still succeeded


def test_missing_24h_for_one_component_is_insufficient_data_not_a_guess(client):
    rows = list(csv.reader(io.StringIO(_live_0h_24h().decode())))
    header, body = rows[0], rows[1:]
    victim = body[0][0]
    kept = [r for r in body if not (r[0] == victim and float(r[2]) >= 12)]  # drop that part's 24h readings
    buf = io.StringIO()
    csv.writer(buf).writerows([header, *kept])
    r = _upload(client, "G7-NO24", buf.getvalue().encode())
    assert r.status_code == 200, r.text
    assert victim in r.json()["insufficient_data_components"]
    summary = client.get("/lots/G7-NO24").json()
    assert victim not in {a["component_id"] for a in summary["assessments"]}, "no forecast may be invented for it"


def test_same_csv_into_two_lots_gives_the_same_verdict_and_pda(client):
    for lot in ("G7-DET-A", "G7-DET-B"):
        assert _upload(client, lot, _live_0h_24h()).status_code == 200
    a, b = (client.get(f"/lots/{lot}").json() for lot in ("G7-DET-A", "G7-DET-B"))
    assert a["disposition"]["verdict"] == b["disposition"]["verdict"]
    assert a["disposition"]["pda_result"] == b["disposition"]["pda_result"]
    ranks = lambda s: sorted((x["component_id"].split("-", 2)[-1], x["module_b_rank"]) for x in s["assessments"])  # noqa: E731
    assert ranks(a) == ranks(b)


def _wide_csv() -> bytes:
    long_rows = list(csv.DictReader(io.StringIO(_live_0h_24h().decode())))
    wide: dict[tuple[str, str], dict[str, str]] = {}
    for r in long_rows:
        wide.setdefault((r["component_id"], r["checkpoint_hour"]), {})[f"{r['parameter']}_{r['unit']}"] = r["value"]
    cols = sorted({c for v in wide.values() for c in v})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["component_id", "checkpoint_hour", *cols])
    for (cid, hour), vals in wide.items():
        w.writerow([cid, hour, *[vals.get(c, "") for c in cols]])
    return buf.getvalue().encode()


@pytest.mark.xfail(strict=True, reason="BLOCKERS.md 2026-09-26 P1: POST /lots never calls parse_wide_lot_csv "
                                       "(the pinned E7 step 1 layout is rejected with 422)")
def test_wide_format_csv_is_accepted_through_the_route_and_equals_long(client):
    assert _upload(client, "G7-LONG", _live_0h_24h()).status_code == 200
    wide = _upload(client, "G7-WIDE", _wide_csv())
    assert wide.status_code == 200, wide.text
    a, b = (client.get(f"/lots/{lot}").json() for lot in ("G7-LONG", "G7-WIDE"))
    assert a["disposition"]["pda_result"] == b["disposition"]["pda_result"]


@pytest.mark.xfail(strict=True, reason="BLOCKERS.md 2026-09-26 P1: POST /lots accepts lot ids that no later route "
                                       "can address (the server should answer 422)")
@pytest.mark.parametrize("lot_id", ["A/B", ".."])
def test_unaddressable_lot_ids_are_refused_by_the_server(client, lot_id):
    assert _upload(client, lot_id, _live_0h_24h()).status_code == 422


def test_get_on_a_post_only_api_path_is_404_not_405(client):
    # Disclosed (docs/DISCLOSURES.md #16): the SPA is mounted at "/", so a GET to a POST-only path falls through to
    # the static mount and answers 404 (the mount itself answers 405 to non-GET methods). Pinned, not endorsed.
    assert client.get("/auth/login").status_code == 404
    assert client.delete("/health").status_code == 405


def test_frontend_has_no_raw_fetch_and_no_any_in_the_typed_api_layer():  # Part 7.3 Frontend row, rule 14
    api = ROOT / "frontend" / "src" / "api"
    offenders = []
    for path in api.glob("*.ts"):
        if path.name.endswith((".test.ts", ".d.ts")) or path.name == "schema.d.ts":
            continue
        text = path.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            code = line.split("//")[0]
            if code.lstrip().startswith(("*", "/*")):
                continue  # a JSDoc line, not code
            if re.search(r"(?<![\w.])fetch\(", code) and path.name != "client.ts":
                offenders.append(f"{path.name}:{n}: raw fetch: {line.strip()}")
            if re.search(r":\s*any\b|\bas any\b|<any>", code):
                offenders.append(f"{path.name}:{n}: any: {line.strip()}")
    outside = []
    for path in (ROOT / "frontend" / "src").rglob("*.ts*"):
        if "api" in path.parts or path.name.endswith((".test.ts", ".test.tsx")):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"(?<![\w.])fetch\(", line.split("//")[0]) and not line.lstrip().startswith(("*", "/*")):
                outside.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders and not outside, offenders + outside


def test_every_registered_route_is_real_and_authenticated_except_health_and_login(client):
    schema = client.get("/openapi.json").json()
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            text = (op.get("summary", "") + op.get("description", "") + op.get("operationId", "")).lower()
            assert "stub" not in text and "temp_" not in text, (path, method)
    # a route may declare auth at app level; verify behaviourally instead of trusting the schema alone
    anon = TestClient(client.app)
    for path, ops in schema["paths"].items():
        if "get" in ops and "{" not in path and path not in ("/health", "/openapi.json"):
            assert anon.get(path).status_code == 401, path
