"""LRU page cache above the :class:`Pager`.

REQ coverage:
* REQ-STO-3 — fixed-capacity LRU cache, default 64 pages; second read of
  the same page hits the cache without disk I/O.
* REQ-STO-8 — :meth:`flush_all` writes every dirty cached page through to
  the underlying Pager (transaction COMMIT path).

Design
------
A single ``OrderedDict`` maps ``page_id`` to ``bytes``.  The dict's
insertion order is the recency order: the **front** (oldest / first
inserted) is the LRU page, the **back** (newest) is the MRU page.  On a
hit we :py:meth:`~collections.OrderedDict.move_to_end`; on a miss when
the cache is full we :py:meth:`~collections.OrderedDict.popitem` with
``last=False`` to drop the LRU.

Dirty pages are pinned to the cache: before evicting a dirty entry we
flush it through to the Pager so the caller never silently loses a
dirty write.

Thread-safety: not thread-safe — matches the v0.1 single-writer fence.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict


class BufferPool:
    """Fixed-capacity LRU cache of pages in front of a Pager.

    The Pager is duck-typed: it must provide ``read_page(pid)`` and
    ``write_page(pid, data)``.  This lets tests substitute a stub Pager
    while production code passes the real
    :class:`tinydb.storage.pager.Pager`.
    """

    def __init__(self, pager: Any, capacity: int = 64) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        self._pager = pager
        self._capacity = capacity
        # page_id -> bytes. Insertion order = recency: front=LRU, back=MRU.
        self._cache: "OrderedDict[int, bytes]" = OrderedDict()
        # Dirty page ids. Flushed on flush_all() or before eviction.
        self._dirty: "set[int]" = set()
        # Counters for stats(). Plain ints — no stdlib Counter overhead.
        self._hits = 0
        self._misses = 0

    # -- introspection ----------------------------------------------------

    @property
    def capacity(self) -> int:
        """Maximum pages the cache may hold."""
        return self._capacity

    def __len__(self) -> int:
        return len(self._cache)

    # -- core API ---------------------------------------------------------

    def fetch_page(self, pid: int) -> bytes:
        """Return the cached bytes for ``pid``.

        On a cache hit the page is promoted to MRU and no disk I/O occurs.
        On a miss the page is loaded from the Pager; if the cache is full
        the LRU page is evicted (and flushed first if dirty).
        """
        cached = self._cache.get(pid)
        if cached is not None:
            self._cache.move_to_end(pid)
            self._hits += 1
            return cached
        # Miss — load from Pager.
        self._misses += 1
        data = self._pager.read_page(pid)
        self._admit(pid, data)
        return data

    def write_page(self, pid: int, data: bytes) -> None:
        """Overwrite the cached copy of ``pid`` and mark it dirty.

        If ``pid`` is not already cached the page is admitted (which may
        evict the LRU).  The bytes will be written through to the Pager
        on the next :meth:`flush_all`.
        """
        if pid in self._cache:
            self._cache[pid] = data
            self._cache.move_to_end(pid)
        else:
            self._admit(pid, data)
        self._dirty.add(pid)

    def mark_dirty(self, pid: int) -> None:
        """Flag an already-cached page as dirty for the next flush.

        Use this when the caller has mutated the on-disk bytes directly
        via the underlying Pager (bypassing :meth:`write_page`) and wants
        the cache to remember the change for the next commit.
        """
        if pid not in self._cache:
            raise ValueError(
                f"page {pid} is not in the cache; fetch it before mark_dirty"
            )
        self._dirty.add(pid)

    def flush_all(self) -> None:
        """Write every dirty cached page through to the Pager.

        Clears the dirty set as a side-effect; the cached copy is kept
        (it is now identical to the on-disk copy).
        """
        for pid, data in self._cache.items():
            if pid in self._dirty:
                self._pager.write_page(pid, data)
                self._dirty.discard(pid)

    # -- IMPROVE ----------------------------------------------------------

    def stats(self) -> Dict[str, int]:
        """Snapshot of hit/miss counters since construction."""
        return {"hits": self._hits, "misses": self._misses}

    # -- internals --------------------------------------------------------

    def _admit(self, pid: int, data: bytes) -> None:
        """Insert ``pid`` at the MRU end, evicting LRU when full.

        Eviction flushes dirty pages first so we never drop a dirty
        write on the floor.
        """
        if len(self._cache) >= self._capacity:
            evicted_pid, evicted_data = self._cache.popitem(last=False)
            if evicted_pid in self._dirty:
                self._pager.write_page(evicted_pid, evicted_data)
                self._dirty.discard(evicted_pid)
        self._cache[pid] = data


__all__ = ["BufferPool"]
