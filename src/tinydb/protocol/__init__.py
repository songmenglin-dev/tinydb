"""Wire protocol package (v0.3).

Exposes the lowest-level codec so :mod:`tinydb.server`,
:mod:`tinydb.client`, and the JDBC bridge can all share the same
definitions.  Higher-level helpers (SQL queries, result sets) live in
:mod:`tinydb.protocol.messages`.
"""
from __future__ import annotations

from tinydb.protocol.codec import FrameReader, FrameWriter, IncompleteFrameError
from tinydb.protocol.frame import MAX_FRAME_LEN, Frame, ProtocolError

__all__ = [
    "MAX_FRAME_LEN",
    "Frame",
    "FrameReader",
    "FrameWriter",
    "IncompleteFrameError",
    "ProtocolError",
]
