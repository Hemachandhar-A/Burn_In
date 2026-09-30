"""dev.sh / build_demo.sh: --dry-run prints the commands and exits 0 without running anything."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def _dry(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, f"scripts/{script}", "--dry-run", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)


def test_dev_dry_run_uses_strict_port():
    proc = _dry("dev.sh")
    assert proc.returncode == 0, proc.stderr
    assert "--strictPort" in proc.stdout and "--port 5173" in proc.stdout
    assert "uvicorn api.main:app --reload" in proc.stdout


def test_build_demo_dry_run_steps_and_flags():
    proc = _dry("build_demo.sh")
    assert proc.returncode == 0, proc.stderr
    assert "scripts.seed" in proc.stdout and "npm ci && npm run build" in proc.stdout
    assert "scripts.prewarm" in proc.stdout and "--reload" not in proc.stdout
    assert "scripts.load_demo_lots" in proc.stdout and "WARNING" not in proc.stderr
    assert "scripts.load_demo_lots" not in _dry("build_demo.sh", "--no-demo-lots").stdout
    skip = _dry("build_demo.sh", "--no-reseed", "--port", "9000")
    assert "scripts.seed" not in skip.stdout and "--port 9000" in skip.stdout
