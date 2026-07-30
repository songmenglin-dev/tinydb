"""Tests for the synchronous Client connection pool (v0.3, T-3.8)."""
from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path

import pytest

from tinydb.api import Database
from tinydb.client.pool import Pool
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


class TestPoolBasics:
    """Acquire / release cycle."""

    def test_acquire_returns_client(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            with Pool("127.0.0.1", port, max_size=2) as pool:
                c = pool.acquire(timeout=2.0)
                try:
                    assert c is not None
                finally:
                    pool.release(c)
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_acquire_reuses_released(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            with Pool("127.0.0.1", port, max_size=2) as pool:
                c1 = pool.acquire(timeout=2.0)
                pool.release(c1)
                c2 = pool.acquire(timeout=2.0)
                try:
                    assert c2 is c1  # recycled
                finally:
                    pool.release(c2)
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_max_size_enforced(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            pool = Pool("127.0.0.1", port, max_size=1)
            try:
                c1 = pool.acquire(timeout=2.0)
                # Try to acquire a 2nd with a short timeout: must fail.
                with pytest.raises(Exception):
                    pool.acquire(timeout=0.2)
                pool.release(c1)
                # After release, acquire works.
                c2 = pool.acquire(timeout=2.0)
                pool.release(c2)
            finally:
                pool.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)


class TestPoolContext:
    """``with pool.connection()`` semantics."""

    def test_connection_context_executes_sql(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            with Pool("127.0.0.1", port, max_size=2) as pool:
                with pool.connection() as c:
                    c.execute("CREATE TABLE t (id INT PRIMARY KEY)")
                    result = c.execute("INSERT INTO t VALUES (1)")
                    assert result.rowcount == 1
        finally:
            stop.set()
            thread.join(timeout=5.0)

    def test_connection_context_drops_client_on_exception(self, tmp_path: Path):
        """If the user code raises, the client should NOT be recycled."""
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            pool = Pool("127.0.0.1", port, max_size=2)
            try:
                with pytest.raises(RuntimeError):
                    with pool.connection() as c:
                        # Force-close under the hood to mimic a broken
                        # connection so the drop path is exercised.
                        c._sock.close()
                        c._sock = None
                        raise RuntimeError("simulated failure")
                # After the exception the client is gone: we can still
                # acquire a fresh one (because max_size allows it).
                c2 = pool.acquire(timeout=2.0)
                pool.release(c2)
            finally:
                pool.close()
        finally:
            stop.set()
            thread.join(timeout=5.0)


class TestPoolClose:
    """close() shuts down all clients."""

    def test_close_then_acquire_raises(self, tmp_path: Path):
        port = _free_port()
        config = ServerConfig(
            db_path=tmp_path / "x.db", host="127.0.0.1", port=port
        )
        thread, stop = _start_server(config)
        try:
            pool = Pool("127.0.0.1", port, max_size=2)
            pool.close()
            with pytest.raises(RuntimeError):
                pool.acquire(timeout=0.1)
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
            pool = Pool("127.0.0.1", port, max_size=2)
            pool.close()
            pool.close()  # must not raise
        finally:
            stop.set()
            thread.join(timeout=5.0)