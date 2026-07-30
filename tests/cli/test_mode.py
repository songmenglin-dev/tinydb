"""Tests for dual-mode CLI (v0.3, T-4.5/T-4.6).

Covers:

* The ``--file`` / ``--uri`` mutual exclusion.
* Running a one-shot SQL via ``-c`` against both modes.
* The Python ``app.run()`` entry point.
"""
from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tinydb.api import Database
from tinydb.cli.app import run as cli_run
from tinydb.server.app import run_server
from tinydb.server.config import ServerConfig


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(config: ServerConfig):
    ready = threading.Event()
    stop = threading.Event()

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def _main():
            db = Database(config.db_path)
            srv = await run_server(config, db=db, on_ready=ready.set)
            try:
                while not stop.is_set():
                    await asyncio.sleep(0.05)
            finally:
                srv.close()
                await srv.wait_closed()
                db.close()
        loop.run_until_complete(_main())
        loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    if not ready.wait(timeout=5.0):
        raise RuntimeError("server failed to start")
    return thread, stop


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------


class TestCliModeDispatch:
    """Argparse + dispatch into embedded vs remote backend."""

    def test_file_mode_one_shot(self, tmp_path: Path):
        db_path = tmp_path / "x.db"
        rc = cli_run([
            "--file", str(db_path),
            "-c", "CREATE TABLE t (id INT PRIMARY KEY)",
        ])
        assert rc == 0

    def test_uri_mode_one_shot(self, tmp_path: Path):
        port = _free_port()
        db_path = tmp_path / "x.db"
        config = ServerConfig(
            db_path=db_path, host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            rc = cli_run([
                "--uri", f"tinydb://127.0.0.1:{port}",
                "-c", "CREATE TABLE t (id INT PRIMARY KEY)",
            ])
            assert rc == 0
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_uri_mode_select(self, tmp_path: Path):
        port = _free_port()
        db_path = tmp_path / "x.db"
        config = ServerConfig(
            db_path=db_path, host="127.0.0.1", port=port
        )
        # Pre-populate.
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY)")
            db.execute("INSERT INTO t VALUES (1)")
            db.execute("INSERT INTO t VALUES (2)")
        thread, stop = _start_server(config)
        try:
            rc = cli_run([
                "--uri", f"tinydb://127.0.0.1:{port}",
                "-c", "SELECT id FROM t ORDER BY id",
            ])
            assert rc == 0
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_file_and_uri_mutually_exclusive(self, tmp_path: Path):
        with pytest.raises(SystemExit):
            cli_run([
                "--file", str(tmp_path / "x.db"),
                "--uri", "tinydb://127.0.0.1:1",
            ])

    def test_no_args_errors(self, tmp_path: Path):
        with pytest.raises(SystemExit):
            cli_run([])


class TestCliSubprocess:
    """End-to-end via ``python -m tinydb``."""

    def test_subprocess_file_mode(self, tmp_path: Path):
        env = {"PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
        cp = subprocess.run(
            [
                sys.executable,
                "-m", "tinydb",
                "--file", str(tmp_path / "x.db"),
                "-c", "CREATE TABLE t (id INT PRIMARY KEY)",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=10.0,
        )
        assert cp.returncode == 0, (
            f"stderr={cp.stderr!r}\nstdout={cp.stdout!r}"
        )