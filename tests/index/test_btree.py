"""Tests for the B-tree leaf-only index (T-4.1).

Covers REQ-IDX-1 (leaf part): leaves contain (key, rid) pairs sorted
ascending by key, with sibling-chain pointers for forward scan.
"""

from __future__ import annotations

import datetime

import pytest

from tinydb.storage.heap import Rid
from tinydb.storage.pager import PAGE_SIZE, Pager
from tinydb.types.system import TypeTag


# --- helpers ------------------------------------------------------------


def _make_index(pager: Pager, key_type: TypeTag):
    """Allocate a fresh page and wrap it in a BTreeIndex.

    Returns ``(index, root_pid)`` so the caller can reopen at the same pid
    after closing the Pager.
    """
    from tinydb.index.btree import BTreeIndex

    pid = pager.allocate_page()
    return BTreeIndex(pager, root_pid=pid, key_type=key_type), pid


# --- construction -------------------------------------------------------


def test_construct_does_not_touch_page(tmp_db_path):
    """``__init__`` must perform no I/O on the root page (per T-4.1 brief)."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        page_before = p.read_page(pid)
        idx = BTreeIndex(p, root_pid=pid, key_type=TypeTag.Int)
        page_after = p.read_page(pid)
        # No I/O on the root page during construction.
        assert page_before == page_after
        assert page_before == b"\x00" * PAGE_SIZE
        assert idx is not None
    finally:
        p.close()


# --- insert + range ------------------------------------------------------


def test_empty_index_range_yields_nothing(tmp_db_path):
    """An empty leaf returns no rids for any range."""
    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        assert list(idx.range(0, 100)) == []
        assert list(idx.range(-100, 100, inclusive=False)) == []
    finally:
        p.close()


def test_insert_then_range_returns_in_order(tmp_db_path):
    """Insert keys out of order; range returns rids sorted by key."""
    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        # Insert deliberately out of order.
        idx.insert(30, Rid(page_id=4, slot_id=2))
        idx.insert(10, Rid(page_id=4, slot_id=0))
        idx.insert(20, Rid(page_id=4, slot_id=1))
        assert list(idx.range(0, 100)) == [
            Rid(page_id=4, slot_id=0),
            Rid(page_id=4, slot_id=1),
            Rid(page_id=4, slot_id=2),
        ]
    finally:
        p.close()


def test_range_excludes_keys_above_hi(tmp_db_path):
    """Keys strictly greater than ``hi`` are excluded."""
    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        idx.insert(10, Rid(0, 0))
        idx.insert(20, Rid(0, 1))
        idx.insert(30, Rid(0, 2))
        assert list(idx.range(5, 25)) == [Rid(0, 0), Rid(0, 1)]
        assert list(idx.range(5, 10)) == [Rid(0, 0)]
    finally:
        p.close()


def test_range_excludes_keys_below_lo(tmp_db_path):
    """Keys strictly less than ``lo`` are excluded."""
    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        idx.insert(10, Rid(0, 0))
        idx.insert(20, Rid(0, 1))
        idx.insert(30, Rid(0, 2))
        assert list(idx.range(15, 100)) == [Rid(0, 1), Rid(0, 2)]
    finally:
        p.close()


def test_range_inclusive_false_excludes_hi(tmp_db_path):
    """With ``inclusive=False`` the ``hi`` endpoint is excluded."""
    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        idx.insert(10, Rid(0, 0))
        idx.insert(20, Rid(0, 1))
        idx.insert(30, Rid(0, 2))
        assert list(idx.range(10, 20, inclusive=False)) == [Rid(0, 0)]
        assert list(idx.range(10, 20, inclusive=True)) == [Rid(0, 0), Rid(0, 1)]
    finally:
        p.close()


def test_duplicates_under_same_key_all_returned(tmp_db_path):
    """B-tree permits duplicate keys; every rid with that key is returned."""
    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        idx.insert(42, Rid(0, 0))
        idx.insert(42, Rid(0, 1))
        idx.insert(42, Rid(0, 2))
        idx.insert(10, Rid(0, 3))
        assert list(idx.range(42, 42)) == [Rid(0, 0), Rid(0, 1), Rid(0, 2)]
    finally:
        p.close()


# --- persistence --------------------------------------------------------


def test_persistence_after_flush(tmp_db_path):
    """After ``flush()`` closes the Pager, reopening reads the same data back."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        idx = BTreeIndex(p, root_pid=pid, key_type=TypeTag.Int)
        idx.insert(42, Rid(page_id=4, slot_id=7))
        idx.insert(13, Rid(page_id=4, slot_id=8))
        idx.flush()
    finally:
        p.close()

    # Reopen the file: same pid, same data.
    p2 = Pager.open(tmp_db_path)
    try:
        idx2 = BTreeIndex(p2, root_pid=pid, key_type=TypeTag.Int)
        assert list(idx2.range(0, 100)) == [
            Rid(page_id=4, slot_id=8),  # key 13
            Rid(page_id=4, slot_id=7),  # key 42
        ]
    finally:
        p2.close()


def test_insert_persists_without_explicit_flush(tmp_db_path):
    """Insert auto-persists: closing without explicit ``flush()`` is safe."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        idx = BTreeIndex(p, root_pid=pid, key_type=TypeTag.Int)
        idx.insert(99, Rid(page_id=4, slot_id=0))
        # No explicit flush(); insert must persist on its own.
    finally:
        p.close()

    p2 = Pager.open(tmp_db_path)
    try:
        idx2 = BTreeIndex(p2, root_pid=pid, key_type=TypeTag.Int)
        assert list(idx2.range(0, 100)) == [Rid(page_id=4, slot_id=0)]
    finally:
        p2.close()


# --- non-int keys -------------------------------------------------------


def test_text_keys_roundtrip_through_codec(tmp_db_path):
    """Text keys encode/decode correctly via the codec."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Text)
        idx.insert("banana", Rid(0, 0))
        idx.insert("apple", Rid(0, 1))
        idx.insert("cherry", Rid(0, 2))
        assert list(idx.range("a", "z")) == [Rid(0, 1), Rid(0, 0), Rid(0, 2)]
        assert list(idx.range("b", "c", inclusive=False)) == [Rid(0, 0)]
    finally:
        p.close()


def test_date_keys_roundtrip_through_codec(tmp_db_path):
    """Date keys encode/decode correctly via the codec."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Date)
        d1 = datetime.date(2024, 1, 1)
        d2 = datetime.date(2024, 6, 15)
        d3 = datetime.date(2024, 12, 31)
        idx.insert(d2, Rid(0, 0))
        idx.insert(d1, Rid(0, 1))
        idx.insert(d3, Rid(0, 2))
        result = list(idx.range(datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)))
        assert result == [Rid(0, 1), Rid(0, 0), Rid(0, 2)]
    finally:
        p.close()


# --- deferred methods ---------------------------------------------------


def test_delete_raises_not_implemented(tmp_db_path):
    """``delete()`` is deferred to T-4.4 (NotImplementedError placeholder)."""
    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        with pytest.raises(NotImplementedError):
            idx.delete(42, Rid(0, 0))
    finally:
        p.close()


def test_search_raises_not_implemented(tmp_db_path):
    """``search()`` via tree walk is deferred to T-4.3."""
    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        with pytest.raises(NotImplementedError):
            idx.search(42)
    finally:
        p.close()


# --- public surface ----------------------------------------------------


def test_module_reexports_btree_index():
    """``tinydb.index`` must re-export ``BTreeIndex``."""
    from tinydb.index import BTreeIndex as BTreeIndexA
    from tinydb.index.btree import BTreeIndex as BTreeIndexB

    assert BTreeIndexA is BTreeIndexB