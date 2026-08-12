"""Tests for the asynchronous Python Client (v0.3, T-3.7).

The test functions are synchronous shells that bridge into asyncio via
``asyncio.run`` — we cannot add ``pytest-asyncio`` as a dependency, so
each test creates a fresh event loop, runs the coroutine, and asserts.
"""
from __future__ import annotations

import asyncio
import socket
import threading
from pathlib import Path

import pytest

from tinydb.api import Database
from tinydb.client.async_client import AsyncClient, AsyncResult
from tinydb.server.app import run_server
from tinydb.server.config import ServerConfig


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(config: ServerConfig):
    """Run the asyncio server in a background thread; return stop event."""
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


def _run(coro):
    """Synchronous bridge into asyncio.run()."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------


class TestAsyncConnect:
    """Connect + HELLO handshake."""

    def test_connect_and_hello(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            async def _go():
                c = AsyncClient("127.0.0.1", port)
                await c.connect()
                try:
                    assert c.version == "tinydb-0.3.1"
                finally:
                    await c.close()
            _run(_go())
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_connect_refused(self):
        from tinydb.client.errors import ConnectionError as ClientConnectionError
        port = _free_port()

        async def _go():
            c = AsyncClient("127.0.0.1", port, connect_timeout=0.5)
            await c.connect()

        with pytest.raises(ClientConnectionError):
            _run(_go())


class TestAsyncExecute:
    """Result rows / rowcount / columns."""

    def test_execute_select(self, tmp_path: Path):
        db_path = tmp_path / "x.db"
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
            db.execute("INSERT INTO t VALUES (1, 'a')")
            db.execute("INSERT INTO t VALUES (2, 'b')")
        port = _free_port()
        config = ServerConfig(
            db_path=db_path, host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            async def _go():
                async with AsyncClient("127.0.0.1", port) as c:
                    result = await c.execute(
                        "SELECT id, name FROM t ORDER BY id"
                    )
                    assert isinstance(result, AsyncResult)
                    assert result.rowcount == 2
                    assert result.rows == [[1, "a"], [2, "b"]]
            _run(_go())
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_execute_insert_returns_rowcount(self, tmp_path: Path):
        db_path = tmp_path / "x.db"
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        port = _free_port()
        config = ServerConfig(
            db_path=db_path, host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            async def _go():
                async with AsyncClient("127.0.0.1", port) as c:
                    result = await c.execute("INSERT INTO t VALUES (42)")
                    assert result.rowcount == 1
                    assert result.rows == []
            _run(_go())
        finally:
            stop.set()
            thread.join(timeout=5.0)


class TestAsyncExecuteMany:
    """execute_many."""

    def test_execute_many_returns_total(self, tmp_path: Path):
        db_path = tmp_path / "x.db"
        with Database(str(db_path)) as db:
            db.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
        port = _free_port()
        config = ServerConfig(
            db_path=db_path, host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            async def _go():
                async with AsyncClient("127.0.0.1", port) as c:
                    params_list = [[i, f"n{i}"] for i in range(1, 11)]
                    total = await c.execute_many(
                        "INSERT INTO t VALUES (?, ?)", params_list
                    )
                    assert total == 10
            _run(_go())
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_execute_many_bad_batch_size(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            async def _go():
                async with AsyncClient("127.0.0.1", port) as c:
                    with pytest.raises(ValueError):
                        await c.execute_many(
                            "INSERT INTO t VALUES (1)", [], batch_size=0
                        )
            _run(_go())
        finally:
            stop.set()
            thread.join(timeout=5.0)


class TestAsyncPingClose:
    """PING latency and close idempotency."""

    def test_ping_returns_rtt(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            async def _go():
                async with AsyncClient("127.0.0.1", port) as c:
                    rtt = await c.ping()
                    assert isinstance(rtt, float)
                    assert rtt >= 0.0
            _run(_go())
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_close_is_idempotent(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            async def _go():
                c = AsyncClient("127.0.0.1", port)
                await c.connect()
                await c.close()
                await c.close()  # must not raise
            _run(_go())
        finally:
            stop.set()
            thread.join(timeout=5.0)