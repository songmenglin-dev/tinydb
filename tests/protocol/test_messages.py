"""Tests for the wire protocol messages (v0.3, T-1.4)."""
from __future__ import annotations

import pytest

from tinydb.protocol.frame import Frame
from tinydb.protocol.messages import (
    Done,
    Err,
    Exec,
    Hello,
    MessageType,
    Ok,
    Ping,
    Pong,
    Query,
    Quit,
    ResultDone,
    ResultError,
    ResultHeader,
    ResultRow,
    decode_message,
)


class TestMessageType:
    """The MessageType enum has the 12 required values."""

    def test_message_types_count(self):
        msg_types = list(MessageType)
        assert len(msg_types) == 12

    def test_message_type_bytes(self):
        assert MessageType.HELLO == 0x01
        assert MessageType.OK == 0x02
        assert MessageType.ERR == 0x03
        assert MessageType.QUERY == 0x10
        assert MessageType.EXEC == 0x11
        assert MessageType.RESULT_HEADER == 0x20
        assert MessageType.RESULT_ROW == 0x21
        assert MessageType.RESULT_DONE == 0x22
        assert MessageType.RESULT_ERROR == 0x23
        assert MessageType.PING == 0x30
        assert MessageType.PONG == 0x31
        assert MessageType.QUIT == 0xFE


class TestHelloMessage:
    """Hello carries a client identifier string."""

    def test_hello_encode_payload(self):
        h = Hello(client="py-tinydb-1.0")
        f = h.to_frame()
        assert f.type == MessageType.HELLO
        assert f.payload == b"py-tinydb-1.0"

    def test_hello_max_64_bytes(self):
        h = Hello(client="x" * 64)
        assert len(h.client) == 64

    def test_hello_too_long_raises(self):
        with pytest.raises(ValueError):
            Hello(client="x" * 65)

    def test_hello_from_frame(self):
        original = Hello(client="py-1.0")
        f = original.to_frame()
        decoded = Hello.from_frame(f)
        assert decoded.client == "py-1.0"


class TestOkMessage:
    """Ok carries a server version string."""

    def test_ok_encode_payload(self):
        o = Ok(version="tinydb-0.3.0")
        f = o.to_frame()
        assert f.type == MessageType.OK
        assert f.payload == b"tinydb-0.3.0"

    def test_ok_from_frame(self):
        original = Ok(version="tinydb-0.3.0")
        f = original.to_frame()
        decoded = Ok.from_frame(f)
        assert decoded.version == "tinydb-0.3.0"


class TestErrMessage:
    """Err carries a SQLSTATE code and message."""

    def test_err_encode_payload(self):
        e = Err(code="08000", msg="HELLO required")
        f = e.to_frame()
        assert f.type == MessageType.ERR
        # 5 bytes code + 2 bytes msg length + msg bytes.
        assert f.payload == b"08000" + (14).to_bytes(2, "big") + b"HELLO required"

    def test_err_from_frame(self):
        original = Err(code="42000", msg="syntax error")
        f = original.to_frame()
        decoded = Err.from_frame(f)
        assert decoded.code == "42000"
        assert decoded.msg == "syntax error"


class TestQueryMessage:
    """Query carries a UTF-8 SQL string."""

    def test_query_payload(self):
        q = Query(sql="SELECT 1")
        f = q.to_frame()
        assert f.type == MessageType.QUERY
        assert f.payload == b"SELECT 1"

    def test_query_empty_sql(self):
        q = Query(sql="")
        f = q.to_frame()
        assert f.payload == b""

    def test_query_unicode(self):
        q = Query(sql="SELECT '你好'")
        f = q.to_frame()
        assert f.payload == "SELECT '你好'".encode("utf-8")

    def test_query_from_frame(self):
        original = Query(sql="SELECT * FROM t")
        f = original.to_frame()
        decoded = Query.from_frame(f)
        assert decoded.sql == "SELECT * FROM t"


class TestExecMessage:
    """Exec carries SQL + typed parameters."""

    def test_exec_no_params(self):
        e = Exec(sql="SELECT 1", params=[])
        f = e.to_frame()
        assert f.type == MessageType.EXEC
        # SQL_LEN(4B) + SQL + PARAM_COUNT(2B)
        assert f.payload == (8).to_bytes(4, "big") + b"SELECT 1" + (0).to_bytes(2, "big")

    def test_exec_with_int_param(self):
        from tinydb.protocol.messages import Param, ParamType
        e = Exec(sql="SELECT ?", params=[Param(ParamType.INT64, 42)])
        f = e.to_frame()
        assert f.type == MessageType.EXEC
        # Decoded should round-trip.
        decoded = Exec.from_frame(f)
        assert decoded.sql == "SELECT ?"
        assert len(decoded.params) == 1
        assert decoded.params[0].type == ParamType.INT64
        assert decoded.params[0].value == 42

    def test_exec_with_string_param(self):
        from tinydb.protocol.messages import Param, ParamType
        e = Exec(sql="SELECT ?", params=[Param(ParamType.STRING, "hello")])
        f = e.to_frame()
        decoded = Exec.from_frame(f)
        assert decoded.params[0].type == ParamType.STRING
        assert decoded.params[0].value == "hello"

    def test_exec_with_null_param(self):
        from tinydb.protocol.messages import Param, ParamType
        e = Exec(sql="SELECT ?", params=[Param(ParamType.NULL, None)])
        f = e.to_frame()
        decoded = Exec.from_frame(f)
        assert decoded.params[0].type == ParamType.NULL
        assert decoded.params[0].value is None

    def test_exec_too_many_params(self):
        from tinydb.protocol.messages import Param, ParamType
        params = [Param(ParamType.INT64, i) for i in range(1025)]
        with pytest.raises(ValueError):
            Exec(sql="SELECT ?", params=params)


class TestResultHeaderMessage:
    """ResultHeader carries column metadata."""

    def test_result_header_payload(self):
        h = ResultHeader(columns=[("id", 0x01), ("name", 0x02)])
        f = h.to_frame()
        assert f.type == MessageType.RESULT_HEADER
        decoded = ResultHeader.from_frame(f)
        assert decoded.columns == [("id", 0x01), ("name", 0x02)]

    def test_result_header_empty(self):
        h = ResultHeader(columns=[])
        f = h.to_frame()
        decoded = ResultHeader.from_frame(f)
        assert decoded.columns == []


class TestResultRowMessage:
    """ResultRow carries a single value list."""

    def test_result_row_payload(self):
        r = ResultRow(values=[1, "hello", True])
        f = r.to_frame()
        decoded = ResultRow.from_frame(f)
        assert decoded.values == [1, "hello", True]

    def test_result_row_empty(self):
        r = ResultRow(values=[])
        f = r.to_frame()
        decoded = ResultRow.from_frame(f)
        assert decoded.values == []


class TestResultDoneMessage:
    """ResultDone carries rowcount + last_insert_id + status flags."""

    def test_result_done_flags(self):
        d = ResultDone(rowcount=1, last_insert_id=5, status_flags=0x05)
        f = d.to_frame()
        assert f.type == MessageType.RESULT_DONE
        decoded = ResultDone.from_frame(f)
        assert decoded.rowcount == 1
        assert decoded.last_insert_id == 5
        assert decoded.status_flags == 0x05

    def test_result_done_no_result(self):
        d = ResultDone(rowcount=0, last_insert_id=0, status_flags=0x04)
        f = d.to_frame()
        decoded = ResultDone.from_frame(f)
        assert decoded.status_flags == 0x04


class TestResultErrorMessage:
    """ResultError carries SQLSTATE code + message."""

    def test_result_error_payload(self):
        e = ResultError(code="42000", msg="syntax error at 'FROM'")
        f = e.to_frame()
        assert f.type == MessageType.RESULT_ERROR
        decoded = ResultError.from_frame(f)
        assert decoded.code == "42000"
        assert decoded.msg == "syntax error at 'FROM'"


class TestPingPongMessages:
    """PING/PONG carry a timestamp."""

    def test_ping_encode(self):
        p = Ping(ts=12345)
        f = p.to_frame()
        assert f.type == MessageType.PING
        decoded = Ping.from_frame(f)
        assert decoded.ts == 12345

    def test_pong_encode(self):
        p = Pong(ts=12345)
        f = p.to_frame()
        assert f.type == MessageType.PONG
        decoded = Pong.from_frame(f)
        assert decoded.ts == 12345


class TestQuitMessage:
    """Quit is a flag message (empty payload)."""

    def test_quit_encode(self):
        q = Quit()
        f = q.to_frame()
        assert f.type == MessageType.QUIT
        assert f.payload == b""


class TestDecodeMessage:
    """decode_message dispatches by type to the right class."""

    def test_decode_hello(self):
        msg = Hello(client="py")
        f = msg.to_frame()
        decoded = decode_message(f)
        assert isinstance(decoded, Hello)
        assert decoded.client == "py"

    def test_decode_query(self):
        msg = Query(sql="SELECT 1")
        f = msg.to_frame()
        decoded = decode_message(f)
        assert isinstance(decoded, Query)
        assert decoded.sql == "SELECT 1"

    def test_decode_ping(self):
        msg = Ping(ts=100)
        f = msg.to_frame()
        decoded = decode_message(f)
        assert isinstance(decoded, Ping)
        assert decoded.ts == 100

    def test_decode_unknown_type_raises(self):
        f = Frame(len=0, type=0x99, payload=b"")
        with pytest.raises(ValueError):
            decode_message(f)
