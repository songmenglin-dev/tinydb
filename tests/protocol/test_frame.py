"""Tests for the wire protocol Frame data structure (v0.3, T-1.1)."""
from __future__ import annotations

import pytest

from tinydb.protocol.frame import Frame, ProtocolError


class TestFrameConstruct:
    """Frame construction stores fields as-is."""

    def test_frame_construct(self):
        f = Frame(len=5, type=0x10, flags=0, payload=b"hello")
        assert f.len == 5
        assert f.type == 0x10
        assert f.flags == 0
        assert f.payload == b"hello"

    def test_frame_default_flags(self):
        f = Frame(len=3, type=0x01, payload=b"abc")
        assert f.flags == 0

    def test_frame_repr_includes_type_hex(self):
        f = Frame(len=2, type=0x10, payload=b"ab")
        s = repr(f)
        assert "0x10" in s
        assert "len=2" in s


class TestFrameToBytes:
    """`Frame.to_bytes` encodes as big-endian length prefix + type + flags + payload."""

    def test_frame_to_bytes_layout(self):
        f = Frame(len=5, type=0x10, flags=0, payload=b"hello")
        data = f.to_bytes()
        # 4 bytes len (BE) + 1 byte type + 1 byte flags + 5 bytes payload.
        assert len(data) == 4 + 1 + 1 + 5
        # Big-endian length prefix.
        assert data[:4] == b"\x00\x00\x00\x05"
        assert data[4] == 0x10
        assert data[5] == 0x00
        assert data[6:] == b"hello"

    def test_frame_to_bytes_empty_payload(self):
        f = Frame(len=0, type=0xFE, payload=b"")
        data = f.to_bytes()
        assert len(data) == 6
        assert data[:4] == b"\x00\x00\x00\x00"
        assert data[4] == 0xFE


class TestFrameFromBytes:
    """`Frame.from_bytes` decodes the wire layout."""

    def test_frame_from_bytes_roundtrip(self):
        original = Frame(len=5, type=0x10, flags=0x01, payload=b"hello")
        data = original.to_bytes()
        parsed = Frame.from_bytes(data)
        assert parsed == original

    def test_frame_from_bytes_truncated(self):
        with pytest.raises(ProtocolError):
            Frame.from_bytes(b"\x00\x00\x00\x05\x10\x01")  # no payload

    def test_frame_from_bytes_header_only(self):
        with pytest.raises(ProtocolError):
            Frame.from_bytes(b"\x00\x00\x00\x05\x10")  # missing flags


class TestFrameProtocolError:
    """ProtocolError is a TinydbError subclass."""

    def test_protocol_error_is_tinydb_error(self):
        from tinydb.errors import TinydbError
        assert issubclass(ProtocolError, TinydbError)

    def test_protocol_error_message(self):
        e = ProtocolError("bad frame")
        assert "bad frame" in str(e)
