"""Tests for the B-tree index (T-4.1 leaf + T-4.2 split + internal nodes).

Covers REQ-IDX-1 (leaf part) and the split / internal-node / persistence
extensions added in T-4.2:

* leaves contain (key, rid) pairs sorted ascending by key, with
  sibling-chain pointers for forward scan;
* internal nodes contain (separator_key, child_pid) entries;
* ``_write_leaf`` / ``_write_internal`` raise :class:`BTreeOverflowError`
  when the entry would not fit in the page, and the split algorithm
  catches that signal and re-tries with two pages.
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


# --- T-4.2: split + internal nodes --------------------------------------


# --- NIT #1 regression: tail-leaf sentinel -----------------------------


def test_tail_leaf_persists_no_next_sentinel(tmp_db_path):
    """NIT #1: a freshly-persisted tail leaf must carry ``NO_NEXT``, not 0.

    With the T-4.1 code, a fresh leaf's on-disk ``next_leaf_pid`` is 0
    (because the page was zero-filled).  After the split work in T-4.2
    introduces siblings, the sibling chain has to use ``NO_NEXT``
    (``0xFFFFFFFF``) as the tail marker or chain-walking code will read
    page 0 as a valid sibling.
    """
    from tinydb.index.btree import BTreeIndex, NO_NEXT, _read_leaf

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        idx = BTreeIndex(p, root_pid=pid, key_type=TypeTag.Int)
        idx.insert(42, Rid(page_id=4, slot_id=0))
        idx.flush()
    finally:
        p.close()

    p2 = Pager.open(tmp_db_path)
    try:
        leaf = _read_leaf(p2, pid, TypeTag.Int)
        assert leaf.next_leaf_pid == NO_NEXT
    finally:
        p2.close()


# --- NIT #2 regression: capacity guard + BTreeOverflowError -------------


def test_write_leaf_capacity_guard_raises(tmp_db_path):
    """NIT #2: ``_write_leaf`` raises ``BTreeOverflowError`` when full.

    With 64-char Text keys, each entry is 77 bytes (2 + 69 + 6).  After
    roughly 50 entries the page is full, so 60 entries must overflow
    the 4 KB page and the new capacity guard must raise
    :class:`BTreeOverflowError`.
    """
    from tinydb.index.btree import BTreeOverflowError, LeafNode, _write_leaf

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        keys = [f"k{i:064d}" for i in range(60)]
        rids = [Rid(page_id=0, slot_id=i) for i in range(60)]
        leaf = LeafNode(keys=keys, rids=rids)
        with pytest.raises(BTreeOverflowError):
            _write_leaf(p, pid, leaf, TypeTag.Text)
    finally:
        p.close()


def test_btree_overflow_error_subclasses_tinydb_error():
    """``BTreeOverflowError`` must subclass ``TinydbError`` so callers
    can catch all tinydb errors uniformly.
    """
    from tinydb.errors import TinydbError
    from tinydb.index.btree import BTreeOverflowError

    assert issubclass(BTreeOverflowError, TinydbError)


# --- split path: many inserts ------------------------------------------


def test_split_with_many_int_keys_returns_all_in_order(tmp_db_path):
    """Inserting more Int keys than fit on one leaf must split; range returns all.

    A single leaf fits ~240 Int entries; 300 entries force at least one
    split.  After the split, :meth:`range` must still yield every rid
    in ascending key order.
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        for i in range(300):
            idx.insert(i, Rid(page_id=0, slot_id=i))
        result = list(idx.range(0, 1000))
        assert result == [Rid(page_id=0, slot_id=i) for i in range(300)]
    finally:
        p.close()


def test_split_persists_across_reopen(tmp_db_path):
    """After a split, the tree must round-trip through close/reopen."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        idx = BTreeIndex(p, root_pid=pid, key_type=TypeTag.Int)
        for i in range(300):
            idx.insert(i, Rid(page_id=0, slot_id=i))
    finally:
        p.close()

    p2 = Pager.open(tmp_db_path)
    try:
        idx2 = BTreeIndex(p2, root_pid=pid, key_type=TypeTag.Int)
        assert list(idx2.range(0, 1000)) == [
            Rid(page_id=0, slot_id=i) for i in range(300)
        ]
    finally:
        p2.close()


def test_root_becomes_internal_after_split(tmp_db_path):
    """A root-leaf split must allocate a new internal-node root.

    Inserting 100 long-Text keys (each ~80 bytes, so ~60 entries fit on
    one leaf) forces a leaf split.  When the original root leaf splits,
    the BTreeIndex must allocate a fresh page and rewrite the root_pid
    to point at a real internal node.  ``_read_internal`` on the new
    root_pid must yield a node with at least two children.
    """
    from tinydb.index.btree import BTreeIndex, _read_internal

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        idx = BTreeIndex(p, root_pid=pid, key_type=TypeTag.Text)
        for i in range(100):
            idx.insert(f"key-{i:060d}", Rid(page_id=0, slot_id=i))
        # The root_pid must have moved to a real internal node.
        assert idx._root_pid != pid
        internal = _read_internal(p, idx._root_pid)
        assert len(internal.children) >= 2
        # And everything still reads back correctly.
        result = list(idx.range("a", "z"))
        assert len(result) == 100
    finally:
        p.close()


def test_random_insert_order_preserves_range_order(tmp_db_path):
    """Insert keys in random order; ``range`` returns rids sorted by key.

    A tree-walking insert must keep the keys sorted regardless of the
    order in which the caller supplied them.  This guards against an
    off-by-one in the split / rebalance logic that would scramble the
    in-order invariant.
    """
    import random

    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        # 300 Int keys → forces at least one split.  Use 300+ so the
        # test really exercises the split path (which is where ordering
        # regressions would show up).
        keys = list(range(300))
        random.seed(0xC0FFEE)
        random.shuffle(keys)
        for k in keys:
            idx.insert(k, Rid(page_id=0, slot_id=k))
        result = list(idx.range(0, 1000))
        assert result == [Rid(page_id=0, slot_id=k) for k in range(300)]
    finally:
        p.close()


# --- re-export surface --------------------------------------------------


def test_module_reexports_internal_node_and_overflow_error():
    """``tinydb.index`` must re-export ``InternalNode`` and
    ``BTreeOverflowError`` so downstream code can ``from tinydb.index
    import InternalNode``."""
    from tinydb.index import BTreeIndex as BTreeIndexA
    from tinydb.index import BTreeOverflowError, InternalNode
    from tinydb.index.btree import (
        BTreeOverflowError as BTreeOverflowErrorB,
        InternalNode as InternalNodeB,
    )

    assert InternalNode is InternalNodeB
    assert BTreeOverflowError is BTreeOverflowErrorB
    assert BTreeIndexA.__module__ == "tinydb.index.btree"