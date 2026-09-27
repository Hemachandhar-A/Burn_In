import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from api.main import app
from storage import repository
from datetime import datetime, UTC

client = TestClient(app)

def test_get_lot_summary_no_live_recompute():
    # Setup test data
    lot_id = "test-lot-no-recompute"
    repository.save_account("tester1", "Tester", "operator", "hash")
    repository.save_project("test-lot-no-recompute", lot_id, "PN-1", datetime.now(UTC), "tester1")
    
    raw_data = {"lot_id": lot_id, "part_number": "PN-1", "status": "COMPLETE", "readings": [], "account_id": "tester1"}
    results_dict = {
        "per_component": {
            "C1": {
                "verdict": "PASS",
                "module_a_ran": True,
                "module_b_ran": True,
                "predicted_168h": 5.0,
                "actual_168h": 5.1,
                "explanation_sentence": "Explanation here."
            }
        },
        "lot_disposition": {
            "status": "COMPLETE",
            "pda_result": 0.0,
            "verdict": "ACCEPT",
            "is_forecast": False
        }
    }
    
    repository.save_analysis_run("test-lot-no-recompute", raw_data, results_dict)
    
    # We patch fusion.pipeline.run_full_pipeline just in case someone imports it or calls it.
    # But wait, we removed the import. So it shouldn't be called.
    # Let's patch it anyway to prove it's NOT called, though it shouldn't even be imported in fusion.router.
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
        assert data["disposition"]["verdict"] == "ACCEPT"
