"""tinydb URI parser for CLI client/server mode (v0.3).

The only URI scheme we accept is ``tinydb://host:port/dbname``.  The
database name is optional and currently informational; the underlying
server is bound to a single file at startup.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass(frozen=True)
class TinydbUri:
    """Parsed components of a ``tinydb://`` URI."""

    host: str
    port: int
    database: Optional[str] = None


def parse_uri(uri: str) -> TinydbUri:
    """Parse a ``tinydb://`` URI.

    Raises :class:`ValueError` if the scheme is wrong or the host/port
    are missing.
    """
    if not uri:
        raise ValueError("empty URI")
    parsed = urlparse(uri)
    if parsed.scheme != "tinydb":
        raise ValueError(
            f"unsupported URI scheme: {parsed.scheme!r}; "
            f"expected 'tinydb'"
        )
    host = parsed.hostname
    if not host:
        raise ValueError(f"missing host in URI: {uri!r}")
    port = parsed.port
    if port is None:
        raise ValueError(f"missing port in URI: {uri!r}")
    database = parsed.path.lstrip("/") or None
    return TinydbUri(host=host, port=port, database=database)


__all__ = ["TinydbUri", "parse_uri"]