"""Per-page free-byte tracker used by the Heap.

The Heap pages are not pre-sized — records push the data area forward
from the page header while slots grow backwards from the end.  Whenever
the Heap inserts or deletes a record it tells the
:class:`FreeSpaceMap` how many free bytes each page has so the next
insert can pick an existing page with room before allocating a new one.

This is intentionally a thin wrapper around a dict.  v0.1 caches pages
in a :class:`~tinydb.storage.buffer_pool.BufferPool` that already does
its own LRU eviction, so we do not need a sophisticated policy here.
"""

from __future__ import annotations

from typing import Dict, Optional


class FreeSpaceMap:
    """Tracks available bytes on each data page known to a Heap."""

    def __init__(self) -> None:
        # page_id -> free_bytes (bytes between data-end and slot table start).
        self._entries: Dict[int, int] = {}

    # -- mutations -------------------------------------------------------

    def update(self, page_id: int, free_bytes: int) -> None:
        """Set the free-byte count for ``page_id`` (overwrites previous)."""
        if free_bytes < 0:
            raise ValueError(f"free_bytes must be >= 0, got {free_bytes}")
        self._entries[page_id] = free_bytes

    def remove(self, page_id: int) -> None:
        """Forget a page (e.g. after the Heap hands it back to the free list)."""
        self._entries.pop(page_id, None)

    # -- queries ---------------------------------------------------------

    def find_with_space(self, needed: int) -> Optional[int]:
        """Return any page_id with at least ``needed`` free bytes, or None.

        Iteration order is insertion order; the first fitting page is
        returned.  This is good enough for v0.1 — a B-tree index will
        funnel inserts into a more focused set of pages anyway.
        """
        for pid, free_bytes in self._entries.items():
            if free_bytes >= needed:
                return pid
        return None

    def free_bytes(self, page_id: int) -> Optional[int]:
        """Return the recorded free bytes for ``page_id``, or None."""
        return self._entries.get(page_id)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, page_id: object) -> bool:
        return page_id in self._entries


__all__ = ["FreeSpaceMap"]
