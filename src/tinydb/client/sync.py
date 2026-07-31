"""Synchronous Python Client (v0.3, REQ-CLI-1..8).

The Client uses a single TCP socket plus a queue.Queue to dispatch
incoming response frames back to the caller that issued the request.
Heartbeats (PING/PONG) are scheduled in the same queue.
"""
from __future__ import annotations

import contextlib
import queue
import socket
import threading
import time
from typing import Any, List, Optional

from tinydb.client.errors import (
    ConnectionError as ClientConnectionError,
    IntegrityError,
    ProtocolError,
    TimeoutError as ClientTimeoutError,
)
from tinydb.errors import TinydbError
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


class Result:
    """The result of a :meth:`Client.execute` call."""

    def __init__(self, rows=None, rowcount=0, columns=None, last_insert_id=0):
        self.rows = rows or []
        self.rowcount = rowcount
        self.columns = columns or []
        self.last_insert_id = last_insert_id

    def __repr__(self) -> str:
        return (
            f"Result(rows={self.rows!r}, rowcount={self.rowcount}, "
            f"columns={self.columns!r}, last_insert_id={self.last_insert_id})"
        )


class _Response:
    """Internal: collect frames until a complete response is buffered."""

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


class Client:
    """Synchronous client over the tinydb wire protocol."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        database: Optional[str] = None,
        connect_timeout: float = 5.0,
        heartbeat: bool = True,
        hello_timeout: float = 5.0,
        max_retries: int = 5,
    ) -> None:
        self._host = host
        self._port = port
        self._database = database
        self._connect_timeout = connect_timeout
        self._hello_timeout = hello_timeout
        self._heartbeat_enabled = heartbeat
        self._max_retries = max_retries
        self._sock: Optional[socket.socket] = None
        self._lock = threading.RLock()
        self._response_queue: "queue.Queue[Frame]" = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None
        self._closed = False
        self._transaction_depth = 0
        self.version: str = ""
        self._connect()

    # -- connection management ---------------------------------------

    def _connect(self) -> None:
        """Open the TCP socket + perform the HELLO handshake."""
        try:
            sock = socket.create_connection(
                (self._host, self._port), timeout=self._connect_timeout
            )
        except OSError as e:
            raise ClientConnectionError(
                f"cannot connect to {self._host}:{self._port}: {e}"
            ) from e
        sock.settimeout(self._hello_timeout)
        try:
            fw = FrameWriter(_SocketWriter(sock))
            fr = FrameReader()
            fw.write_frame(perform_client_handshake().to_frame())
            fw.flush()
            # Read the OK frame via the codec.
            ok_frame: Optional[Frame] = None
            while ok_frame is None:
                try:
                    buf = sock.recv(4096)
                except socket.timeout:
                    raise ClientTimeoutError(
                        "handshake timed out waiting for OK"
                    )
                if not buf:
                    raise ClientConnectionError(
                        "server closed during handshake"
                    )
                ok_frame = fr.feed(buf)
            if ok_frame.type != MessageType.OK:
                sock.close()
                raise ProtocolError(
                    f"expected OK after HELLO, got type {ok_frame.type}"
                )
            ok = Ok.from_frame(ok_frame)
            self.version = ok.version
        except (OSError, WireProtocolError) as e:
            sock.close()
            if isinstance(e, ClientTimeoutError):
                raise
            raise ClientConnectionError(f"handshake failed: {e}") from e
        sock.settimeout(None)
        self._sock = sock
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="tinydb-client-reader"
        )
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        """Background thread: pull frames off the socket and put them on the queue."""
        fr = FrameReader()
        sock = self._sock
        if sock is None:
            return
        try:
            while not self._closed:
                try:
                    buf = sock.recv(4096)
                except OSError:
                    break
                if not buf:
                    break
                # Feed all bytes, then drain all complete frames.
                frame = fr.feed(buf)
                while frame is not None:
                    self._response_queue.put(frame)
                    frame = fr.feed(b"")
        except Exception:
            pass

    # -- lifecycle ----------------------------------------------------

    def close(self) -> None:
        """Send QUIT and close the socket. Idempotent."""
        with self._lock:
            if self._closed:
                return
            sock = self._sock
            self._sock = None
        # Mark closed only after we've claimed the socket.  If we
        # flipped ``_closed`` first, a concurrent ``_collect_response``
        # could observe ``_closed`` and bail before this thread gets
        # a chance to flush QUIT — leaving the server waiting for a
        # graceful disconnect.
        with self._lock:
            self._closed = True
        if sock is not None:
            try:
                fw = FrameWriter(_SocketWriter(sock))
                fw.write_frame(Quit().to_frame())
                fw.flush()
            except Exception:
                pass
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # -- public API ---------------------------------------------------

    def execute(
        self,
        sql: str,
        params: Optional[List[Any]] = None,
        *,
        timeout: float = 30.0,
        retry: Optional[bool] = None,
    ) -> Result:
        """Execute one SQL statement and return its result.

        ``retry`` controls automatic re-execution after a connection
        drop with exponential backoff (100, 200, 400, 800, 1600 ms).
        Defaults to ``True`` for SELECT-style queries and ``False``
        for DML — silently re-executing an INSERT/UPDATE/DELETE could
        double-apply the change.  Pass ``retry=True`` explicitly to
        opt in (e.g. for an idempotent INSERT).
        """
        if retry is None:
            retry = self._is_safe_to_retry(sql)
        last_exc: Optional[Exception] = None
        max_attempts = self._max_retries + 1 if retry else 1
        for attempt in range(max_attempts):
            try:
                with self._lock:
                    if self._sock is None and attempt == 0:
                        raise ClientConnectionError("client is closed")
                    if self._sock is None:
                        # Reconnect.
                        self._reconnect()
                    sock = self._sock
                    if sock is None:
                        raise ClientConnectionError("reconnect failed")
                fw = FrameWriter(_SocketWriter(sock))
                if params is None:
                    fw.write_frame(Query(sql=sql).to_frame())
                else:
                    typed_params = [_to_param(p) for p in params]
                    fw.write_frame(
                        Exec(sql=sql, params=typed_params).to_frame()
                    )
                fw.flush()
                return self._collect_response(timeout)
            except ClientConnectionError as e:
                last_exc = e
                # Drop the dead socket before retrying.
                self._drop_sock()
                if attempt + 1 >= max_attempts:
                    break
                # Exponential backoff: 100 * 2^attempt ms
                backoff = (0.1 * (2 ** attempt))
                time.sleep(backoff)
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _is_safe_to_retry(sql: str) -> bool:
        """Heuristic: True iff ``sql`` starts with a known idempotent keyword.

        Only SELECT (and a couple of explicitly-idempotent forms like
        ``EXPLAIN``) are considered safe to silently re-execute after
        a connection drop.  Anything else — INSERT / UPDATE / DELETE /
        DDL / ``BEGIN``/``COMMIT``/``ROLLBACK`` — would risk
        double-application if the server had partially processed it
        before the connection died.
        """
        if not sql:
            return False
        head = sql.strip().split(None, 1)
        if not head:
            return False
        first = head[0].upper()
        return first in ("SELECT", "EXPLAIN", "SHOW", "DESCRIBE", "DESC", "WITH")

    def _drop_sock(self) -> None:
        """Close the current socket without sending QUIT (server already gone)."""
        with self._lock:
            sock = self._sock
            self._sock = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    def _reconnect(self) -> None:
        """Re-open the socket and perform the HELLO handshake."""
        try:
            sock = socket.create_connection(
                (self._host, self._port), timeout=self._connect_timeout
            )
        except OSError as e:
            raise ClientConnectionError(
                f"cannot reconnect to {self._host}:{self._port}: {e}"
            ) from e
        sock.settimeout(self._hello_timeout)
        try:
            fw = FrameWriter(_SocketWriter(sock))
            fr = FrameReader()
            fw.write_frame(perform_client_handshake().to_frame())
            fw.flush()
            ok_frame: Optional[Frame] = None
            while ok_frame is None:
                try:
                    buf = sock.recv(4096)
                except socket.timeout:
                    raise ClientTimeoutError(
                        "reconnect: handshake timed out waiting for OK"
                    )
                if not buf:
                    raise ClientConnectionError(
                        "server closed during reconnect handshake"
                    )
                ok_frame = fr.feed(buf)
            if ok_frame.type != MessageType.OK:
                sock.close()
                raise ProtocolError(
                    f"expected OK after HELLO, got type {ok_frame.type}"
                )
        except (OSError, WireProtocolError) as e:
            sock.close()
            raise ClientConnectionError(f"reconnect failed: {e}") from e
        sock.settimeout(None)
        with self._lock:
            self._sock = sock
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name="tinydb-client-reader",
            )
        self._reader_thread.start()

    def execute_many(
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
                result = self.execute(sql, params)
                if result.rowcount and result.rowcount > 0:
                    total += int(result.rowcount)
        return total

    @contextlib.contextmanager
    def transaction(self):
        """Context manager: BEGIN ... COMMIT / ROLLBACK."""
        with self._lock:
            if self._transaction_depth > 0:
                raise ProtocolError("nested transaction not supported")
            self._transaction_depth += 1
        self.execute("BEGIN")
        try:
            yield
        except Exception:
            try:
                self.execute("ROLLBACK")
            finally:
                with self._lock:
                    self._transaction_depth -= 1
            raise
        else:
            self.execute("COMMIT")
            with self._lock:
                self._transaction_depth -= 1

    def ping(self) -> float:
        """Send a PING and return the RTT in seconds."""
        with self._lock:
            if self._sock is None:
                raise ClientConnectionError("client is closed")
            sock = self._sock
        fw = FrameWriter(_SocketWriter(sock))
        ts = time.time_ns()
        fw.write_frame(Ping(ts=ts).to_frame())
        fw.flush()
        # PONG comes back via the reader thread.
        try:
            frame = self._wait_for_frame(
                MessageType.PONG, timeout=5.0
            )
        except ClientTimeoutError:
            raise ClientConnectionError("ping timed out")
        if frame is None:
            raise ClientConnectionError("connection lost during ping")
        pong = Pong.from_frame(frame)
        return (time.time_ns() - pong.ts) / 1e9

    # -- response collection -----------------------------------------

    def _wait_for_frame(
        self, expected_type: int, timeout: float
    ) -> Optional[Frame]:
        """Block until a frame of the expected type arrives on the queue."""
        end = time.time() + timeout
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                raise ClientTimeoutError(
                    f"timed out waiting for frame type {expected_type}"
                )
            try:
                frame = self._response_queue.get(timeout=remaining)
            except queue.Empty:
                if self._closed or self._sock is None:
                    return None
                continue
            if frame.type == expected_type:
                return frame
            # Discard other frames (e.g. late heartbeats).

    def _collect_response(self, timeout: float) -> Result:
        """Wait for the next response set and return a Result."""
        with self._lock:
            if self._sock is None:
                raise ClientConnectionError("client is closed")
        response = _Response()
        end = time.time() + timeout
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                raise ClientTimeoutError("execute timed out")
            try:
                frame = self._response_queue.get(timeout=remaining)
            except queue.Empty:
                if self._closed or self._sock is None:
                    raise ClientConnectionError(
                        "connection lost during execute"
                    )
                continue
            if response.add(frame):
                break
        if response.error is not None:
            err = response.error
            if err.code == "22000":
                raise IntegrityError(err.msg)
            raise ProtocolError(f"{err.code}: {err.msg}")
        # Build the Result.
        rows = [r.values for r in response.rows]
        columns = (
            [name for name, _ in response.header.columns]
            if response.header is not None
            else []
        )
        return Result(
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


class _SocketWriter:
    """Adapter so FrameWriter can write to a raw socket."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def write(self, data: bytes) -> None:
        self._sock.sendall(data)

    def flush(self) -> None:
        pass


__all__ = ["Client", "Result"]
