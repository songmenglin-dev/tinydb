"""Tests for the server session and command handler (v0.3, T-2.2, T-2.3)."""
from __future__ import annotations

import asyncio
import io
import socket

import pytest

from tinydb.protocol.codec import FrameReader, FrameWriter
from tinydb.protocol.frame import Frame
from tinydb.protocol.messages import (
    Err,
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
from tinydb.server.handler import dispatch_message
from tinydb.server.session import ServerSession


class _StubDatabase:
    """Test double for :class:`tinydb.api.Database`."""

    def __init__(self) -> None:
        self.calls: list = []
        # `return_rows` is an explicit marker: None means "not set",
        # an empty list means "set to empty", a non-empty list means
        # "set to these rows".
        self.return_rows = None
        self.table_names: list = ["users", "orders"]

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.return_rows is None:
            return [(1,)]
        return self.return_rows

    def list_tables(self):
        return self.table_names

    def get_schema(self, table):
        return f"CREATE TABLE {table} (id INT)"


def _frames_from_reader(buf: io.BytesIO) -> list:
    """Helper: decode all frames from a BytesIO containing server output."""
    buf.seek(0)
    r = FrameReader(buf)
    out = []
    while True:
        f = r.read_frame()
        if f is None:
            break
        out.append(f)
    return out


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestMockSessionHandshake:
    """The session accepts a Hello and replies with Ok."""

    def test_session_handshake_then_query(self):
        # Build a fake client stream that sends Hello + Query(SELECT 1).
        sink = io.BytesIO()
        writer = FrameWriter(sink)
        writer.write_frame(Hello(client="py-1.0").to_frame())
        writer.write_frame(Query(sql="SELECT 1").to_frame())
        # Server side: reader consumes the sink.
        reader = FrameReader(io.BytesIO(sink.getvalue()))
        db = _StubDatabase()
        db.return_rows = []  # force empty-result path
        session = ServerSession(reader=reader, db=db)
        # First call: handshake Ok
        r1 = _run(session.run_once())
        assert r1[0].type == MessageType.OK
        # Second call: dispatch the Query
        r2 = _run(session.run_once())
        # Empty result: HEADER + ROW + DONE
        assert r2[0].type == MessageType.RESULT_HEADER
        assert r2[1].type == MessageType.RESULT_ROW
        assert r2[2].type == MessageType.RESULT_DONE

    def test_session_missing_hello_closes(self):
        sink = io.BytesIO()
        FrameWriter(sink).write_frame(Query(sql="SELECT 1").to_frame())
        reader = FrameReader(io.BytesIO(sink.getvalue()))
        db = _StubDatabase()
        session = ServerSession(reader=reader, db=db)
        responses = _run(session.run_once())
        # First response should be an Err with code 08000.
        assert responses[0].type == MessageType.ERR
        err = Err.from_frame(responses[0])
        assert err.code == "08000"

    def test_session_quit_closes_gracefully(self):
        sink = io.BytesIO()
        FrameWriter(sink).write_frame(Hello(client="py-1.0").to_frame())
        FrameWriter(sink).write_frame(Quit().to_frame())
        reader = FrameReader(io.BytesIO(sink.getvalue()))
        db = _StubDatabase()
        session = ServerSession(reader=reader, db=db)
        # First frame: Hello → Ok
        r1 = _run(session.run_once())
        assert r1[0].type == MessageType.OK
        # Second frame: Quit → Ok
        r2 = _run(session.run_once())
        assert r2[0].type == MessageType.OK


class TestDispatchHandler:
    """dispatch_message maps protocol messages to db.execute."""

    def test_dispatch_query_calls_db_execute(self):
        db = _StubDatabase()
        db.return_rows = []
        msg = Query(sql="SELECT 1, 2")
        frames = _run(dispatch_message(msg, db))
        # Empty result: HEADER + ROW + DONE
        assert len(db.calls) == 1
        assert db.calls[0][0] == "SELECT 1, 2"
        assert db.calls[0][1] is None
        assert frames[0].type == MessageType.RESULT_HEADER
        assert frames[1].type == MessageType.RESULT_ROW
        assert frames[2].type == MessageType.RESULT_DONE

    def test_dispatch_exec_substitutes_params(self):
        db = _StubDatabase()
        db.return_rows = []
        msg = Exec(sql="SELECT ?", params=[Param(ParamType.INT64, 42)])
        _run(dispatch_message(msg, db))
        # The handler substitutes ? with literal values so the SQL
        # that reaches db.execute is "SELECT 42".
        assert db.calls[0][0] == "SELECT 42"

    def test_dispatch_query_syntax_error(self):
        db = _StubDatabase()
        # parse error will trigger ResultError
        from tinydb.errors import ParseError as _PE
        from tinydb.sql.parser import parse as _parse

        # Patch db.execute to raise ParseError.
        def _raise(sql, params=None):
            raise _PE(1, 1, "syntax error near 'FROM'")
        db.execute = _raise
        msg = Query(sql="SELECT FROM")
        frames = _run(dispatch_message(msg, db))
        # expect ResultError
        assert frames[0].type == MessageType.RESULT_ERROR
        err = ResultError.from_frame(frames[0])
        assert err.code == "42000"

    def test_dispatch_query_constraint_violation(self):
        from tinydb.errors import ConstraintViolation as _CV

        db = _StubDatabase()

        def _raise(sql, params=None):
            raise _CV("UNIQUE constraint violated")
        db.execute = _raise
        msg = Query(sql="INSERT INTO t VALUES (1, 'x')")
        frames = _run(dispatch_message(msg, db))
        assert frames[0].type == MessageType.RESULT_ERROR
        err = ResultError.from_frame(frames[0])
        assert err.code == "22000"

    def test_dispatch_query_returns_rows(self):
        db = _StubDatabase()
        db.return_rows = [(1, "Alice"), (2, "Bob")]
        msg = Query(sql="SELECT id, name FROM users")
        frames = _run(dispatch_message(msg, db))
        assert frames[0].type == MessageType.RESULT_HEADER
        header = ResultHeader.from_frame(frames[0])
        assert len(header.columns) >= 2
        assert frames[1].type == MessageType.RESULT_ROW
        row1 = ResultRow.from_frame(frames[1])
        assert row1.values == [1, "Alice"]
        assert frames[2].type == MessageType.RESULT_ROW
        row2 = ResultRow.from_frame(frames[2])
        assert row2.values == [2, "Bob"]
        assert frames[3].type == MessageType.RESULT_DONE
        done = ResultDone.from_frame(frames[3])
        assert done.rowcount == 2


class TestDispatchEmptySQL:
    """An empty SQL string returns a 42000 error."""

    def test_dispatch_empty_sql_error(self):
        db = _StubDatabase()
        msg = Query(sql="")
        frames = _run(dispatch_message(msg, db))
        assert frames[0].type == MessageType.RESULT_ERROR
        err = ResultError.from_frame(frames[0])
        assert err.code == "42000"
