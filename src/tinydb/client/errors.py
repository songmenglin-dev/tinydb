"""Client-side exception hierarchy (v0.3, REQ-CLI-1/2/6/7)."""
from __future__ import annotations

from tinydb.errors import TinydbError


class ClientError(TinydbError):
    """Base class for client-side errors."""


class ConnectionError(ClientError):
    """Raised when the server connection is refused, drops, or cannot
    be re-established after the configured number of retries."""


class TimeoutError(ClientError):
    """Raised when a request exceeds its timeout."""


class IntegrityError(ClientError):
    """Raised when a server-side constraint violation aborts a batch."""


class ProtocolError(ClientError):
    """Raised when the server returns a malformed response."""


__all__ = [
    "ClientError",
    "ConnectionError",
    "TimeoutError",
    "IntegrityError",
    "ProtocolError",
]
