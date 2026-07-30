"""Tests for the server-aware meta commands (v0.3, T-4.7).

Exercises ``.connect`` / ``.disconnect`` / ``.status`` / ``.server-info``
through the REPL's combined meta-dispatch layer.
"""
from __future__ import annotations

import asyncio
import socket
import threading
from pathlib import Path
from typing import List

import pytest

from tinydb.api import Database
from tinydb.cli.backend import FileBackend
from tinydb.cli.commands import (
    ConnectionState,
    cmd_connect,
    cmd_disconnect,
    cmd_server_info,
    cmd_status,
    dispatch_server_meta,
)
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


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------


class TestStatusCommand:
    """.status reports the current backend."""

    def test_status_file_mode(self, tmp_path: Path):
        db = Database(str(tmp_path / "x.db"))
        state = ConnectionState(FileBackend(db))
        try:
            out: List[str] = []
            r = cmd_status(state, "", out.append)
            assert r == "handled"
            assert "mode: file" in out[0]
        finally:
            db.close()


class TestConnectDisconnect:
    """.connect and .disconnect swap the backend."""

    def test_connect_then_status(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            db = Database(str(tmp_path / "x.db"))
            state = ConnectionState(FileBackend(db))
            try:
                out: List[str] = []
                cmd_connect(state, f"tinydb://127.0.0.1:{port}", out.append)
                assert any("Connected" in line for line in out)
                # After connect, status reports remote mode.
                out2: List[str] = []
                cmd_status(state, "", out2.append)
                assert "mode: remote" in out2[0]
            finally:
                try:
                    cmd_disconnect(state, "", lambda _line: None)
                except Exception:
                    pass
                db.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_connect_refused(self):
        port = _free_port()
        state = ConnectionState(FileBackend(Database(":memory:")))
        out: List[str] = []
        r = cmd_connect(
            state, f"tinydb://127.0.0.1:{port}", out.append
        )
        assert r == "handled"
        assert any("Error" in line for line in out)

    def test_disconnect_in_file_mode(self, tmp_path: Path):
        db = Database(str(tmp_path / "x.db"))
        state = ConnectionState(FileBackend(db))
        try:
            out: List[str] = []
            r = cmd_disconnect(state, "", out.append)
            assert r == "handled"
            assert "Not connected" in out[0]
        finally:
            db.close()

    def test_connect_disconnect_cycle(self, tmp_path: Path):
        """After a .connect then .disconnect the state should be clean."""
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            db = Database(str(tmp_path / "x.db"))
            state = ConnectionState(FileBackend(db))
            try:
                cmd_connect(
                    state, f"tinydb://127.0.0.1:{port}", lambda _l: None
                )
                out: List[str] = []
                r = cmd_disconnect(state, "", out.append)
                assert r == "handled"
                assert "Disconnected" in out[0]
                # Status reports disconnected mode.
                out2: List[str] = []
                cmd_status(state, "", out2.append)
                assert "disconnected" in out2[0]
                # A second disconnect says "already disconnected".
                out3: List[str] = []
                cmd_disconnect(state, "", out3.append)
                assert "Already disconnected" in out3[0]
            finally:
                db.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)


class TestServerInfo:
    """.server-info against a live server."""

    def test_server_info_remote(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            db = Database(str(tmp_path / "x.db"))
            state = ConnectionState(FileBackend(db))
            try:
                cmd_connect(
                    state, f"tinydb://127.0.0.1:{port}", lambda _line: None
                )
                out: List[str] = []
                r = cmd_server_info(state, "", out.append)
                assert r == "handled"
                # Expect at least the version and the rtt row.
                joined = "\n".join(out)
                assert "version" in joined
                assert "rtt" in joined
            finally:
                try:
                    cmd_disconnect(state, "", lambda _line: None)
                except Exception:
                    pass
                db.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_server_info_in_file_mode(self, tmp_path: Path):
        db = Database(str(tmp_path / "x.db"))
        state = ConnectionState(FileBackend(db))
        try:
            out: List[str] = []
            r = cmd_server_info(state, "", out.append)
            assert r == "handled"
            assert "Not connected" in out[0]
        finally:
            db.close()


class TestDispatchServerMeta:
    """The dispatcher returns None for non-server meta commands."""

    def test_dispatch_unknown_returns_none(self, tmp_path: Path):
        db = Database(str(tmp_path / "x.db"))
        state = ConnectionState(FileBackend(db))
        try:
            r = dispatch_server_meta(".tables", state, lambda _line: None)
            # .tables is not ours; the regular dispatcher handles it.
            assert r is None
        finally:
            db.close()

    def test_dispatch_exit_returns_exit(self, tmp_path: Path):
        db = Database(str(tmp_path / "x.db"))
        state = ConnectionState(FileBackend(db))
        try:
            r = dispatch_server_meta(".exit", state, lambda _line: None)
            assert r == "exit"
        finally:
            db.close()

    def test_dispatch_help_returns_handled(self, tmp_path: Path):
        db = Database(str(tmp_path / "x.db"))
        state = ConnectionState(FileBackend(db))
        try:
            r = dispatch_server_meta(".help", state, lambda _line: None)
            assert r == "handled"
        finally:
            db.close()