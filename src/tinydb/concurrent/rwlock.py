"""Reader/Writer lock built on :class:`threading.Condition`.

Why a hand-rolled RWLock?
-------------------------
Python's :class:`threading` module does not include a built-in
read/write lock. The standard idiom is one Condition + two counters
``_readers`` (active readers) and ``_writers_waiting`` (writers
blocked waiting for the lock); the writer itself is not counted — it
is simply the *absence* of a current owner.

Write-preferring (default)
--------------------------
With ``prefer_writer=True``, once a writer calls :meth:`acquire_write`
subsequent readers must wait until that writer has run. This avoids
the classic "writer starvation" failure where a steady stream of
readers keeps a writer perpetually queued.

Non-reentrant: a thread that holds the write lock cannot recursively
acquire the read or write lock again. The transaction manager is
structured so the lock is acquired exactly once per transaction.

API
---
    lock = RWLock()
    with lock.read():
        ...   # multiple threads may be inside concurrently
    with lock.write():
        ...   # exclusive; readers and writers all block
"""
from __future__ import annotations

import contextlib
import threading
import time
from typing import Iterator, Optional


class RWLock:
    """Writer-preferring reader/writer lock.

    Parameters
    ----------
    prefer_writer:
        When ``True`` (the default), once a writer is waiting new
        readers must wait until the writer acquires and releases the
        lock. This prevents writer starvation under heavy read load.
    """

    __slots__ = (
        "_cond",
        "_readers",
        "_writer",
        "_writers_waiting",
        "_prefer_writer",
    )

    def __init__(self, *, prefer_writer: bool = True) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers: int = 0
        self._writer: Optional[int] = None  # thread id, or None
        self._writers_waiting: int = 0
        self._prefer_writer = prefer_writer

    # -- introspection (handy for tests) -------------------------------

    @property
    def readers(self) -> int:
        """Number of threads currently holding the read lock."""
        with self._cond:
            return self._readers

    @property
    def is_writer_held(self) -> bool:
        """``True`` if a writer currently holds the exclusive lock."""
        with self._cond:
            return self._writer is not None

    # -- core API ------------------------------------------------------

    def acquire_read(self, timeout: Optional[float] = None) -> bool:
        """Acquire the lock for reading.

        Returns ``True`` if acquired, ``False`` if ``timeout`` expired
        before acquisition. Multiple threads may hold the read lock
        concurrently; this method blocks while a writer is active or
        (when ``prefer_writer`` is set) while a writer is waiting.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while self._writer is not None or (
                self._prefer_writer and self._writers_waiting > 0
            ):
                if deadline is None:
                    self._cond.wait()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self._cond.wait(remaining)
            self._readers += 1
            return True

    def release_read(self) -> None:
        """Release one read hold. Wakes a waiting writer if present."""
        with self._cond:
            if self._readers <= 0 or self._writer is not None:
                raise RuntimeError("release_read() without matching acquire_read")
            self._readers -= 1
            if self._readers == 0:
                # Wake all so a queued writer and any waiting readers
                # can race for the now-free lock.
                self._cond.notify_all()

    def acquire_write(self, timeout: Optional[float] = None) -> bool:
        """Acquire the lock for writing.

        Returns ``True`` if acquired, ``False`` if ``timeout`` expired.
        Waits until all readers have released and (if it was first in
        line) until the previous writer has released.
        """
        me = threading.get_ident()
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            self._writers_waiting += 1
            try:
                while self._readers > 0 or self._writer is not None:
                    if deadline is None:
                        self._cond.wait()
                    else:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return False
                        self._cond.wait(remaining)
                self._writer = me
                return True
            finally:
                self._writers_waiting -= 1

    def release_write(self) -> None:
        """Release the exclusive hold. Wakes all waiters."""
        me = threading.get_ident()
        with self._cond:
            if self._writer != me:
                raise RuntimeError("release_write() by non-holder or unlocked")
            self._writer = None
            self._cond.notify_all()

    # -- context-manager sugar -----------------------------------------

    @contextlib.contextmanager
    def read(self) -> Iterator[None]:
        if not self.acquire_read():
            raise TimeoutError("RWLock.acquire_read timed out")
        try:
            yield
        finally:
            self.release_read()

    @contextlib.contextmanager
    def write(self) -> Iterator[None]:
        if not self.acquire_write():
            raise TimeoutError("RWLock.acquire_write timed out")
        try:
            yield
        finally:
            self.release_write()


__all__ = ["RWLock"]