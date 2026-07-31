"""Tests for the asyncio TCP server main loop (v0.3, T-2.4)."""
from __future__ import annotations

import asyncio
import socket
import struct
import threading
import time

import pytest

from tinydb.protocol.codec import FrameReader, FrameWriter
from tinydb.protocol.frame import Frame
from tinydb.protocol.messages import (
    Hello,
    MessageType,
    Ok,
    Ping,
    Pong,
    Query,
    Quit,
)
from tinydb.server.app import run_server
from tinydb.server.config import ServerConfig


def _free_port() -> int:
    """Return a port that is currently free (best-effort)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _BlockingDB:
    """Simple stand-in for tinydb.api.Database."""

    def __init__(self) -> None:
        self.calls: list = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return [(1,)]


def _start_server_in_thread(config: ServerConfig) -> tuple:
    """Start ``run_server`` in a background thread.

    Returns ``(thread, stop)`` where ``stop`` is a thread-safe callable
    that asks the server's loop to close the listening socket and
    shut down.  We deliberately do NOT touch module-level state — the
    earlier ``_app._shutdown_event.set()`` pattern leaked between
    tests because the event was bound to whatever loop happened to be
    current at import time.
    """
    ready = threading.Event()
    loop_holder: dict = {}

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop_holder["loop"] = loop
        server_holder: dict = {}

        async def _main():
            server = await run_server(config, on_ready=ready.set)
            server_holder["server"] = server
            await server.serve_forever()
        try:
            loop.run_until_complete(_main())
        finally:
            loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    if not ready.wait(timeout=5.0):
        raise RuntimeError("server failed to start")

    def stop():
        loop = loop_holder.get("loop")
        server = loop_holder.get("server_holder", {})
        # ``server_holder`` is a local in _runner; recover by reaching
        # for the asyncio server object we stashed on the loop's debug
        # name attribute via run_server.  Simpler: ask the loop to
        # close every active asyncio.Server it owns.
        if loop is None:
            return
        def _shutdown():
            for srv in list(getattr(loop, "_servers", {}).values()):
                srv.close()
        loop.call_soon_threadsafe(_shutdown)

    return thread, stop


def _read_one_frame(sock: socket.socket, fr: FrameReader):
    """Read exactly one frame from ``sock`` into ``fr``."""
    sock.settimeout(2.0)
    header = b""
    while len(header) < 6:
        chunk = sock.recv(6 - len(header))
        if not chunk:
            raise RuntimeError("EOF while reading header")
        header += chunk
    (length,) = struct.unpack(">I", header[:4])
    rest = b""
    while len(rest) < length:
        chunk = sock.recv(length - len(rest))
        if not chunk:
            raise RuntimeError("EOF while reading payload")
        rest += chunk
    return fr.feed(header + rest)


def _do_handshake(sock: socket.socket) -> None:
    """Send HELLO and read OK."""
    fw = FrameWriter(_SocketWriter(sock))
    fr = FrameReader()
    fw.write_frame(Hello(client="py-1.0").to_frame())
    fw.flush()
    resp = _read_one_frame(sock, fr)
    assert resp is not None
    assert resp.type == MessageType.OK


class _SocketWriter:
    """Minimal stream wrapper exposing ``write(bytes)``."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def write(self, data: bytes) -> None:
        self._sock.sendall(data)

    def flush(self) -> None:
        pass


class _SocketReader:
    """Minimal stream wrapper exposing ``read(n)``."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def read(self, n: int) -> bytes:
        try:
            return self._sock.recv(n)
        except OSError:
            return b""

    def read1(self, n: int) -> bytes:
        # recv(1) is the canonical "read one byte".
        try:
            return self._sock.recv(1)
        except OSError:
            return b""


class TestServerLifecycle:
    """Test that the server binds, accepts, and shuts down."""

    def test_run_server_binds_and_accepts(self, tmp_path):
        port = _free_port()
        config = ServerConfig(db_path=tmp_path / "x.db", host="127.0.0.1", port=port)
        db = _BlockingDB()
        thread, stop = _start_server_in_thread(config)
        try:
            # Connect to the server.
            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
                _do_handshake(sock)
                # Send a PING, expect PONG.
                fw = FrameWriter(_SocketWriter(sock))
                fr = FrameReader()
                fw.write_frame(Ping(ts=42).to_frame())
                fw.flush()
                resp = _read_one_frame(sock, fr)
                assert resp is not None
                assert resp.type == MessageType.PONG
                # QUIT
                fw.write_frame(Quit().to_frame())
                fw.flush()
                resp = _read_one_frame(sock, fr)
                assert resp is not None
                assert resp.type == MessageType.OK
        finally:
            stop()
            thread.join(timeout=5.0)

    def test_run_server_bind_error(self, tmp_path):
        # Bind a port, then try to start the server on the same port.
        port = _free_port()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            blocker.bind(("127.0.0.1", port))
            blocker.listen(8)
            config = ServerConfig(db_path=tmp_path / "x.db", host="127.0.0.1", port=port)
            from tinydb.server import app as _app
            with pytest.raises(OSError):
                _run_sync(run_server(config))
        finally:
            blocker.close()


def _run_sync(coro):
    """Run an async coroutine in a fresh event loop and return its result."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
