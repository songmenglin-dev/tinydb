"""Wire protocol message classes (v0.3, REQ-PROTO-2 through REQ-PROTO-9).

Each message class is a small value object that knows how to encode
itself into a :class:`~tinydb.protocol.frame.Frame` and decode back.

The 12 message types implemented here exactly correspond to the table
in REQ-PROTO-2:

* CLIENT → SERVER:  HELLO, QUERY, EXEC, PING, QUIT
* SERVER → CLIENT:  OK, ERR, RESULT_HEADER, RESULT_ROW, RESULT_DONE,
                    RESULT_ERROR, PONG

Each message exposes a ``to_frame()`` method that returns a
:class:`Frame` with the right type code and payload, and a
``from_frame(frame)`` classmethod that does the reverse.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, List, Optional, Tuple, Union

from tinydb.protocol.frame import Frame

MAX_PARAMS: int = 1024
MAX_CLIENT_ID: int = 64


class MessageType(IntEnum):
    """The 12 wire-protocol message type codes."""

    HELLO = 0x01
    OK = 0x02
    ERR = 0x03
    QUERY = 0x10
    EXEC = 0x11
    RESULT_HEADER = 0x20
    RESULT_ROW = 0x21
    RESULT_DONE = 0x22
    RESULT_ERROR = 0x23
    PING = 0x30
    PONG = 0x31
    QUIT = 0xFE


class ParamType(IntEnum):
    """Parameter type codes used in the EXEC payload."""

    NULL = 0x00
    INT64 = 0x01
    FLOAT64 = 0x02
    STRING = 0x03
    BOOL = 0x04


# --- simple flag/empty messages ----------------------------------------


@dataclass
class Hello:
    """HELLO — client → server handshake."""

    client: str

    def __post_init__(self) -> None:
        encoded = self.client.encode("utf-8")
        if len(encoded) > MAX_CLIENT_ID:
            raise ValueError(
                f"HELLO client id too long: {len(encoded)} > {MAX_CLIENT_ID} bytes"
            )

    def to_frame(self) -> Frame:
        return Frame(
            type=MessageType.HELLO,
            payload=self.client.encode("utf-8"),
        )

    @classmethod
    def from_frame(cls, frame: Frame) -> "Hello":
        return cls(client=frame.payload.decode("utf-8"))


@dataclass
class Ok:
    """OK — server → client positive ack."""

    version: str

    def to_frame(self) -> Frame:
        return Frame(type=MessageType.OK, payload=self.version.encode("utf-8"))

    @classmethod
    def from_frame(cls, frame: Frame) -> "Ok":
        return cls(version=frame.payload.decode("utf-8"))


@dataclass
class Err:
    """ERR — server → client error ack (handshake-level)."""

    code: str
    msg: str

    def to_frame(self) -> Frame:
        code = self.code.encode("ascii")
        msg = self.msg.encode("utf-8")
        return Frame(
            type=MessageType.ERR,
            payload=code + struct.pack(">H", len(msg)) + msg,
        )

    @classmethod
    def from_frame(cls, frame: Frame) -> "Err":
        code = frame.payload[:5].decode("ascii")
        (msg_len,) = struct.unpack(">H", frame.payload[5:7])
        msg = frame.payload[7 : 7 + msg_len].decode("utf-8")
        return cls(code=code, msg=msg)


# --- SQL query messages -------------------------------------------------


@dataclass
class Query:
    """QUERY — transmit a single SQL string (no parameters)."""

    sql: str

    def to_frame(self) -> Frame:
        return Frame(type=MessageType.QUERY, payload=self.sql.encode("utf-8"))

    @classmethod
    def from_frame(cls, frame: Frame) -> "Query":
        return cls(sql=frame.payload.decode("utf-8"))


@dataclass
class Param:
    """A single typed parameter for an :class:`Exec` message."""

    type: ParamType
    value: Any


@dataclass
class Exec:
    """EXEC — SQL string + typed parameter list."""

    sql: str
    params: List[Param] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.params) > MAX_PARAMS:
            raise ValueError(
                f"too many params: {len(self.params)} > {MAX_PARAMS}"
            )

    def to_frame(self) -> Frame:
        sql_bytes = self.sql.encode("utf-8")
        body = struct.pack(">I", len(sql_bytes)) + sql_bytes
        body += struct.pack(">H", len(self.params))
        for p in self.params:
            body += bytes([p.type])
            if p.type == ParamType.NULL:
                body += struct.pack(">I", 0)
            elif p.type == ParamType.INT64:
                body += struct.pack(">I", 8) + struct.pack(">q", int(p.value))
            elif p.type == ParamType.FLOAT64:
                body += struct.pack(">I", 8) + struct.pack(">d", float(p.value))
            elif p.type == ParamType.STRING:
                encoded = str(p.value).encode("utf-8")
                body += struct.pack(">I", len(encoded)) + encoded
            elif p.type == ParamType.BOOL:
                body += struct.pack(">I", 1) + bytes([1 if p.value else 0])
            else:
                raise ValueError(f"unknown param type: {p.type}")
        return Frame(type=MessageType.EXEC, payload=body)

    @classmethod
    def from_frame(cls, frame: Frame) -> "Exec":
        payload = frame.payload
        (sql_len,) = struct.unpack(">I", payload[:4])
        sql = payload[4 : 4 + sql_len].decode("utf-8")
        offset = 4 + sql_len
        (param_count,) = struct.unpack(">H", payload[offset : offset + 2])
        offset += 2
        params: List[Param] = []
        for _ in range(param_count):
            ptype = ParamType(payload[offset])
            offset += 1
            (plen,) = struct.unpack(">I", payload[offset : offset + 4])
            offset += 4
            data = payload[offset : offset + plen]
            offset += plen
            if ptype == ParamType.NULL:
                params.append(Param(ptype, None))
            elif ptype == ParamType.INT64:
                params.append(Param(ptype, struct.unpack(">q", data)[0]))
            elif ptype == ParamType.FLOAT64:
                params.append(Param(ptype, struct.unpack(">d", data)[0]))
            elif ptype == ParamType.STRING:
                params.append(Param(ptype, data.decode("utf-8")))
            elif ptype == ParamType.BOOL:
                params.append(Param(ptype, bool(data[0])))
            else:
                raise ValueError(f"unknown param type: {ptype}")
        return cls(sql=sql, params=params)


# --- result-set messages ------------------------------------------------


@dataclass
class ResultHeader:
    """Column metadata returned before the row stream."""

    # list of (name, type_code) pairs
    columns: List[Tuple[str, int]]

    def to_frame(self) -> Frame:
        body = struct.pack(">H", len(self.columns))
        for name, type_code in self.columns:
            encoded = name.encode("utf-8")
            body += bytes([len(encoded)]) + encoded + bytes([type_code])
        return Frame(type=MessageType.RESULT_HEADER, payload=body)

    @classmethod
    def from_frame(cls, frame: Frame) -> "ResultHeader":
        payload = frame.payload
        (count,) = struct.unpack(">H", payload[:2])
        offset = 2
        cols: List[Tuple[str, int]] = []
        for _ in range(count):
            name_len = payload[offset]
            offset += 1
            name = payload[offset : offset + name_len].decode("utf-8")
            offset += name_len
            type_code = payload[offset]
            offset += 1
            cols.append((name, type_code))
        return cls(columns=cols)


@dataclass
class ResultRow:
    """A single row of result values."""

    values: List[Any]

    def to_frame(self) -> Frame:
        body = struct.pack(">H", len(self.values))
        for v in self.values:
            if v is None:
                body += bytes([ParamType.NULL]) + struct.pack(">I", 0)
            elif isinstance(v, bool):
                body += bytes([ParamType.BOOL]) + struct.pack(">I", 1) + bytes([1 if v else 0])
            elif isinstance(v, int):
                body += bytes([ParamType.INT64]) + struct.pack(">I", 8) + struct.pack(">q", v)
            elif isinstance(v, float):
                body += bytes([ParamType.FLOAT64]) + struct.pack(">I", 8) + struct.pack(">d", v)
            elif isinstance(v, str):
                encoded = v.encode("utf-8")
                body += bytes([ParamType.STRING]) + struct.pack(">I", len(encoded)) + encoded
            else:
                encoded = str(v).encode("utf-8")
                body += bytes([ParamType.STRING]) + struct.pack(">I", len(encoded)) + encoded
        return Frame(type=MessageType.RESULT_ROW, payload=body)

    @classmethod
    def from_frame(cls, frame: Frame) -> "ResultRow":
        payload = frame.payload
        (count,) = struct.unpack(">H", payload[:2])
        offset = 2
        values: List[Any] = []
        for _ in range(count):
            ptype = ParamType(payload[offset])
            offset += 1
            (plen,) = struct.unpack(">I", payload[offset : offset + 4])
            offset += 4
            data = payload[offset : offset + plen]
            offset += plen
            if ptype == ParamType.NULL:
                values.append(None)
            elif ptype == ParamType.INT64:
                values.append(struct.unpack(">q", data)[0])
            elif ptype == ParamType.FLOAT64:
                values.append(struct.unpack(">d", data)[0])
            elif ptype == ParamType.STRING:
                values.append(data.decode("utf-8"))
            elif ptype == ParamType.BOOL:
                values.append(bool(data[0]))
            else:
                values.append(None)
        return cls(values=values)


@dataclass
class ResultDone:
    """End-of-result marker with statistics."""

    rowcount: int
    last_insert_id: int
    status_flags: int

    def to_frame(self) -> Frame:
        body = (
            struct.pack(">q", self.rowcount)
            + struct.pack(">q", self.last_insert_id)
            + bytes([self.status_flags])
        )
        return Frame(type=MessageType.RESULT_DONE, payload=body)

    @classmethod
    def from_frame(cls, frame: Frame) -> "ResultDone":
        (rowcount,) = struct.unpack(">q", frame.payload[:8])
        (last_insert_id,) = struct.unpack(">q", frame.payload[8:16])
        status_flags = frame.payload[16]
        return cls(
            rowcount=rowcount, last_insert_id=last_insert_id, status_flags=status_flags
        )


@dataclass
class ResultError:
    """Result-level error (after RESULT_HEADER)."""

    code: str
    msg: str

    def to_frame(self) -> Frame:
        code = self.code.encode("ascii")
        msg = self.msg.encode("utf-8")
        return Frame(
            type=MessageType.RESULT_ERROR,
            payload=code + struct.pack(">H", len(msg)) + msg,
        )

    @classmethod
    def from_frame(cls, frame: Frame) -> "ResultError":
        code = frame.payload[:5].decode("ascii")
        (msg_len,) = struct.unpack(">H", frame.payload[5:7])
        msg = frame.payload[7 : 7 + msg_len].decode("utf-8")
        return cls(code=code, msg=msg)


# --- heartbeat and shutdown --------------------------------------------


@dataclass
class Ping:
    """PING — heartbeat request."""

    ts: int

    def to_frame(self) -> Frame:
        return Frame(type=MessageType.PING, payload=struct.pack(">Q", self.ts))

    @classmethod
    def from_frame(cls, frame: Frame) -> "Ping":
        (ts,) = struct.unpack(">Q", frame.payload)
        return cls(ts=ts)


@dataclass
class Pong:
    """PONG — heartbeat reply."""

    ts: int

    def to_frame(self) -> Frame:
        return Frame(type=MessageType.PONG, payload=struct.pack(">Q", self.ts))

    @classmethod
    def from_frame(cls, frame: Frame) -> "Pong":
        (ts,) = struct.unpack(">Q", frame.payload)
        return cls(ts=ts)


@dataclass
class Quit:
    """QUIT — graceful connection close."""

    def to_frame(self) -> Frame:
        return Frame(type=MessageType.QUIT, payload=b"")

    @classmethod
    def from_frame(cls, frame: Frame) -> "Quit":
        return cls()


# --- alias used in early tests -----------------------------------------
# (some callsites spell the Done result as just "Done" — export under
# the canonical name too for ergonomics).


@dataclass
class Done:
    """Internal alias for :class:`ResultDone` used by the server."""

    rowcount: int
    last_insert_id: int
    status_flags: int

    def to_frame(self) -> Frame:
        return ResultDone(
            self.rowcount, self.last_insert_id, self.status_flags
        ).to_frame()


# --- dispatcher --------------------------------------------------------


_DISPATCH: dict = {
    MessageType.HELLO: Hello,
    MessageType.OK: Ok,
    MessageType.ERR: Err,
    MessageType.QUERY: Query,
    MessageType.EXEC: Exec,
    MessageType.RESULT_HEADER: ResultHeader,
    MessageType.RESULT_ROW: ResultRow,
    MessageType.RESULT_DONE: ResultDone,
    MessageType.RESULT_ERROR: ResultError,
    MessageType.PING: Ping,
    MessageType.PONG: Pong,
    MessageType.QUIT: Quit,
}


def decode_message(frame: Frame) -> Any:
    """Decode a frame into the corresponding message dataclass.

    Raises :class:`ValueError` if the type code is unknown.
    """
    try:
        cls = _DISPATCH[MessageType(frame.type)]
    except (KeyError, ValueError):
        raise ValueError(f"unknown message type: 0x{frame.type:02X}")
    return cls.from_frame(frame)


__all__ = [
    "MessageType",
    "ParamType",
    "Param",
    "Hello",
    "Ok",
    "Err",
    "Query",
    "Exec",
    "ResultHeader",
    "ResultRow",
    "ResultDone",
    "ResultError",
    "Ping",
    "Pong",
    "Quit",
    "Done",
    "decode_message",
    "MAX_PARAMS",
    "MAX_CLIENT_ID",
]
