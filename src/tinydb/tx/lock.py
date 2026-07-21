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
    """Internal helper: per-thread reentrancy stack over :class:`RWLock`.

    Each ``acquire()`` pushes one frame onto the current thread's
    stack; the underlying :class:`RWLock` write side is taken only
    on the *first* entry from a given thread.  ``release()`` pops
    one frame; the underlying RWLock is released only when the
    current thread's stack drains to zero.

    A fresh thread that calls ``acquire()`` acquires the underlying
    RWLock.write() once and stacks a frame.  The same thread may
    then call ``acquire()`` / ``release()`` repeatedly without
    blocking on its own lock (the underlying RWLock is
    non-reentrant, so without this guard the second acquire from
    the same thread would deadlock).

    Thread-safety note: the per-thread stack is guarded by a single
    threading.Lock; acquire/release are short critical sections so
    contention is negligible.  The RWLock itself enforces mutual
    exclusion across threads.
    """

    __slots__ = ("_lock", "_mutex", "_stacks")

    def __init__(self, lock: RWLock) -> None:
        self._lock = lock
        self._mutex = threading.Lock()
        # Map: thread_id -> int depth.
        self._stacks: dict = {}

    def acquire(self) -> None:
        me = threading.get_ident()
        # Fast path: re-entry by the same thread.  We must drop
        # `_mutex` BEFORE taking the underlying RWLock; otherwise a
        # sibling thread's release could deadlock on `_mutex` while
        # blocking on the RWLock that we hold-and-wait-on.
        with self._mutex:
            entry = self._stacks.get(me)
        if entry is not None:
            depth, cm = entry
            with self._mutex:
                self._stacks[me] = (depth + 1, cm)
            return
        # First entry from this thread — take the underlying
        # RWLock.  cm.__enter__() blocks if a different thread
        # holds it; we are NOT holding _mutex at this point so the
        # sibling can still release.
        cm = self._lock.write()
        cm.__enter__()
        with self._mutex:
            entry = self._stacks.get(me)
            if entry is None:
                self._stacks[me] = (1, cm)
            else:
                # Another thread? No, ``me`` is this thread's id, so
                # we can only see None or a tuple here.  Defensive:
                # merge depths.
                depth, prior_cm = entry
                self._stacks[me] = (depth + 1, prior_cm)
                # The freshly-acquired cm is for the OUTER frame; the
                # INNER frames stack on the prior_cm.  But because the
                # prior_cm was already entered by another caller of
                # this thread, we should NOT have entered a fresh cm.
                # Discard the unused one to keep depth tracking clean.
                cm.__exit__(None, None, None)

    def release(self) -> None:
        me = threading.get_ident()
        with self._mutex:
            entry = self._stacks.get(me)
            if entry is None:
                raise RuntimeError("release unlocked lock")
            depth, cm = entry
            new_depth = depth - 1
            if new_depth == 0:
                del self._stacks[me]
            else:
                self._stacks[me] = (new_depth, cm)
        if new_depth == 0:
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