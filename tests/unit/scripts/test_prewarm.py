"""scripts/prewarm.py: runs clean, prints every step, and never touches the database."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_prewarm_exits_zero_and_prints_steps(tmp_path):
    db = tmp_path / "prewarm.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db.as_posix()}", "PYTHONPATH": str(ROOT)}
    proc = subprocess.run([sys.executable, "-m", "scripts.prewarm"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    for step in ("import shap / lightgbm / mapie", "module_b synthetic_models", "one in-memory pipeline run", "total"):
        assert step in proc.stdout
    assert not db.exists(), "prewarm must not write to the database"
