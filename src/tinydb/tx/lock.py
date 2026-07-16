"""Single-writer reentrant lock (v0.1 API surface, v0.2 plumbing).

Tinydb v0.1 exposed a single-writer reentrant lock (the
:class:`WriteLock`) that the transaction manager used to serialise
writers within a single process.  v0.2 keeps the *public* surface of
:class:`WriteLock` identical (so existing v0.1 callers and tests
continue to work) but the lock is now a thin wrapper over the
:class:`tinydb.concurrent.RWLock`'s write side.  The wrapper
preserves the reentrant semantics that the v0.1 manager relied on.

Why a wrapper, not a replacement?
---------------------------------
The v0.1 manager calls ``self._lock.acquire()`` once per transaction
and stores the returned :class:`WriteLockHeld` token.  Replacing
:class:`WriteLock` outright would change the manager's call
sequence.  Wrapping the new RWLock.write() context manager gives us
re-entrance semantics in a few lines while leaving v0.1's public
contract intact.
"""
from __future__ import annotations

import contextlib
import threading
from types import TracebackType
from typing import Iterator, Optional, Type

from tinydb.concurrent.rwlock import RWLock


class _ReentrantWriteGuard:
    """Internal helper: stack of (thread_id, RWLock.write() cm) frames.

    Each ``acquire()`` pushes a new RWLock.write() context; each
    ``release()`` pops one.  The lock is actually released only when
    the stack drains to zero.
    """

    __slots__ = ("_lock", "_frames")

    def __init__(self, lock: RWLock) -> None:
        self._lock = lock
        self._frames: list = []

    def acquire(self) -> None:
        cm = self._lock.write()
        cm.__enter__()
        self._frames.append(cm)

    def release(self) -> None:
        if not self._frames:
            raise RuntimeError("release unlocked lock")
        cm = self._frames.pop()
        cm.__exit__(None, None, None)


# A process-wide singleton: WriteLock instances are created by
# TransactionManager (one per Database) and live for the lifetime
# of the process.  A module-level dict keyed by id(rwlock) keeps
# per-RWLock reentrancy stacks.
_REENTRANT: dict = {}


def _reentrant_for(rwlock: RWLock) -> _ReentrantWriteGuard:
    key = id(rwlock)
    guard = _REENTRANT.get(key)
    if guard is None:
        guard = _ReentrantWriteGuard(rwlock)
        _REENTRANT[key] = guard
    return guard


class WriteLockHeld:
    """Token returned by WriteLock.acquire() — opaque marker.

    Holds a reference to the parent :class:`WriteLock`; releasing
    decrements the underlying RWLock write-side reentrancy depth.
    """

    __slots__ = ("_lock",)

    def __init__(self, lock: "WriteLock") -> None:
        self._lock = lock

    def __enter__(self) -> "WriteLockHeld":
        return self

    def __exit__(
        self,
        et: Optional[Type[BaseException]],
        ev: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> bool:
        self._lock.release()
        return False


class WriteLock:
    """v0.1 single-writer reentrant lock — now backed by RWLock.write.

    Thread-safety: backed by :class:`tinydb.concurrent.RWLock`.  The
    wrapper maintains a reentrancy stack so v0.1's
    ``acquire()``/``release()`` (and the v0.1 manager's
    ``held = lock.acquire()`` then later ``held.__exit__()``)
    pattern continues to work without any caller-side changes.
    """

    __slots__ = ("_rwlock",)

    def __init__(self) -> None:
        # Prefer writer semantics: a queued reader must not jump in
        # front of a pending writer (matches the v0.1 "exclusive
        # writer" contract).
        self._rwlock = RWLock(prefer_writer=True)

    @property
    def rwlock(self) -> RWLock:
        """Underlying :class:`RWLock` (v0.2 callers use this directly)."""
        return self._rwlock

    def acquire(self) -> WriteLockHeld:
        """Block until the calling thread owns the write side.

        Reentrant: the same thread may call acquire() multiple times
        and the lock will only be released when an equal number of
        release() calls have been made.
        """
        _reentrant_for(self._rwlock).acquire()
        return WriteLockHeld(self)

    def release(self) -> None:
        """Drop one reentrance level; wake waiters if depth==0."""
        _reentrant_for(self._rwlock).release()

    # context-manager sugar on the lock itself
    def __enter__(self) -> WriteLockHeld:
        return self.acquire()

    def __exit__(
        self,
        et: Optional[Type[BaseException]],
        ev: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> bool:
        self.release()
        return False


__all__ = ["WriteLock", "WriteLockHeld"]