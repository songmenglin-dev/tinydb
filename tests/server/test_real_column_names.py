"""Tests for v0.3 wire protocol: SELECT must return real column names.

The legacy v0.3 handler shipped ``col0``/``col1``/… placeholder names
on the wire because the SELECT projection was executed via
``db.execute(sql)`` which only returns ``List[tuple]`` — there was no
side channel for column labels.  JDBC clients (MyBatis, plain JDBC)
had to add a ``@Results(column="col0", property="id")`` mapping to
translate the placeholder back to the POJO field, which is brittle
and surprising.

REQ-V03-COLFIX: when a real :class:`Database` is in the room, the
server's :class:`ResultHeader` should report the *table*'s real
column names.  The test class :class:`_RealDatabase` here is a tiny
in-process stub that exercises the parser → planner → ``ops.result_columns``
pipeline that the CLI's :class:`FileBackend` already uses, so the
handler picks up real names without needing to parse SQL twice.

When the stub does not expose ``result_columns_for`` (the
``_StubDatabase`` in :mod:`tests.server.test_session` for instance)
the handler falls back to ``col{i}`` so existing tests stay green.
"""
from __future__ import annotations

import asyncio
import io
import re
from typing import List, Optional

import pytest

from tinydb.protocol.codec import FrameReader, FrameWriter
from tinydb.protocol.frame import Frame
from tinydb.protocol.messages import (
    Hello,
    MessageType,
    Query,
    ResultHeader,
    ResultRow,
)
from tinydb.server.handler import dispatch_message
from tinydb.server.session import ServerSession


# --------------------------------------------------------------------
# Stubs
# --------------------------------------------------------------------


class _RealDatabase:
    """Run-end Database stub that exposes ``result_columns_for(sql)``.

    The real :class:`tinydb.api.Database` could be used directly,
    but that pulls the catalog / executor / WAL machinery into
    the unit test.  This stub builds a tiny duck-typed catalog +
    executor pair so the parser + planner + ``result_columns`` pipeline
    exercises the same code paths the production handler will.
    """

    def __init__(self, table_columns: dict) -> None:
        # table name -> list of column names in declared order
        self._table_columns = table_columns
        self.calls: list = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        upper = sql.strip().upper()
        if upper.startswith("SELECT"):
            m = re.match(r"SELECT\s+\*\s+FROM\s+(\w+)", sql, re.IGNORECASE)
            if m:
                cols = self._table_columns.get(m.group(1), [])
                return [tuple(range(len(cols)))]
            m = re.match(
                r"SELECT\s+(.+?)\s+FROM\s+(\w+)", sql, re.IGNORECASE
            )
            if m:
                items = [s.strip() for s in m.group(1).split(",")]
                return [tuple(range(len(items)))]
        if upper.startswith("INSERT"):
            return [(1,)]
        return []

    def result_columns_for(self, sql: str) -> Optional[List[str]]:
        """Return real column names for the SELECT projection of ``sql``.

        Mirrors the logic in :class:`tinydb.cli.backend.FileBackend`:
        parse → plan → :func:`result_columns`.  Returns ``None`` for
        non-SELECT so the handler keeps using ``col{i}`` for DML.
        """
        from tinydb.executor.ops import result_columns
        from tinydb.executor.planner import plan as _plan
        from tinydb.sql.ast import Select, Star
        from tinydb.sql.parser import parse

        stmt = parse(sql)
        if not isinstance(stmt, Select):
            return None
        # SELECT * FROM users — expand to the table's declared columns.
        if stmt.columns and isinstance(stmt.columns[0], Star):
            return list(self._table_columns.get(stmt.table, []))
        # Build a tiny duck-typed catalog (the planner reads
        # ``meta.name``, ``meta.columns[*].name`` and ``.tag``).
        from tinydb.types.system import TypeTag

        _cols_for_table = self._table_columns

        class _Col:
            __slots__ = ("name", "tag")

            def __init__(self, name):
                self.name = name
                self.tag = TypeTag.Text

        class _Meta:
            def __init__(self, name, names):
                self.name = name
                self.columns = [_Col(n) for n in names]

        class _Catalog:
            def get_table(self, t):
                return _Meta(t, _cols_for_table.get(t, []))

        # The planner also touches indexer when a sort key uses an
        # index expression; pass ``None`` so it falls back to a seq scan.
        return list(
            result_columns(_plan(stmt, _Catalog(), None)) or []
        )


class _StubDatabase:
    """Legacy stub (no real column resolution) — keeps col{i} fallback."""

    def __init__(self) -> None:
        self.return_rows = None
        self.calls: list = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.return_rows is None:
            return [(1,)]
        return self.return_rows


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _header_columns(frames: list) -> list:
    """Return the ``[(name, type_code), ...]`` from the first RESULT_HEADER."""
    for f in frames:
        if f.type == MessageType.RESULT_HEADER:
            return ResultHeader.from_frame(f).columns
    raise AssertionError("no RESULT_HEADER in frames")


# --------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------


class TestResultHeaderRealColumnNames:
    """Handler emits real column names when the DB exposes them."""

    def test_select_id_name_age_returns_id_name_age(self):
        db = _RealDatabase({"users": ["id", "name", "age"]})
        msg = Query(sql="SELECT id, name, age FROM users")
        frames = _run(dispatch_message(msg, db))
        names = [name for name, _ in _header_columns(frames)]
        assert names == ["id", "name", "age"], (
            f"expected real column names, got {names!r}"
        )
        # Row tuples must align positionally with the new column names.
        rows = [
            ResultRow.from_frame(f).values
            for f in frames
            if f.type == MessageType.RESULT_ROW
        ]
        assert rows, "expected at least one RESULT_ROW"
        assert len(rows[0]) == len(names), (
            f"row width {len(rows[0])} != header width {len(names)}"
        )

    def test_select_star_returns_table_columns_in_declared_order(self):
        db = _RealDatabase({"users": ["id", "name", "age"]})
        msg = Query(sql="SELECT * FROM users")
        frames = _run(dispatch_message(msg, db))
        names = [name for name, _ in _header_columns(frames)]
        assert names == ["id", "name", "age"], (
            f"SELECT * should expand to table columns, got {names!r}"
        )

    def test_select_count_returns_aggregate_label(self):
        db = _RealDatabase({"users": ["id", "name", "age"]})
        msg = Query(sql="SELECT COUNT(*) FROM users")
        frames = _run(dispatch_message(msg, db))
        names = [name for name, _ in _header_columns(frames)]
        # COUNT(*) renders as the aggregate label string.
        assert names == ["COUNT(*)"], (
            f"COUNT(*) should return the aggregate label, got {names!r}"
        )

    def test_select_with_where_still_returns_real_names(self):
        db = _RealDatabase({"users": ["id", "name", "age"]})
        msg = Query(sql="SELECT name FROM users WHERE id = 1")
        frames = _run(dispatch_message(msg, db))
        names = [name for name, _ in _header_columns(frames)]
        assert names == ["name"]

    def test_fallback_to_col_i_when_db_has_no_result_columns_helper(self):
        """Legacy stubs without ``result_columns_for`` keep the col{i} fallback."""
        db = _StubDatabase()
        db.return_rows = [(1, "Alice"), (2, "Bob")]
        msg = Query(sql="SELECT id, name FROM users")
        frames = _run(dispatch_message(msg, db))
        names = [name for name, _ in _header_columns(frames)]
        # Falls back to col{i} for backwards compatibility.
        assert names == ["col0", "col1"], (
            f"legacy stub should fall back to col{{i}}, got {names!r}"
        )

    def test_dml_does_not_emit_column_header(self):
        """DML doesn't carry a SELECT projection; no RESULT_HEADER is emitted."""
        db = _RealDatabase({"users": ["id", "name", "age"]})
        msg = Query(sql="INSERT INTO users (id, name) VALUES (1, 'Alice')")
        frames = _run(dispatch_message(msg, db))
        # DML is framed as a single RESULT_DONE — there is no RESULT_HEADER
        # to apply col{i} placeholders to, so the col{i} fallback never
        # fires for non-SELECT statements.
        frame_types = [f.type for f in frames]
        assert MessageType.RESULT_HEADER not in frame_types, (
            f"DML should not emit RESULT_HEADER, got {frame_types!r}"
        )
        assert MessageType.RESULT_DONE in frame_types, (
            f"DML must emit RESULT_DONE, got {frame_types!r}"
        )


class TestWireRoundtripWithRealNames:
    """End-to-end: send a Hello + Query, read RESULT_HEADER from the bytes."""

    def test_session_runner_returns_real_names_for_select(self):
        db = _RealDatabase({"users": ["id", "name", "age"]})
        sink = io.BytesIO()
        FrameWriter(sink).write_frame(Hello(client="py-1.0").to_frame())
        FrameWriter(sink).write_frame(
            Query(sql="SELECT id, name, age FROM users").to_frame()
        )
        reader = FrameReader(io.BytesIO(sink.getvalue()))
        session = ServerSession(reader=reader, db=db)
        # Run handshake then dispatch.
        _run(session.run_once())  # Ok
        frames = _run(session.run_once())
        names = [name for name, _ in _header_columns(frames)]
        assert names == ["id", "name", "age"]
