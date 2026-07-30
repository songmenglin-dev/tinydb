"""Tests for the SQLSTATE error mapping (v0.3, T-1.3)."""
from __future__ import annotations

import pytest

from tinydb.protocol.errors import (
    ConnectionException,
    DataException,
    GeneralException,
    SQLSTATE_MAP,
    SyntaxError,
    TransactionException,
    map_sqlstate,
)


class TestSqlstateMap:
    """The SQLSTATE_MAP covers the five required codes."""

    def test_sqlstate_map_covers_5_codes(self):
        assert set(SQLSTATE_MAP.keys()) == {"08000", "22000", "25000", "42000", "HY000"}

    def test_sqlstate_map_values_are_exception_classes(self):
        for code, cls in SQLSTATE_MAP.items():
            assert isinstance(cls, type)
            assert issubclass(cls, Exception)


class TestMapSqlstate:
    """map_sqlstate returns the matching exception class."""

    def test_sqlstate_to_connection_exception(self):
        assert map_sqlstate("08000") is ConnectionException

    def test_sqlstate_to_data_exception(self):
        assert map_sqlstate("22000") is DataException

    def test_sqlstate_to_transaction_exception(self):
        assert map_sqlstate("25000") is TransactionException

    def test_sqlstate_to_syntax_error(self):
        assert map_sqlstate("42000") is SyntaxError

    def test_sqlstate_to_general_exception(self):
        assert map_sqlstate("HY000") is GeneralException

    def test_sqlstate_unknown_returns_general(self):
        # Unknown code falls back to GenericException (HY000 family).
        assert map_sqlstate("99999") is GeneralException

    def test_sqlstate_empty_returns_general(self):
        assert map_sqlstate("") is GeneralException


class TestExceptionHierarchy:
    """The exception classes inherit from TinydbError via ProtocolError."""

    def test_all_are_protocol_errors(self):
        from tinydb.protocol.errors import ProtocolError
        for cls in (
            ConnectionException,
            DataException,
            TransactionException,
            SyntaxError,
            GeneralException,
        ):
            assert issubclass(cls, ProtocolError)

    def test_can_construct_with_message(self):
        e = ConnectionException("server unreachable")
        assert "server unreachable" in str(e)
