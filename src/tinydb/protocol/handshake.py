"""HELLO handshake protocol helpers (v0.3, REQ-PROTO-3).

The v0.3 handshake is a no-op authentication placeholder: the client
announces itself with a UTF-8 identifier and the server responds with
its version string.  This module centralises the constants and the
two helper functions so server and client code use the same values.
"""
from __future__ import annotations

from tinydb.protocol.messages import MAX_CLIENT_ID, Hello, Ok

DEFAULT_CLIENT_ID: str = "py-tinydb-0.3.0"
DEFAULT_SERVER_VERSION: str = "tinydb-0.3.0"

CLIENT_ID: str = DEFAULT_CLIENT_ID
SERVER_VERSION: str = DEFAULT_SERVER_VERSION


def perform_client_handshake(client_id: str = DEFAULT_CLIENT_ID) -> Hello:
    """Build the :class:`Hello` message the client sends first.

    Validates length here so the caller can ``except ValueError`` at
    the construction-call boundary rather than during the round trip.
    """
    encoded = client_id.encode("utf-8")
    if len(encoded) > MAX_CLIENT_ID:
        raise ValueError(
            f"client id too long: {len(encoded)} > {MAX_CLIENT_ID} bytes"
        )
    return Hello(client=client_id)


def perform_server_handshake(hello: Hello) -> Ok:
    """Return the :class:`Ok` reply the server sends in response to
    the client's :class:`Hello`.

    Treated as a no-op authentication step in v0.3; the server
    merely echoes its build version.
    """
    return Ok(version=DEFAULT_SERVER_VERSION)


__all__ = [
    "CLIENT_ID",
    "SERVER_VERSION",
    "DEFAULT_CLIENT_ID",
    "DEFAULT_SERVER_VERSION",
    "perform_client_handshake",
    "perform_server_handshake",
]
