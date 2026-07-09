"""Tests for the Heap — slotted-page record store.

T-2.3 RED phase.  Covers REQ-STO-2 (cross-page overflow), REQ-STO-5
(records-in-slots), and REQ-STO-7 (free-space tracking).
"""

from __future__ import annotations

import dataclasses

import pytest

from tinydb.storage.heap import Heap, Rid
from tinydb.storage.pager import PAGE_SIZE, Pager


# --- Rid value type -----------------------------------------------------


def test_rid_equality_and_hashability():
    """Rid is a frozen dataclass — equal Rid instances compare equal and hash the same."""
    a = Rid(page_id=4, slot_id=7)
    b = Rid(page_id=4, slot_id=7)
    c = Rid(page_id=4, slot_id=8)
    d = Rid(page_id=5, slot_id=7)
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
    assert a != d
    # Usable as a set / dict key.
    assert {a, b, c, d} == {a, c, d}


def test_rid_is_frozen():
    """Frozen dataclass — attribute assignment raises FrozenInstanceError."""
    rid = Rid(page_id=0, slot_id=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rid.page_id = 99  # type: ignore[misc]


# --- single-page heap ---------------------------------------------------


def test_insert_returns_rid_and_reads_back(tmp_db_path):
    """Basic roundtrip: insert bytes → read same bytes back via the returned Rid."""
    p = Pager.open(tmp_db_path)
    try:
        heap = Heap(p, table_id=1)
        rid = heap.insert(b"hello")
        assert heap.read(rid) == b"hello"
    finally:
        p.close()


def test_multiple_inserts_get_distinct_rids(tmp_db_path):
    """Each insert returns a Rid that points at a unique (page_id, slot_id) pair."""
    p = Pager.open(tmp_db_path)
    try:
        heap = Heap(p, table_id=1)
        rids = [heap.insert(f"row-{i}".encode()) for i in range(5)]
        # Every Rid is unique.
        assert len(set(rids)) == 5
        # Every Rid reads back its exact byte payload.
        for i, rid in enumerate(rids):
            assert heap.read(rid) == f"row-{i}".encode()
    finally:
        p.close()


def test_read_unknown_rid_returns_none(tmp_db_path):
    """A Rid for a slot we never inserted to reads back as None (empty slot)."""
    p = Pager.open(tmp_db_path)
    try:
        heap = Heap(p, table_id=1)
        # Insert real data first so the page is allocated.
        heap.insert(b"x")
        # A fresh Rid on a slot we didn't touch reads as None.
        ghost = Rid(page_id=4, slot_id=999)
        assert heap.read(ghost) is None
    finally:
        p.close()


# --- delete -------------------------------------------------------------


def test_read_after_delete_returns_none(tmp_db_path):
    """delete(rid) marks the slot empty; subsequent read returns None."""
    p = Pager.open(tmp_db_path)
    try:
        heap = Heap(p, table_id=1)
        rid = heap.insert(b"will be deleted")
        heap.delete(rid)
        assert heap.read(rid) is None
    finally:
        p.close()


def test_delete_one_rid_does_not_affect_others(tmp_db_path):
    """Deleting a record only kills its slot, not its neighbours."""
    p = Pager.open(tmp_db_path)
    try:
        heap = Heap(p, table_id=1)
        keep = [heap.insert(f"k-{i}".encode()) for i in range(3)]
        doomed = heap.insert(b"doomed")
        more = [heap.insert(f"m-{i}".encode()) for i in range(2)]
        heap.delete(doomed)
        assert heap.read(doomed) is None
        # Everyone else is still there.
        for rid in keep + more:
            assert heap.read(rid) is not None
    finally:
        p.close()


# --- scan ---------------------------------------------------------------


def test_scan_yields_only_live_rids(tmp_db_path):
    """scan() emits each live (non-deleted) Rid exactly once, in slot order."""
    p = Pager.open(tmp_db_path)
    try:
        heap = Heap(p, table_id=1)
        rids = [heap.insert(f"row-{i}".encode()) for i in range(8)]
        heap.delete(rids[3])
        heap.delete(rids[5])
        scanned = list(heap.scan())
        expected = [r for i, r in enumerate(rids) if i not in (3, 5)]
        assert scanned == expected
    finally:
        p.close()


# --- cross-page overflow (REQ-STO-2) -----------------------------------


def test_overflow_inserts_land_on_a_fresh_page(tmp_db_path):
    """REQ-STO-2: when a heap page fills, further inserts use a new overflow page."""
    p = Pager.open(tmp_db_path)
    try:
        heap = Heap(p, table_id=1)
        # 200-byte payloads → roughly 18 records per page (header + slots eat space).
        first_pid: int | None = None
        overflowed_at_least_once = False
        for i in range(50):
            rid = heap.insert(b"X" * 200)
            if first_pid is None:
                first_pid = rid.page_id
            elif rid.page_id > first_pid:  # type: ignore[operator]
                overflowed_at_least_once = True
        assert overflowed_at_least_once, "expected at least one overflow page"
        # Tail insert must be readable.
        tail = heap.insert(b"tail")
        assert heap.read(tail) == b"tail"
    finally:
        p.close()


def test_scan_after_overflow_visits_every_page(tmp_db_path):
    """scan() walks the full linked-list of pages and yields every live Rid."""
    p = Pager.open(tmp_db_path)
    try:
        heap = Heap(p, table_id=1)
        rids = [heap.insert(b"X" * 200) for _ in range(60)]
        scanned = list(heap.scan())
        assert scanned == rids
    finally:
        p.close()
