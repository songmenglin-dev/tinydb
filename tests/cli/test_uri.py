"""Tests for the tinydb CLI URI parser (T-4.1)."""
from __future__ import annotations

import pytest

from tinydb.cli.uri import TinydbUri, parse_uri


def test_parse_uri_minimal():
    """tinydb://host:port parses cleanly."""
    u = parse_uri("tinydb://127.0.0.1:8520")
    assert u == TinydbUri(host="127.0.0.1", port=8520, database=None)


def test_parse_uri_with_database():
    """The /db path component is captured as the database name."""
    u = parse_uri("tinydb://db.example.com:9000/mydb")
    assert u.host == "db.example.com"
    assert u.port == 9000
    assert u.database == "mydb"


def test_parse_uri_empty_raises():
    with pytest.raises(ValueError):
        parse_uri("")


def test_parse_uri_wrong_scheme_raises():
    with pytest.raises(ValueError):
        parse_uri("postgres://localhost:5432/x")


def test_parse_uri_missing_port_raises():
    with pytest.raises(ValueError):
        parse_uri("tinydb://localhost")


def test_parse_uri_missing_host_raises():
    with pytest.raises(ValueError):
        parse_uri("tinydb://:1234")