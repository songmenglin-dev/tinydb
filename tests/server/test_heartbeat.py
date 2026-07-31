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
    """Spin up ``run_server`` in a background thread and return ``(thread, stop)``.

    ``stop`` is a thread-safe callable that, when invoked, asks the
    server's loop to shut it down.  Crucially this no longer mutates
    module-level state — earlier revisions poked ``app._shutdown_event``
    directly, which contaminated other tests by leaving the event set
    (and bound to the wrong loop) for anyone else who imported it.
    """
    ready = threading.Event()
    loop_holder: dict = {}

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop_holder["loop"] = loop
        async def _main():
            from tinydb.api import Database
            db = Database(config.db_path)
            srv = await run_server(config, db=db, on_ready=ready.set)
            try:
                # Stop is delivered via the loop's call_soon_threadsafe,
                # which sets an Event the coroutine awaits.  The event
                # is local to this runner so it cannot leak across tests.
                stop_event = asyncio.Event()
                loop_holder["stop"] = stop_event
                await stop_event.wait()
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

    def stop():
        loop = loop_holder.get("loop")
        event = loop_holder.get("stop")
        if loop is None or event is None:
            return
        loop.call_soon_threadsafe(event.set)

    return thread, stop


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
        thread, stop = _start_server_in_thread(config)
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
            stop()
            thread.join(timeout=5.0)
