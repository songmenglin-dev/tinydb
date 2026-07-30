"""Tests for the wire protocol streaming codec (v0.3, T-1.2)."""
from __future__ import annotations

import io

import pytest

from tinydb.protocol.codec import (
    FrameReader,
    FrameWriter,
    IncompleteFrameError,
)
from tinydb.protocol.frame import Frame, ProtocolError


class TestFrameWriter:
    """FrameWriter writes frames to an underlying binary stream."""

    def test_write_single_frame(self):
        buf = io.BytesIO()
        w = FrameWriter(buf)
        f = Frame(len=5, type=0x10, payload=b"hello")
        w.write_frame(f)
        data = buf.getvalue()
        assert len(data) == 4 + 1 + 1 + 5

    def test_write_multiple_frames(self):
        buf = io.BytesIO()
        w = FrameWriter(buf)
        w.write_frame(Frame(len=3, type=0x01, payload=b"abc"))
        w.write_frame(Frame(len=2, type=0x02, payload=b"xy"))
        w.write_frame(Frame(len=0, type=0x03, payload=b""))
        data = buf.getvalue()
        assert len(data) == (4 + 1 + 1 + 3) + (4 + 1 + 1 + 2) + (4 + 1 + 1)


class TestFrameReaderBasic:
    """FrameReader decodes frames from an underlying binary stream."""

    def test_read_single_frame(self):
        buf = io.BytesIO()
        w = FrameWriter(buf)
        original = Frame(len=5, type=0x10, payload=b"hello")
        w.write_frame(original)
        buf.seek(0)
        r = FrameReader(buf)
        assert r.read_frame() == original

    def test_read_multiple_frames(self):
        buf = io.BytesIO()
        w = FrameWriter(buf)
        a = Frame(len=3, type=0x01, payload=b"abc")
        b = Frame(len=2, type=0x02, payload=b"xy")
        c = Frame(len=0, type=0x03, payload=b"")
        for f in (a, b, c):
            w.write_frame(f)
        buf.seek(0)
        r = FrameReader(buf)
        assert r.read_frame() == a
        assert r.read_frame() == b
        assert r.read_frame() == c

    def test_eof_returns_none(self):
        buf = io.BytesIO()
        r = FrameReader(buf)
        assert r.read_frame() is None

    def test_roundtrip_bytesio(self):
        # Write 3 frames, read them back in order.
        buf = io.BytesIO()
        w = FrameWriter(buf)
        frames = [
            Frame(len=5, type=0x10, payload=b"hello"),
            Frame(len=0, type=0xFE, payload=b""),
            Frame(len=2, type=0x01, payload=b"ab"),
        ]
        for f in frames:
            w.write_frame(f)
        buf.seek(0)
        r = FrameReader(buf)
        for f in frames:
            assert r.read_frame() == f


class TestFrameReaderPartial:
    """Partial frames raise IncompleteFrameError."""

    def test_partial_header(self):
        buf = io.BytesIO(b"\x00\x00\x00\x05")
        r = FrameReader(buf)
        with pytest.raises(IncompleteFrameError):
            r.read_frame()

    def test_partial_header_and_type(self):
        buf = io.BytesIO(b"\x00\x00\x00\x05\x10")
        r = FrameReader(buf)
        with pytest.raises(IncompleteFrameError):
            r.read_frame()

    def test_partial_payload(self):
        # header says 5 payload bytes, only 3 present.
        buf = io.BytesIO(b"\x00\x00\x00\x05\x10\x00hel")
        r = FrameReader(buf)
        with pytest.raises(IncompleteFrameError):
            r.read_frame()


class TestFrameReaderOversize:
    """Oversize frames raise ProtocolError."""

    def test_oversize_frame(self):
        # LEN = 0xFFFFFF (max); exceeds the cap (16 MiB - 1).
        buf = io.BytesIO(b"\xFF\xFF\xFF\xFF")
        r = FrameReader(buf)
        with pytest.raises(ProtocolError):
            r.read_frame()


class TestFrameReaderFeed:
    """FrameReader handles incremental data arrival."""

    def test_feed_data_in_chunks(self):
        # Use a stream that hands out data one byte at a time.
        frames = [Frame(len=3, type=0x01, payload=b"abc")]
        buf = io.BytesIO()
        FrameWriter(buf).write_frame(frames[0])
        all_bytes = buf.getvalue()

        # Split the bytes into chunks; feed them through the reader.
        reader = FrameReader(io.BytesIO())
        received = []
        for byte in all_bytes:
            chunk = bytes([byte])
            try:
                f = reader.feed(chunk)
            except IncompleteFrameError:
                continue
            if f is not None:
                received.append(f)
        assert received == frames
