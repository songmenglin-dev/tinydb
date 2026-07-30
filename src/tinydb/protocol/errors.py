"""SQLSTATE error mapping for the wire protocol (v0.3, REQ-PROTO-7).

The server emits one of five SQLSTATE codes in the ``RESULT_ERROR``
/ ``ERR`` payload.  We map each code to a Python exception class so
clients can ``except`` on a meaningful type rather than a string.
"""
from __future__ import annotations

from typing import Dict, Type

from tinydb.protocol.frame import ProtocolError


# --- exception classes --------------------------------------------------


class ConnectionException(ProtocolError):
    """SQLSTATE 08000 — connection error (socket closed, I/O failure)."""


class DataException(ProtocolError):
    """SQLSTATE 22000 — data error (type mismatch, division by zero,
    constraint violation)."""


class TransactionException(ProtocolError):
    """SQLSTATE 25000 — invalid transaction state."""


class SyntaxError(ProtocolError):
    """SQLSTATE 42000 — SQL syntax error."""


class GeneralException(ProtocolError):
    """SQLSTATE HY000 — general / unmapped error."""


# --- code → class map ---------------------------------------------------


SQLSTATE_MAP: Dict[str, Type[ProtocolError]] = {
    "08000": ConnectionException,
    "22000": DataException,
    "25000": TransactionException,
    "42000": SyntaxError,
    "HY000": GeneralException,
}


def map_sqlstate(code: str) -> Type[ProtocolError]:
    """Return the exception class associated with a SQLSTATE ``code``.

    Unknown codes fall back to :class:`GeneralException` so the
    client never sees a bare :class:`KeyError`.
    """
    return SQLSTATE_MAP.get(code, GeneralException)


__all__ = [
    "ConnectionException",
    "DataException",
    "TransactionException",
    "SyntaxError",
    "GeneralException",
    "SQLSTATE_MAP",
    "map_sqlstate",
]
