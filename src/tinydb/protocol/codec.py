"""Streaming codec for wire-protocol frames (v0.3, T-1.2).

A :class:`FrameWriter` writes frames to a binary stream; a
:class:`FrameReader` reads them back.  The reader buffers partial
data internally so the caller can hand it bytes one chunk at a time
without worrying about frame boundaries.

The codec is deliberately stream-agnostic — it only touches the
underlying :class:`io.RawIOBase` / :class:`io.BytesIO` interface so
both the synchronous client (which uses a real socket) and the
asyncio server (which uses StreamReader/StreamWriter) can wrap it.
"""
from __future__ import annotations

import io
import struct
from typing import BinaryIO, Optional

from tinydb.errors import TinydbError
from tinydb.protocol.frame import MAX_FRAME_LEN, Frame, ProtocolError

_HEADER_SIZE: int = 4 + 1 + 1


class IncompleteFrameError(TinydbError):
    """Raised when the codec has not yet seen enough bytes to decode a frame.

    Distinct from :class:`ProtocolError` so callers can distinguish
    "feed me more bytes" from "the wire is broken".
    """


class FrameWriter:
    """Write frames to a binary stream."""

    __slots__ = ("_stream",)

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream

    def write_frame(self, frame: Frame) -> None:
        """Encode ``frame`` and append it to the stream."""
        self._stream.write(frame.to_bytes())

    def flush(self) -> None:
        """Best-effort flush; ignored on streams that don't support it."""
        flush = getattr(self._stream, "flush", None)
        if flush is not None:
            flush()


class FrameReader:
    """Decode frames from a binary stream, buffering partial data.

    Two interfaces are supported:

    * :meth:`read_frame` — pulls bytes from the underlying stream on
      demand.  Returns ``None`` on EOF.  Raises
      :class:`IncompleteFrameError` when the stream is short and
      :class:`ProtocolError` when the bytes are malformed.
    * :meth:`feed` — caller hands bytes in manually and gets fully
      decoded frames back.  Useful when the underlying transport
      does not have a blocking read API (e.g. asyncio).
    """

    __slots__ = ("_stream", "_buffer")

    def __init__(self, stream: Optional[BinaryIO] = None) -> None:
        self._stream = stream
        self._buffer: bytearray = bytearray()

    # ---------------------------------------------------------------
    # public: stream-based reading
    # ---------------------------------------------------------------

    def _read_byte(self) -> bool:
        """Read one byte from the stream into the buffer.

        Returns True on success, False on EOF.
        """
        if self._stream is None:
            raise IncompleteFrameError("no stream")
        b = self._stream.read(1)
        if not b:
            return False
        self._buffer.extend(b)
        return True

    def read_frame(self) -> Optional[Frame]:
        """Read a frame from the stream, blocking until one is complete.

        Returns ``None`` on EOF.  Raises :class:`IncompleteFrameError`
        if the stream is short (the caller may try again later).
        """
        # Without a stream we rely on feed() and only return a frame
        # once the buffer holds a complete one.
        if self._stream is None:
            if len(self._buffer) < 4:
                return None
            length = struct.unpack(">I", self._buffer[:4])[0]
            if length > MAX_FRAME_LEN:
                raise ProtocolError(
                    f"frame length {length} exceeds {MAX_FRAME_LEN} (0xFFFFFF)"
                )
            if len(self._buffer) < _HEADER_SIZE + length:
                return None
            target = _HEADER_SIZE + length
            parsed = Frame.from_bytes(bytes(self._buffer[:target]))
            del self._buffer[:target]
            return parsed
        # With a stream: pull more bytes as needed.
        if len(self._buffer) < 4:
            while len(self._buffer) < 4:
                if not self._read_byte():
                    if self._buffer:
                        raise IncompleteFrameError(
                            "EOF while reading frame length"
                        )
                    return None
        length = struct.unpack(">I", self._buffer[:4])[0]
        if length > MAX_FRAME_LEN:
            raise ProtocolError(
                f"frame length {length} exceeds {MAX_FRAME_LEN} (0xFFFFFF)"
            )
        target = _HEADER_SIZE + length
        while len(self._buffer) < target:
            if not self._read_byte():
                raise IncompleteFrameError(
                    "EOF while reading frame body"
                )
        parsed = Frame.from_bytes(bytes(self._buffer[:target]))
        del self._buffer[:target]
        return parsed

    # ---------------------------------------------------------------
    # public: chunk-based feeding (for asyncio-style transports)
    # ---------------------------------------------------------------

    def feed(self, data: bytes) -> Optional[Frame]:
        """Append ``data`` to the internal buffer and return a frame if ready.

        Returns the next complete frame, or ``None`` if more bytes are
        needed.  Raises :class:`IncompleteFrameError` if the buffered
        bytes are still short, and :class:`ProtocolError` on malformed
        inputs.
        """
        if data:
            self._buffer.extend(data)
        if len(self._buffer) < _HEADER_SIZE:
            return None
        length = struct.unpack(">I", self._buffer[:4])[0]
        if length > MAX_FRAME_LEN:
            raise ProtocolError(
                f"frame length {length} exceeds {MAX_FRAME_LEN} (0xFFFFFF)"
            )
        if len(self._buffer) < _HEADER_SIZE + length:
            return None
        parsed = Frame.from_bytes(bytes(self._buffer[: _HEADER_SIZE + length]))
        del self._buffer[: _HEADER_SIZE + length]
        return parsed

    # ---------------------------------------------------------------
    # introspection
    # ---------------------------------------------------------------

    @property
    def buffered_bytes(self) -> int:
        """Number of bytes currently buffered internally."""
        return len(self._buffer)


__all__ = [
    "FrameReader",
    "FrameWriter",
    "IncompleteFrameError",
]
