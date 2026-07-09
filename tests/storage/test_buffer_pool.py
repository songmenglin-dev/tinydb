"""Tests for the BufferPool — LRU cache layer above the Pager.

T-2.2 RED phase.  Covers REQ-STO-3 (LRU cache) and REQ-STO-8 (flush on commit).
"""

from __future__ import annotations

import pytest

from tinydb.storage.buffer_pool import BufferPool
from tinydb.storage.pager import PAGE_SIZE, Pager


# --- helpers ------------------------------------------------------------


def _spy_io(pager: Pager) -> dict:
    """Wrap Pager.read_page / write_page to count calls.

    Returns a mutable counter dict so tests can assert on the number of
    disk accesses the BufferPool performs.  We patch the *instance* (not
    the class) so other tests sharing a Pager class are not affected.
    """
    counter: dict = {"reads": 0, "writes": 0}
    orig_read = pager.read_page
    orig_write = pager.write_page

    def counted_read(pid):
        counter["reads"] += 1
        return orig_read(pid)

    def counted_write(pid, data):
        counter["writes"] += 1
        return orig_write(pid, data)

    pager.read_page = counted_read  # type: ignore[method-assign]
    pager.write_page = counted_write  # type: ignore[method-assign]
    return counter


class _StubPager:
    """Minimal Pager-like stub.

    Tracks calls so tests that don't need a real on-disk file can still
    observe BufferPool behaviour.  Stands in for the ``Pager`` protocol
    (read_page, write_page) without touching the filesystem.
    """

    def __init__(self) -> None:
        self.reads: list = []
        self.writes: list = []

    def read_page(self, pid: int) -> bytes:
        self.reads.append(pid)
        return b"\x00" * PAGE_SIZE

    def write_page(self, pid: int, data: bytes) -> None:
        self.writes.append((pid, data))


# --- core behaviour -----------------------------------------------------


def test_fetch_returns_page_content(tmp_db_path):
    """fetch_page returns the bytes that the Pager has on disk."""
    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        p.write_page(pid, b"\xAB" * PAGE_SIZE)
        bp = BufferPool(p, capacity=8)
        assert bp.fetch_page(pid) == b"\xAB" * PAGE_SIZE
    finally:
        p.close()


def test_repeat_fetch_is_cache_hit(tmp_db_path):
    """REQ-STO-3: same page read twice — second fetch must not hit disk."""
    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        p.write_page(pid, b"\xCD" * PAGE_SIZE)
        counter = _spy_io(p)
        bp = BufferPool(p, capacity=8)
        bp.fetch_page(pid)
        bp.fetch_page(pid)
        assert counter["reads"] == 1
    finally:
        p.close()


def test_distinct_pages_each_load_from_disk(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        pids = [p.allocate_page() for _ in range(3)]
        counter = _spy_io(p)
        bp = BufferPool(p, capacity=8)
        for pid in pids:
            bp.fetch_page(pid)
        assert counter["reads"] == 3
    finally:
        p.close()


# --- LRU eviction -------------------------------------------------------


def test_lru_evicts_least_recently_used(tmp_db_path):
    """REQ-STO-3: when the pool is full, the LRU page is evicted."""
    p = Pager.open(tmp_db_path)
    try:
        pids = [p.allocate_page() for _ in range(3)]
        counter = _spy_io(p)
        bp = BufferPool(p, capacity=2)
        bp.fetch_page(pids[0])  # miss
        bp.fetch_page(pids[1])  # miss (capacity now 2)
        bp.fetch_page(pids[2])  # miss → evicts pids[0] (LRU)
        bp.fetch_page(pids[0])  # miss (was evicted)
        assert counter["reads"] == 4
    finally:
        p.close()


def test_recent_use_protects_from_eviction(tmp_db_path):
    """Re-fetching a page promotes it to MRU and protects from later eviction.

    Scenario with capacity=2 and 4 distinct pages::

        fetch(0) → miss  read=1  cache=[0]
        fetch(1) → miss  read=2  cache=[0, 1]
        fetch(0) → hit            cache=[1, 0]   (0 promoted to MRU)
        fetch(2) → miss  read=3  cache=[0, 2]   (1 evicted as LRU)
        fetch(0) → hit            cache=[2, 0]   (0 promoted again)
        fetch(3) → miss  read=4  cache=[0, 3]   (2 evicted as LRU)
        fetch(0) → hit            cache=[3, 0]   (0 survived both evictions)

    So pids[0] suffers 0 misses; pids[1], pids[2], pids[3] each miss once.
    """
    p = Pager.open(tmp_db_path)
    try:
        pids = [p.allocate_page() for _ in range(4)]
        counter = _spy_io(p)
        bp = BufferPool(p, capacity=2)
        bp.fetch_page(pids[0])  # miss
        bp.fetch_page(pids[1])  # miss
        bp.fetch_page(pids[0])  # hit  (promote to MRU)
        bp.fetch_page(pids[2])  # miss (evicts pids[1])
        bp.fetch_page(pids[0])  # hit  (promote again)
        bp.fetch_page(pids[3])  # miss (evicts pids[2]; pids[0] survives)
        bp.fetch_page(pids[0])  # hit  (still present)
        assert counter["reads"] == 4
    finally:
        p.close()


# --- capacity and default -----------------------------------------------


def test_default_capacity_is_64():
    """REQ-STO-3 default buffer pool size is 64 pages."""
    bp = BufferPool(_StubPager())  # type: ignore[arg-type]
    assert bp.capacity == 64


def test_custom_capacity_is_stored():
    bp = BufferPool(_StubPager(), capacity=16)  # type: ignore[arg-type]
    assert bp.capacity == 16


# --- flush (REQ-STO-8) --------------------------------------------------


def test_write_then_flush_persists_via_pager(tmp_db_path):
    """REQ-STO-8: dirty pages flush through to the Pager on flush_all."""
    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        counter = _spy_io(p)
        bp = BufferPool(p, capacity=4)
        bp.fetch_page(pid)
        assert counter["writes"] == 0
        bp.write_page(pid, b"\xEE" * PAGE_SIZE)
        assert counter["writes"] == 0  # still only cached
        bp.flush_all()
        assert counter["writes"] == 1  # now persisted
        assert p.read_page(pid) == b"\xEE" * PAGE_SIZE
    finally:
        p.close()


def test_flush_with_no_dirty_pages_is_noop(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        counter = _spy_io(p)
        bp = BufferPool(p, capacity=4)
        bp.flush_all()
        assert counter["writes"] == 0
    finally:
        p.close()


def test_mark_dirty_triggers_flush_for_cached_page(tmp_db_path):
    """mark_dirty(pid) flags an already-cached page for the next flush."""
    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        counter = _spy_io(p)
        bp = BufferPool(p, capacity=4)
        bp.fetch_page(pid)
        bp.mark_dirty(pid)  # caller mutated via Pager outside; tell cache
        bp.flush_all()
        assert counter["writes"] == 1
    finally:
        p.close()


# --- IMPROVE phase: stats() --------------------------------------------


def test_stats_track_hits_and_misses(tmp_db_path):
    """stats() exposes the cache hit/miss counters (IMPROVE)."""
    p = Pager.open(tmp_db_path)
    try:
        pids = [p.allocate_page() for _ in range(2)]
        bp = BufferPool(p, capacity=4)
        bp.fetch_page(pids[0])  # miss
        bp.fetch_page(pids[0])  # hit
        bp.fetch_page(pids[1])  # miss
        stats = bp.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
    finally:
        p.close()
