"""scripts/demo.py: exits 0 and prints the summary, with no database writes."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_demo_exits_zero_and_prints_summary(tmp_path):
    db = tmp_path / "demo.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db.as_posix()}", "PYTHONPATH": str(ROOT)}
    proc = subprocess.run([sys.executable, "-m", "scripts.demo"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    for token in ("lot verdict:", "PDA:", "flagged parts:", "seconds taken:"):
        assert token in proc.stdout
    assert not db.exists()
