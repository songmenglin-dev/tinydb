"""Tests for the CLI backend abstraction (T-4.2 + T-4.6)."""
from __future__ import annotations

import asyncio
import socket
import sys
import threading
from pathlib import Path

import pytest

from tinydb.api import Database
from tinydb.cli.backend import Backend, BackendResult, FileBackend, RemoteBackend
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


class TestFileBackend:
    """In-process backend backed by a Database."""

    def test_create_table_returns_ok_result(self, tmp_path: Path):
        backend = FileBackend(Database(str(tmp_path / "x.db")))
        try:
            r = backend.execute("CREATE TABLE t (id INT PRIMARY KEY)")
            assert isinstance(r, BackendResult)
            assert r.is_select is False
            assert r.rowcount == 0
        finally:
            backend.close()

    def test_select_returns_rows(self, tmp_path: Path):
        backend = FileBackend(Database(str(tmp_path / "x.db")))
        try:
            backend.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
            backend.execute("INSERT INTO t VALUES (1, 'a')")
            backend.execute("INSERT INTO t VALUES (2, 'b')")
            r = backend.execute("SELECT id, name FROM t ORDER BY id")
            assert r.is_select is True
            assert r.rows == [(1, "a"), (2, "b")]
            assert r.rowcount == 2
        finally:
            backend.close()

    def test_insert_returns_rowcount(self, tmp_path: Path):
        backend = FileBackend(Database(str(tmp_path / "x.db")))
        try:
            backend.execute("CREATE TABLE t (id INT PRIMARY KEY)")
            r = backend.execute("INSERT INTO t VALUES (42)")
            assert r.rowcount == 1
            assert r.is_select is False
        finally:
            backend.close()

    def test_close_idempotent(self, tmp_path: Path):
        backend = FileBackend(Database(str(tmp_path / "x.db")))
        backend.close()
        backend.close()  # must not raise


class TestRemoteBackend:
    """Backend backed by a remote Client."""

    def test_remote_create_and_select(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            client = Client("127.0.0.1", port)
            backend = RemoteBackend(client)
            try:
                backend.execute("CREATE TABLE t (id INT PRIMARY KEY)")
                r = backend.execute("INSERT INTO t VALUES (7)")
                assert r.rowcount == 1
                r = backend.execute("SELECT id FROM t")
                assert r.is_select is True
                assert r.rows == [(7,)]
            finally:
                backend.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)


# ---------------------------------------------------------------------
# CLI argument tests
# ---------------------------------------------------------------------


class TestCliArgs:
    """Argparse integration: --file vs --uri mutual exclusion."""

    def test_no_args_errors(self):
        from tinydb.cli import main
        with pytest.raises(SystemExit):
            main([])

    def test_file_and_uri_are_mutually_exclusive(self, tmp_path: Path):
        from tinydb.cli import main
        with pytest.raises(SystemExit):
            main([
                "--file", str(tmp_path / "x.db"),
                "--uri", "tinydb://127.0.0.1:1",
            ])

    def test_db_alias_still_works(self, tmp_path: Path):
        from tinydb.cli import main
        rc = main([
            "--db", str(tmp_path / "x.db"),
            "-c", "CREATE TABLE t (id INT PRIMARY KEY)",
        ])
        assert rc == 0

    def test_file_one_shot(self, tmp_path: Path):
        from tinydb.cli import main
        rc = main([
            "--file", str(tmp_path / "x.db"),
            "-c", "CREATE TABLE t (id INT PRIMARY KEY)",
        ])
        assert rc == 0

    def test_uri_connection_failure(self, tmp_path: Path, capsys):
        """Connection refused -> clear error message + non-zero exit."""
        from tinydb.cli import main
        port = _free_port()  # nothing listening
        with pytest.raises(SystemExit) as exc:
            main([
                "--uri", f"tinydb://127.0.0.1:{port}",
                "-c", "SELECT 1",
            ])
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "connect" in err.lower() or "refused" in err.lower() or "127.0.0.1" in err