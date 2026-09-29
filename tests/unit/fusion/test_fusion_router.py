import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from api.main import app
from storage import repository
from datetime import datetime, UTC

client = TestClient(app)

import uuid
def test_get_lot_summary_no_live_recompute():
    # Setup test data
    uid = str(uuid.uuid4())
    lot_id = f"test-lot-no-recompute-{uid}"
    tester_id = f"tester-{uid}"
    repository.save_account(tester_id, "Tester", "operator", "hash")
    repository.save_project(lot_id, lot_id, "PN-1", datetime.now(UTC), tester_id)
    
    raw_data = {"lot_id": lot_id, "part_number": "PN-1", "status": "COMPLETE", "readings": [], "account_id": tester_id}
    
    from contracts import AnalysisResults, RiskAssessment, LotDisposition
    results = AnalysisResults(
        assessments=[
            RiskAssessment(
                component_id="C1",
                lot_id=lot_id,
                verdict="PASS",
                module_a_rank=0.5,
                module_b_rank=0.8,
                worst_parameter="iddq_uA",
                module_a_ran=True,
                module_b_ran=True,
                predicted_168h=5.0,
                actual_168h=5.1,
                explanation_sentence="Explanation here."
            )
        ],
        disposition=LotDisposition(
            lot_id=lot_id,
            status="COMPLETE",
            pda_result=0.0,
            verdict="ACCEPT",
            is_forecast=False
        )
    )
    
    repository.save_analysis_run(lot_id, raw_data, results)
    
    # We patch fusion.pipeline.run_full_pipeline just in case someone imports it or calls it.
    with patch("fusion.pipeline.run_full_pipeline") as mock_run:
        mock_run.side_effect = Exception("Live recompute should not happen")
        
        # First call
        resp1 = client.get(f"/lots/{lot_id}")
        assert resp1.status_code == 200
        
        # Second call
        resp2 = client.get(f"/lots/{lot_id}")
        assert resp2.status_code == 200
        
        # Confirm no recomputation occurred
        assert mock_run.call_count == 0
        
        # Confirm they are identical
        assert resp1.json() == resp2.json()
        
        data = resp1.json()
        assert len(data["assessments"]) == 1
        assert data["assessments"][0]["component_id"] == "C1"
        assert data["assessments"][0]["verdict"] == "PASS"
        assert data["assessments"][0]["module_a_rank"] == 0.5
        assert data["assessments"][0]["module_b_rank"] == 0.8
        assert data["assessments"][0]["worst_parameter"] == "iddq_uA"
        assert data["disposition"]["verdict"] == "ACCEPT"
