"""Tests for the tinydb-server CLI entry point (v0.3, T-2.6)."""
from __future__ import annotations

import subprocess
import sys

import pytest


class TestCli:
    """Invoke the server CLI as a subprocess."""

    def test_cli_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "tinydb.server", "--help"],
            capture_output=True, text=True, timeout=10,
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0
        assert "tinydb-server" in result.stdout
        assert "--db-path" in result.stdout
        assert "--port" in result.stdout
