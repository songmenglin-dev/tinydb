"""Single-writer write lock with reentrance.

Tinydb v0.1 is a single-process, single-connection database (per
spec-superflow DP-0 scope fence — no concurrent writers in
v0.1). The WriteLock enforces "at most one active writer" using an
in-process recursion-depth counter on the owning thread.

API
---
    lock = WriteLock()
    with lock.acquire() as held:
        # critical section; `held` is a WriteLockHeld token
        ...

Reentrance: the same thread may acquire the lock multiple times.
Each acquire() increments the depth; release decrements. Only when
depth returns to zero is the lock released. Other threads block
on a Condition.wait().

Non-reentrance from another thread: blocks until the holder
releases.

This is intentionally tiny. We do NOT need:
- Read/write locks (single-process ⇒ no concurrency)
- Fair scheduling (single-process ⇒ not observed)
- Lock timeouts (out of scope for v0.1; documented)
"""
from __future__ import annotations

import threading
from types import TracebackType
from typing import Optional, Type


class WriteLockHeld:
    """Token returned by WriteLock.acquire() — opaque marker.

    Holds a (Lock, depth) pair; releasing decrements depth.
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
    """Single-writer reentrant lock (one writer at a time).

    Thread-safety: lock state is held in self._owner + self._depth +
    self._cond. Multiple writers block on Condition.wait() until the
    owner releases (depth == 0).
    """

    __slots__ = ("_cond", "_owner", "_depth")

    def __init__(self) -> None:
        # Condition wraps a Lock; that Lock protects _owner and _depth.
        self._owner: Optional[int] = None  # thread id
        self._depth: int = 0
        self._cond = threading.Condition()

    def acquire(self) -> WriteLockHeld:
        """Block until the calling thread owns the lock. Reentrant."""
        me = threading.get_ident()
        with self._cond:
            while self._owner is not None and self._owner != me:
                self._cond.wait()
            self._owner = me
            self._depth += 1
        return WriteLockHeld(self)

    def release(self) -> None:
        """Drop one reentrance level; if depth==0, wake the next waiter."""
        me = threading.get_ident()
        with self._cond:
            if self._owner != me or self._depth == 0:
                raise RuntimeError("release unlocked lock or wrong thread")
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
                self._cond.notify_all()

    # context-manager sugar on the lock itself (mirrors acquire/release)
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