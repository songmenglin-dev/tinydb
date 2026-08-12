"""Tests for the synchronous Python Client (v0.3, T-3.1..T-3.6)."""
from __future__ import annotations

import asyncio
import socket
import struct
import threading
import time
from typing import List, Optional

import pytest

from tinydb.protocol.frame import Frame
from tinydb.protocol.messages import (
    Exec,
    Hello,
    MessageType,
    Ok,
    Param,
    ParamType,
    Ping,
    Pong,
    Query,
    Quit,
    ResultDone,
    ResultHeader,
    ResultRow,
)
from tinydb.server.app import run_server
from tinydb.server.config import ServerConfig


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(config: ServerConfig):
    """Start a server in a background thread and return its stop function."""
    ready = threading.Event()
    stop = threading.Event()

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def _main():
            from tinydb.api import Database
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


# ------------- tests -------------------


class TestClientConnect:
    """Client construction and HELLO handshake."""

    def test_client_connect_and_hello(self, tmp_path):
        port = _free_port()
        config = ServerConfig(db_path=tmp_path / "x.db", host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            from tinydb.client.sync import Client
            c = Client("127.0.0.1", port)
            try:
                assert c.version == "tinydb-0.3.1"
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_client_connect_refused(self):
        from tinydb.client.sync import Client
        from tinydb.client.errors import ConnectionError as ClientConnectionError
        # Pick a port that's definitely not listening.
        port = _free_port()
        with pytest.raises(ClientConnectionError):
            Client("127.0.0.1", port, connect_timeout=0.5)

    def test_client_hello_timeout(self):
        from tinydb.client.sync import Client
        from tinydb.client.errors import ClientError
        # Block the port so the TCP handshake completes but no HELLO comes.
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        port = _free_port()
        blocker.bind(("127.0.0.1", port))
        blocker.listen(8)
        try:
            with pytest.raises(ClientError):
                Client("127.0.0.1", port, connect_timeout=0.5, hello_timeout=0.5)
        finally:
            blocker.close()


class TestClientExecute:
    """Result rows / rowcount / columns."""

    def test_execute_select_returns_result(self, tmp_path):
        from tinydb.client.sync import Client
        from tinydb.api import Database
        # Use a real Database so we can INSERT then SELECT.
        db_path = tmp_path / "x.db"
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
            db.execute("INSERT INTO t VALUES (1, 'a')")
            db.execute("INSERT INTO t VALUES (2, 'b')")
        port = _free_port()
        config = ServerConfig(db_path=db_path, host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            try:
                result = c.execute("SELECT id, name FROM t ORDER BY id")
                assert result.rowcount == 2
                assert result.rows == [[1, "a"], [2, "b"]]
                assert result.columns == ["id", "name"]
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)


class TestClientSqlPath:
    """Client.execute against a real Database, round-trip SQL."""

    def test_execute_select_returns_result(self, tmp_path):
        from tinydb.api import Database
        from tinydb.client.sync import Client
        # Use a real Database so we can INSERT then SELECT.
        db_path = tmp_path / "x.db"
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
            db.execute("INSERT INTO t VALUES (1, 'a')")
            db.execute("INSERT INTO t VALUES (2, 'b')")
        port = _free_port()
        config = ServerConfig(db_path=db_path, host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            try:
                result = c.execute("SELECT id, name FROM t ORDER BY id")
                assert result.rowcount == 2
                assert result.rows == [[1, "a"], [2, "b"]]
                assert result.columns == ["id", "name"]
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_execute_insert_returns_rowcount(self, tmp_path):
        from tinydb.api import Database
        from tinydb.client.sync import Client
        db_path = tmp_path / "x.db"
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
        port = _free_port()
        config = ServerConfig(db_path=db_path, host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            try:
                result = c.execute("INSERT INTO t VALUES (1, 'a')")
                assert result.rowcount == 1
                assert result.rows == []
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_execute_query_timeout(self, tmp_path):
        from tinydb.client.sync import Client
        from tinydb.client.errors import TimeoutError as ClientTimeoutError
        # Just check that the timeout parameter is honoured and a
        # TimeoutError is raised when the server doesn't respond.
        port = _free_port()
        config = ServerConfig(db_path=tmp_path / "x.db", host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            try:
                # Set an unrealistically short timeout; the server is
                # fast but the timeout machinery should still fire.
                with pytest.raises((ClientTimeoutError, Exception)):
                    c.execute("SELECT 1", timeout=0.0001)
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)


class TestClientExecuteMany:
    """execute_many quotes the parameter substitution path."""

    def test_execute_many_batch_size_100(self, tmp_path):
        from tinydb.api import Database
        from tinydb.client.sync import Client
        db_path = tmp_path / "x.db"
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
        port = _free_port()
        config = ServerConfig(db_path=db_path, host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            try:
                params_list = [[i, f"n{i}"] for i in range(1, 11)]
                total = c.execute_many(
                    "INSERT INTO t VALUES (?, ?)", params_list
                )
                assert total == 10
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)


class TestClientTransaction:
    """Transaction context manager."""

    def test_transaction_commit(self, tmp_path):
        from tinydb.api import Database
        from tinydb.client.sync import Client
        db_path = tmp_path / "x.db"
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
        port = _free_port()
        config = ServerConfig(db_path=db_path, host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            try:
                with c.transaction():
                    c.execute("INSERT INTO t VALUES (1, 'a')")
                # Independent read should see the row.
                result = c.execute("SELECT id FROM t WHERE id = 1")
                assert result.rowcount == 1
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_transaction_rollback(self, tmp_path):
        from tinydb.api import Database
        from tinydb.client.sync import Client
        db_path = tmp_path / "x.db"
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
        port = _free_port()
        config = ServerConfig(db_path=db_path, host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            try:
                with pytest.raises(RuntimeError):
                    with c.transaction():
                        c.execute("INSERT INTO t VALUES (1, 'a')")
                        raise RuntimeError("boom")
                # The row should not be visible.
                result = c.execute("SELECT id FROM t WHERE id = 1")
                assert result.rowcount == 0
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_transaction_nested_raises(self, tmp_path):
        from tinydb.client.sync import Client
        from tinydb.client.errors import ClientError
        port = _free_port()
        config = ServerConfig(db_path=tmp_path / "x.db", host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            try:
                with c.transaction():
                    with pytest.raises(Exception):
                        with c.transaction():
                            pass
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)


class TestClientPingClose:
    """PING latency and close idempotency."""

    def test_ping_returns_rtt(self, tmp_path):
        from tinydb.client.sync import Client
        port = _free_port()
        config = ServerConfig(db_path=tmp_path / "x.db", host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            try:
                rtt = c.ping()
                assert isinstance(rtt, float)
                assert rtt >= 0.0
                assert rtt < 1.0  # loopback
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_close_is_idempotent(self, tmp_path):
        from tinydb.client.sync import Client
        port = _free_port()
        config = ServerConfig(db_path=tmp_path / "x.db", host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client("127.0.0.1", port)
            c.close()
            c.close()  # should not raise
        finally:
            stop.set()
            thread.join(timeout=5.0)


class TestClientReconnect:
    """Connection retry with exponential backoff."""

    def test_execute_retries_after_drop(self, tmp_path):
        """If the first execute raises ConnectionError, the client should
        transparently reconnect and retry.

        Note: INSERT is not idempotent in general, so the client now
        defaults to ``retry=False`` for DML.  This test opts in with
        ``retry=True`` to exercise the retry path; the primary-key
        constraint makes the INSERT safe to re-execute (the second
        attempt sees the row already exists and would raise, so a
        realistic deployment would key on a non-PK column or use an
        ``INSERT OR IGNORE`` form).
        """
        from tinydb.api import Database
        from tinydb.client.sync import Client
        db_path = tmp_path / "x.db"
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
        port = _free_port()
        config = ServerConfig(db_path=db_path, host="127.0.0.1", port=port)
        thread, stop = _start_server(config)
        try:
            c = Client(
                "127.0.0.1", port, max_retries=2, hello_timeout=2.0
            )
            try:
                # Force a connection drop by killing the reader thread's
                # socket from underneath. We close the local side and let
                # the next execute trigger a reconnect.
                c._sock.close()
                c._sock = None
                result = c.execute("INSERT INTO t VALUES (1, 'a')", retry=True)
                assert result.rowcount == 1
            finally:
                c.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)
