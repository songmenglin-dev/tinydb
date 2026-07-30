"""End-to-end integration test for the v0.3 Python wire-protocol stack.

Exercises: server boot -> Client connect -> CRUD -> transactions ->
remote CLI invocation.  Each scenario owns its own server thread and
database file under ``tmp_path``.
"""
from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tinydb.api import Database
from tinydb.client.sync import Client
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


class TestEndToEnd:
    """Full stack: server -> client -> SQL -> on-disk."""

    def test_full_lifecycle(self, tmp_path: Path):
        """Create, insert, select, transaction-rollback, quit."""
        port = _free_port()
        db_path = tmp_path / "x.db"
        config = ServerConfig(db_path=db_path, host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            try:
                # CREATE TABLE
                r = c.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
                assert r.rowcount == 0

                # INSERT two rows via EXEC (parameterised)
                r = c.execute(
                    "INSERT INTO t VALUES (?, ?)", [1, "alice"]
                )
                assert r.rowcount == 1
                r = c.execute(
                    "INSERT INTO t VALUES (?, ?)", [2, "bob"]
                )
                assert r.rowcount == 1

                # SELECT
                r = c.execute("SELECT id, name FROM t ORDER BY id")
                assert r.rows == [[1, "alice"], [2, "bob"]]
                assert r.rowcount == 2

                # Transaction rollback
                with pytest.raises(RuntimeError):
                    with c.transaction():
                        c.execute("INSERT INTO t VALUES (?, ?)", [3, "carol"])
                        # Force rollback
                        raise RuntimeError("simulated failure")
                r = c.execute("SELECT COUNT(*) FROM t")
                assert r.rows == [[2]]

                # Transaction commit
                with c.transaction():
                    c.execute("INSERT INTO t VALUES (?, ?)", [4, "dave"])
                r = c.execute("SELECT id FROM t WHERE id = ?", [4])
                assert r.rows == [[4]]

                # PING
                rtt = c.ping()
                assert rtt >= 0.0
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)

        # Reopen the file and confirm durability.
        with Database(str(db_path)) as db2:
            rows = db2.execute("SELECT id, name FROM t ORDER BY id")
            assert rows == [(1, "alice"), (2, "bob"), (4, "dave")]

    def test_cli_against_server(self, tmp_path: Path):
        """`python -m tinydb --uri tinydb://host:port -c <sql>` works."""
        port = _free_port()
        db_path = tmp_path / "x.db"
        config = ServerConfig(db_path=db_path, host="127.0.0.1", port=port)
        # Pre-populate the DB file BEFORE starting the server so the
        # server sees a fresh, committed state on open.
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY)")
            db.execute("INSERT INTO t VALUES (1)")
            db.execute("INSERT INTO t VALUES (2)")
        thread, stop = _start_server(config)
        try:
            env = {"PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
            cp = subprocess.run(
                [
                    sys.executable,
                    "-m", "tinydb",
                    "--uri", f"tinydb://127.0.0.1:{port}",
                    "-c", "SELECT id FROM t ORDER BY id",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=10.0,
            )
            assert cp.returncode == 0, (
                f"stderr={cp.stderr!r}\nstdout={cp.stdout!r}"
            )
            assert "1" in cp.stdout
            assert "2" in cp.stdout
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_concurrent_clients(self, tmp_path: Path):
        """Two clients share the same server safely."""
        port = _free_port()
        db_path = tmp_path / "x.db"
        config = ServerConfig(db_path=db_path, host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c1 = Client("127.0.0.1", port)
            c2 = Client("127.0.0.1", port)
            try:
                c1.execute("CREATE TABLE t (id INT PRIMARY KEY)")
                c1.execute("INSERT INTO t VALUES (1)")
                # c2 sees the row.
                r = c2.execute("SELECT id FROM t")
                assert r.rows == [[1]]
            finally:
                c1.close()
                c2.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)