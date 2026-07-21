"""Concurrency primitives for tinydb v0.2.

This package provides three stdlib-only primitives used by the
transaction layer to coordinate concurrent readers and writers:

* :class:`RWLock` — single-process reader/writer lock built on
  :class:`threading.Condition`. Multiple readers may hold the lock
  concurrently; writers hold it exclusively. ``prefer_writer=True``
  avoids writer starvation by queueing new readers behind a waiting
  writer.
* :class:`ProcessLock` — cross-process file lock via ``fcntl.flock``
  on POSIX. On platforms without ``fcntl`` (Windows) it falls back to
  :mod:`msvcrt` ``locking`` when available, or raises a clear
  :class:`ProcessLockUnavailableError` so the caller knows the lock
  cannot be acquired (REQ-CONC-2: never fail silently).
* :class:`DeadlockDetector` — wait-for graph + DFS cycle detector.
  Tracks which transaction is waiting for which holder and reports
  the youngest transaction in a detected cycle so the transaction
  manager can roll it back (REQ-CONC-7).

The package is intentionally stdlib-only (no third-party deps).
"""
from __future__ import annotations

from tinydb.concurrent.deadlock import DeadlockDetector
from tinydb.concurrent.fcntl_lock import (
    ProcessLock,
    ProcessLockUnavailableError,
)
from tinydb.concurrent.rwlock import RWLock

__all__ = [
    "RWLock",
    "ProcessLock",
    "ProcessLockUnavailableError",
    "DeadlockDetector",
]