"""End-to-end test for examples/demo.py.

Spawns the demo as a subprocess, asserts exit code 0 and key output
substring presence.  This is the only test that exercises
``examples/demo.py`` end-to-end (T-9.3 gate).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = REPO_ROOT / "examples" / "demo.py"


def test_demo_exits_cleanly():
    """examples/demo.py exits 0 when run as a subprocess."""
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"demo exited {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )


def test_demo_output_mentions_v0_1():
    """The demo's banner announces the version — make sure it shows."""
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert "tinydb v0.1 demo" in proc.stdout


def test_demo_runs_all_ten_steps():
    """Each of the 10 numbered steps emits its own banner line."""
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    out = proc.stdout
    # Steps 2..10 each emit "--- step N: ...".  Step 1 is the open/banner.
    for n in range(2, 11):
        assert f"step {n}" in out, f"missing banner for step {n}"