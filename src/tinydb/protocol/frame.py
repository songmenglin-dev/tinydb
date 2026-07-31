"""Wire protocol frame structure (v0.3, REQ-PROTO-1).

A frame is the outer envelope used by every tinydb wire-proto message:

    [LEN(4B BE)][TYPE(1B)][FLAGS(1B)][PAYLOAD(LEN bytes)]

The LEN prefix counts **only** the payload bytes — it does **not**
include the type/flags bytes.  The minimum non-empty frame is
therefore LEN=0 carrying no payload (the type and flags are still
transmitted), and the maximum is 0xFFFFFF (16 MiB - 1, per
REQ-PROTO-1).

This module is the lowest layer of the protocol stack; it depends on
nothing else from tinydb beyond :mod:`tinydb.errors`.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from tinydb.errors import TinydbError

# Maximum frame length: 16 MiB - 1 (per REQ-PROTO-1).
MAX_FRAME_LEN: int = 0xFFFFFF

# Header byte counts: 4 (length) + 1 (type) + 1 (flags).
_HEADER_SIZE: int = 4 + 1 + 1


class ProtocolError(TinydbError):
    """Raised when the wire protocol bytes are malformed.

    Callers should treat this as a fatal connection error — the
    protocol state is undefined once a malformed frame has been seen.
    """


@dataclass
class Frame:
    """A single wire-protocol frame.

    Attributes:
        len: Length of the *payload* in bytes (does NOT count the
            type/flags bytes).  For an empty frame this is 0.
        type: One-byte message-type code (REQ-PROTO-2).
        flags: One-byte message flags (REQ-PROTO-1).
        payload: Raw bytes carried by the frame.
    """

    len: int = 0
    type: int = 0
    flags: int = 0
    payload: bytes = b""

    def __post_init__(self) -> None:
        if self.type < 0 or self.type > 0xFF:
            raise ValueError(f"frame type must fit in 1 byte, got {self.type}")
        if self.flags < 0 or self.flags > 0xFF:
            raise ValueError(f"frame flags must fit in 1 byte, got {self.flags}")
        if self.len < 0 or self.len > MAX_FRAME_LEN:
            raise ValueError(
                f"frame len must be 0..{MAX_FRAME_LEN}, got {self.len}"
            )
        # ``self.len`` is the payload length — it MUST match
        # ``len(self.payload)`` exactly.  A bare ``Frame(payload=...)``
        # call (which leaves ``len`` at the default 0) is auto-derived
        # for ergonomics, but an explicit mismatch is now an error so
        # caller mistakes (e.g. transposed length and type) fail loudly
        # instead of being silently coerced.
        if self.len == 0 and self.payload:
            self.len = len(self.payload)
        elif self.len != len(self.payload):
            raise ValueError(
                f"frame len {self.len} does not match payload length "
                f"{len(self.payload)}"
            )

    # -- encoding ----------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialize the frame into the wire layout.

        Returns ``LEN(4B BE) || TYPE(1B) || FLAGS(1B) || PAYLOAD``.

        The ``LEN`` field encodes the payload length; the type and
        flags bytes are always present and are NOT counted in LEN.
        """
        if len(self.payload) > MAX_FRAME_LEN:
            raise ProtocolError(
                f"frame payload too large: {len(self.payload)} bytes "
                f"(max {MAX_FRAME_LEN})"
            )
        return (
            struct.pack(">I", len(self.payload))
            + bytes([self.type, self.flags])
            + self.payload
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "Frame":
        """Decode a single frame from ``data``.

        Raises :class:`ProtocolError` if the buffer is truncated or
        if the length prefix exceeds :data:`MAX_FRAME_LEN`.
        """
        if len(data) < _HEADER_SIZE:
            raise ProtocolError(
                f"frame header too short: need {_HEADER_SIZE} bytes, got {len(data)}"
            )
        (length,) = struct.unpack(">I", data[:4])
        if length > MAX_FRAME_LEN:
            raise ProtocolError(
                f"frame length {length} exceeds {MAX_FRAME_LEN} (0xFFFFFF)"
            )
        if len(data) < _HEADER_SIZE + length:
            raise ProtocolError(
                f"frame truncated: header says {length} bytes, have {len(data) - _HEADER_SIZE}"
            )
        type_byte = data[4]
        flags_byte = data[5]
        payload = data[_HEADER_SIZE : _HEADER_SIZE + length]
        return cls(len=length, type=type_byte, flags=flags_byte, payload=payload)

    # -- ergonomics --------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover — debug sugar
        return (
            f"Frame(len={self.len}, type=0x{self.type:02X}, "
            f"flags=0x{self.flags:02X}, payload={self.payload!r})"
        )


__all__ = ["Frame", "ProtocolError", "MAX_FRAME_LEN"]
