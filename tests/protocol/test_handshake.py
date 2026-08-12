"""Tests for the HELLO handshake protocol (v0.3, T-1.5)."""
from __future__ import annotations

import pytest

from tinydb.protocol.handshake import (
    CLIENT_ID,
    DEFAULT_CLIENT_ID,
    DEFAULT_SERVER_VERSION,
    SERVER_VERSION,
    perform_client_handshake,
    perform_server_handshake,
)
from tinydb.protocol.messages import Hello, Ok


class TestHandshakeConstants:
    """Protocol-wide constants used by the handshake."""

    def test_default_client_id(self):
        assert DEFAULT_CLIENT_ID == "py-tinydb-0.3.1"

    def test_default_server_version(self):
        assert DEFAULT_SERVER_VERSION == "tinydb-0.3.1"

    def test_client_id_constant(self):
        assert CLIENT_ID == DEFAULT_CLIENT_ID

    def test_server_version_constant(self):
        assert SERVER_VERSION == DEFAULT_SERVER_VERSION


class TestServerHandshake:
    """perform_server_handshake accepts a Hello and returns Ok."""

    def test_server_handshake_returns_ok(self):
        from tinydb.protocol.messages import Hello
        hello = Hello(client="py-1.0")
        ok = perform_server_handshake(hello)
        assert isinstance(ok, Ok)
        assert ok.version == DEFAULT_SERVER_VERSION

    def test_server_rejects_long_client_id(self):
        # Hello already validates length at construction; do a defensive
        # check from the raw bytes payload as well.
        from tinydb.protocol.frame import Frame
        from tinydb.protocol.messages import MessageType
        bad = Frame(type=MessageType.HELLO, payload=b"x" * 65)
        with pytest.raises(ValueError):
            perform_server_handshake(Hello.from_frame(bad))


class TestClientHandshake:
    """perform_client_handshake builds a Hello message."""

    def test_client_handshake_default(self):
        h = perform_client_handshake()
        assert isinstance(h, Hello)
        assert h.client == DEFAULT_CLIENT_ID

    def test_client_handshake_custom_id(self):
        h = perform_client_handshake(client_id="my-tool/1.2.3")
        assert h.client == "my-tool/1.2.3"

    def test_client_handshake_rejects_long_id(self):
        with pytest.raises(ValueError):
            perform_client_handshake(client_id="x" * 65)
