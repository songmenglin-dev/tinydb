"""Server-side connection session (v0.3, T-2.2).

A :class:`ServerSession` is the per-connection coroutine.  It owns
a :class:`FrameReader` for incoming bytes and a list of outgoing
frames (the tests inject a list; the production path uses an
asyncio StreamWriter).
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from tinydb.protocol.codec import FrameReader, FrameWriter
from tinydb.protocol.frame import Frame, ProtocolError
from tinydb.protocol.handshake import perform_server_handshake
from tinydb.protocol.messages import (
    Hello,
    MessageType,
    Ok,
    Ping,
    Pong,
    Quit,
    ResultDone,
    ResultError,
    decode_message,
)
from tinydb.server.handler import dispatch_message


class ServerSession:
    """Per-connection state machine.

    For unit tests the reader is a :class:`FrameReader` and the
    "writer" is a list of frames that accumulates what would be sent
    on the wire.  The production :meth:`serve` coroutine bridges to an
    asyncio StreamWriter.
    """

    def __init__(self, reader: FrameReader, db, *, hello_timeout: float = 5.0) -> None:
        self._reader = reader
        self._db = db
        self._hello_timeout = hello_timeout
        self._handshake_done = False
        self._tx = None  # active TransactionContext or None

    # -- test harness -------------------------------------------------

    async def run_once(self) -> List[Frame]:
        """Process one frame from the reader and return the responses.

        Used by the unit tests.  Returns ``[]`` on EOF.
        """
        frame = self._reader.read_frame()
        if frame is None:
            return []
        return await self._handle_frame(frame)

    async def _handle_frame(self, frame: Frame) -> List[Frame]:
        """Dispatch one frame to the right handler."""
        # PING may arrive before HELLO; reply but mark handshake.
        if frame.type == MessageType.PING:
            ping = Ping.from_frame(frame)
            return [Pong(ts=ping.ts).to_frame()]
        if not self._handshake_done:
            if frame.type != MessageType.HELLO:
                # Per REQ-PROTO-3: refuse pre-HELLO traffic.
                from tinydb.protocol.messages import Err
                return [Err(code="08000", msg="HELLO required").to_frame()]
            try:
                hello = Hello.from_frame(frame)
            except ValueError as e:
                from tinydb.protocol.messages import Err
                return [Err(code="08000", msg=f"HELLO client too long: {e}").to_frame()]
            self._handshake_done = True
            return [perform_server_handshake(hello).to_frame()]
        msg = decode_message(frame)
        if isinstance(msg, Quit):
            # Auto-rollback any in-flight transaction.
            self._auto_rollback()
            return [Ok(version="tinydb-0.3.0").to_frame()]
        if isinstance(msg, Ping):
            return [Pong(ts=msg.ts).to_frame()]
        # Intercept BEGIN/COMMIT/ROLLBACK before dispatch.
        from tinydb.protocol.messages import Exec, Query
        if isinstance(msg, (Query, Exec)):
            sql = msg.sql.strip().upper() if msg.sql else ""
            if sql == "BEGIN":
                return self._handle_begin()
            if sql == "COMMIT":
                return self._handle_commit()
            if sql == "ROLLBACK":
                return self._handle_rollback()
        return await dispatch_message(msg, self._db)

    # -- transaction control ------------------------------------------

    def _handle_begin(self) -> List[Frame]:
        if self._tx is not None:
            return [
                ResultError(
                    code="25000", msg="transaction already active"
                ).to_frame()
            ]
        try:
            self._tx = self._db._txn.begin()
        except Exception as e:
            return [ResultError(code="25000", msg=str(e)).to_frame()]
        return [ResultDone(rowcount=0, last_insert_id=0, status_flags=0x01).to_frame()]

    def _handle_commit(self) -> List[Frame]:
        if self._tx is None:
            return [
                ResultError(code="25000", msg="no active transaction").to_frame()
            ]
        try:
            self._db._txn.commit(self._tx)
        except Exception as e:
            return [ResultError(code="25000", msg=str(e)).to_frame()]
        self._tx = None
        return [ResultDone(rowcount=0, last_insert_id=0, status_flags=0x01).to_frame()]

    def _handle_rollback(self) -> List[Frame]:
        if self._tx is None:
            return [
                ResultError(code="25000", msg="no active transaction").to_frame()
            ]
        try:
            self._db._txn.rollback(self._tx)
        except Exception as e:
            return [ResultError(code="25000", msg=str(e)).to_frame()]
        self._tx = None
        return [ResultDone(rowcount=0, last_insert_id=0, status_flags=0x01).to_frame()]

    def _auto_rollback(self) -> None:
        """Drop any in-flight transaction on disconnect."""
        if self._tx is not None:
            try:
                self._db._txn.rollback(self._tx)
            except Exception:
                pass
            self._tx = None

    # -- production bridge --------------------------------------------

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Drive the session over an asyncio stream pair."""
        frame_reader = FrameReader()
        frame_writer = FrameWriter(writer)
        try:
            while True:
                header = await reader.read(6)
                if not header or len(header) < 6:
                    return
                length = int.from_bytes(header[:4], "big")
                rest = await reader.readexactly(length)
                # feed() returns a frame if the buffered bytes form a
                # complete one; pass it along to the handler.
                f = frame_reader.feed(header + rest)
                if f is None:
                    continue
                responses = await self._handle_frame(f)
                for r in responses:
                    frame_writer.write_frame(r)
                await writer.drain()
                if f.type == MessageType.QUIT:
                    return
        except (asyncio.IncompleteReadError, ConnectionError):
            return
        finally:
            self._auto_rollback()
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


__all__ = ["ServerSession"]
