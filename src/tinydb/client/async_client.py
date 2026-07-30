"""Asynchronous Python Client (v0.3, T-3.7).

The :class:`AsyncClient` mirrors :class:`tinydb.client.sync.Client`
exactly except that all I/O happens through ``asyncio.open_connection``.
There is one TCP connection per instance — no extra reader thread — and
incoming frames are decoded by :class:`FrameReader.feed`.

The async client intentionally does NOT use the response-queue model
that the sync client relies on: with asyncio a single ``StreamReader``
already serialises reads, so we just ``await`` for the next complete
frame and add it to a local ``_Response`` collector.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, List, Optional

from tinydb.client.errors import (
    ConnectionError as ClientConnectionError,
    IntegrityError,
    ProtocolError,
    TimeoutError as ClientTimeoutError,
)
from tinydb.protocol.codec import FrameReader, FrameWriter
from tinydb.protocol.frame import Frame, ProtocolError as WireProtocolError
from tinydb.protocol.handshake import perform_client_handshake
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
    ResultError,
    ResultHeader,
    ResultRow,
)


class AsyncResult:
    """The result of an :meth:`AsyncClient.execute` call."""

    def __init__(
        self,
        rows: Optional[List[list]] = None,
        rowcount: int = 0,
        columns: Optional[List[str]] = None,
        last_insert_id: int = 0,
    ) -> None:
        self.rows = rows or []
        self.rowcount = rowcount
        self.columns = columns or []
        self.last_insert_id = last_insert_id

    def __repr__(self) -> str:
        return (
            f"AsyncResult(rows={self.rows!r}, rowcount={self.rowcount}, "
            f"columns={self.columns!r}, last_insert_id={self.last_insert_id})"
        )


class _AsyncResponse:
    """Internal: collect frames until the response is complete."""

    def __init__(self) -> None:
        self.header: Optional[ResultHeader] = None
        self.rows: List[ResultRow] = []
        self.done: Optional[ResultDone] = None
        self.error: Optional[ResultError] = None

    def add(self, frame: Frame) -> bool:
        if frame.type == MessageType.RESULT_HEADER:
            self.header = ResultHeader.from_frame(frame)
        elif frame.type == MessageType.RESULT_ROW:
            self.rows.append(ResultRow.from_frame(frame))
        elif frame.type == MessageType.RESULT_DONE:
            self.done = ResultDone.from_frame(frame)
        elif frame.type == MessageType.RESULT_ERROR:
            self.error = ResultError.from_frame(frame)
        return self.done is not None or self.error is not None


class AsyncClient:
    """Async client over the tinydb wire protocol."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        database: Optional[str] = None,
        connect_timeout: float = 5.0,
        hello_timeout: float = 5.0,
    ) -> None:
        self._host = host
        self._port = port
        self._database = database
        self._connect_timeout = connect_timeout
        self._hello_timeout = hello_timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._frame_reader = FrameReader()
        self._closed = False
        self.version: str = ""

    # -- context manager ---------------------------------------------

    async def __aenter__(self) -> "AsyncClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # -- connection lifecycle ----------------------------------------

    async def connect(self) -> None:
        """Open the TCP socket and complete the HELLO handshake."""
        if self._writer is not None:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._connect_timeout,
            )
        except (asyncio.TimeoutError, OSError) as e:
            raise ClientConnectionError(
                f"cannot connect to {self._host}:{self._port}: {e}"
            ) from e
        # Send HELLO and await OK.
        fw = FrameWriter(self._writer)
        fw.write_frame(perform_client_handshake().to_frame())
        try:
            await self._writer.drain()
        except Exception:
            pass
        # Read the OK frame using the header-parse loop.
        try:
            ok_frame = await asyncio.wait_for(
                self._read_one_frame(), timeout=self._hello_timeout
            )
        except asyncio.TimeoutError as e:
            await self._abort()
            raise ClientTimeoutError("handshake timed out waiting for OK") from e
        if ok_frame is None:
            await self._abort()
            raise ClientConnectionError("server closed during handshake")
        if ok_frame.type != MessageType.OK:
            await self._abort()
            raise ProtocolError(
                f"expected OK after HELLO, got type {ok_frame.type}"
            )
        self.version = Ok.from_frame(ok_frame).version

    async def close(self) -> None:
        """Send QUIT and close the underlying transport. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self._writer is not None:
            try:
                fw = FrameWriter(self._writer)
                fw.write_frame(Quit().to_frame())
                await self._writer.drain()
            except Exception:
                pass
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None

    async def _abort(self) -> None:
        """Tear down the connection without a graceful QUIT."""
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        self._closed = True

    # -- low-level frame I/O ------------------------------------------

    async def _read_one_frame(self) -> Optional[Frame]:
        """Pull exactly one frame from the stream.

        Returns ``None`` on clean EOF, raises on transport errors.
        """
        reader = self._reader
        if reader is None:
            raise ClientConnectionError("client is closed")
        # Read the 6-byte header (length + type + flags).
        header = await reader.readexactly(6)
        length = int.from_bytes(header[:4], "big")
        rest = await reader.readexactly(length)
        # Feed through the codec to get a parsed Frame.
        frame = self._frame_reader.feed(header + rest)
        if frame is None:
            # Should not happen — we just supplied a complete buffer.
            raise WireProtocolError("FrameReader failed to parse complete frame")
        return frame

    async def _read_until(
        self, predicate, timeout: float
    ) -> Frame:
        """Read frames until ``predicate(frame)`` is True.

        Frames that fail the predicate are discarded (this matches the
        sync client's "discard late heartbeats" behaviour).
        """
        end = time.time() + timeout
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                raise ClientTimeoutError("read timed out")
            try:
                frame = await asyncio.wait_for(
                    self._read_one_frame(), timeout=remaining
                )
            except asyncio.TimeoutError as e:
                raise ClientTimeoutError("read timed out") from e
            if frame is None:
                raise ClientConnectionError("connection lost")
            if predicate(frame):
                return frame

    # -- public API ---------------------------------------------------

    async def execute(
        self,
        sql: str,
        params: Optional[List[Any]] = None,
        *,
        timeout: float = 30.0,
    ) -> AsyncResult:
        """Execute one SQL statement and return its result."""
        if self._writer is None:
            await self.connect()
        if self._writer is None:
            raise ClientConnectionError("client is closed")
        fw = FrameWriter(self._writer)
        if params is None:
            fw.write_frame(Query(sql=sql).to_frame())
        else:
            typed_params = [_to_param(p) for p in params]
            fw.write_frame(Exec(sql=sql, params=typed_params).to_frame())
        await self._writer.drain()
        return await self._collect_response(timeout)

    async def execute_many(
        self,
        sql: str,
        params_list: List[List[Any]],
        *,
        batch_size: int = 100,
    ) -> int:
        """Run ``sql`` once per parameter list; return total affected rows."""
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        total = 0
        for i in range(0, len(params_list), batch_size):
            batch = params_list[i : i + batch_size]
            for params in batch:
                result = await self.execute(sql, params)
                if result.rowcount and result.rowcount > 0:
                    total += int(result.rowcount)
        return total

    async def ping(self) -> float:
        """Send a PING and return the RTT in seconds."""
        if self._writer is None:
            raise ClientConnectionError("client is closed")
        fw = FrameWriter(self._writer)
        ts = time.time_ns()
        fw.write_frame(Ping(ts=ts).to_frame())
        await self._writer.drain()
        try:
            pong_frame = await self._read_until(
                lambda f: f.type == MessageType.PONG, timeout=5.0
            )
        except ClientTimeoutError as e:
            raise ClientConnectionError("ping timed out") from e
        pong = Pong.from_frame(pong_frame)
        return (time.time_ns() - pong.ts) / 1e9

    # -- response collection -----------------------------------------

    async def _collect_response(self, timeout: float) -> AsyncResult:
        """Collect a RESULT_HEADER...RESULT_DONE/ERROR sequence."""
        response = _AsyncResponse()
        end = time.time() + timeout

        def _is_done(frame: Frame) -> bool:
            return response.add(frame)

        try:
            await self._read_until(_is_done, timeout=timeout)
        except ClientTimeoutError:
            raise ClientTimeoutError("execute timed out")

        if response.error is not None:
            err = response.error
            if err.code == "22000":
                raise IntegrityError(err.msg)
            raise ProtocolError(f"{err.code}: {err.msg}")
        rows = [r.values for r in response.rows]
        columns = (
            [name for name, _ in response.header.columns]
            if response.header is not None
            else []
        )
        return AsyncResult(
            rows=rows,
            rowcount=response.done.rowcount if response.done else 0,
            columns=columns,
            last_insert_id=response.done.last_insert_id if response.done else 0,
        )


# ---------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------


def _to_param(value: Any) -> Param:
    """Convert a Python value to a protocol :class:`Param`."""
    if value is None:
        return Param(ParamType.NULL, None)
    if isinstance(value, bool):
        return Param(ParamType.BOOL, value)
    if isinstance(value, int):
        return Param(ParamType.INT64, value)
    if isinstance(value, float):
        return Param(ParamType.FLOAT64, value)
    return Param(ParamType.STRING, str(value))


__all__ = ["AsyncClient", "AsyncResult"]