"""scripts/evaluate.py: --help exits 0; rendering is a pure formatter over harness tables (no E5 logic here)."""
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from scripts.evaluate import render

ROOT = Path(__file__).resolve().parents[3]


def test_help_exits_zero():
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.run([sys.executable, "-m", "scripts.evaluate", "--help"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    assert "--format" in proc.stdout


def test_render_formats_preserve_values():
    tables = {"headline": pd.DataFrame([{"method": "module_a_review", "recall": 0.841}])}
    assert "0.841" in render(tables, "table")
    assert '"recall": 0.841' in render(tables, "json")
    md = render(tables, "markdown")
    assert md.startswith("## headline") and "| module_a_review | 0.841 |" in md
