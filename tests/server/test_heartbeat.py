"""Tests for server heartbeat / dead-connection cleanup (v0.3, T-2.5)."""
from __future__ import annotations

import asyncio
import socket
import struct
import threading
import time

import pytest

from tinydb.protocol.frame import Frame
from tinydb.protocol.messages import Hello, MessageType, Ping, Pong
from tinydb.server.app import run_server
from tinydb.server.config import ServerConfig


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server_in_thread(config: ServerConfig):
    ready = threading.Event()

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def _main():
            from tinydb.api import Database
            db = Database(config.db_path)
            srv = await run_server(config, db=db, on_ready=ready.set)
            try:
                await asyncio.sleep(15)
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
    from tinydb.server import app as _app
    _app._shutdown_event.set()
    return thread


def _read_exact(sock: socket.socket, n: int) -> bytes:
    sock.settimeout(5.0)
    out = b""
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            raise RuntimeError("EOF")
        out += chunk
    return out


def _read_frame(sock: socket.socket) -> Frame:
    header = _read_exact(sock, 6)
    (length,) = struct.unpack(">I", header[:4])
    payload = _read_exact(sock, length)
    return Frame.from_bytes(header + payload)


class TestHeartbeat:
    """PING/PONG round-trip."""

    def test_ping_returns_pong(self, tmp_path):
        port = _free_port()
        config = ServerConfig(db_path=tmp_path / "x.db", host="127.0.0.1", port=port)
        thread = _start_server_in_thread(config)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
                # HELLO
                sock.sendall(Hello(client="py-1.0").to_frame().to_bytes())
                _ = _read_frame(sock)
                # PING
                sock.sendall(Ping(ts=12345).to_frame().to_bytes())
                resp = _read_frame(sock)
                assert resp.type == MessageType.PONG
                p = Pong.from_frame(resp)
                assert p.ts == 12345
        finally:
            thread.join(timeout=5.0)
