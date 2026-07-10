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


def test_search_raises_not_implemented(tmp_db_path):
    """Placeholder from T-4.1 era — T-4.3 implements search via tree walk.

    Kept as a smoke test for an empty index: ``search`` must return
    ``[]`` rather than raising.  The T-4.1 ``NotImplementedError`` test
    is now obsolete.
    """
    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        assert idx.search(42) == []
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
    from tinydb.index.btree import BTreeIndex, NO_NEXT
    from tinydb.index.btree_leaf import _read_leaf

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
        leaf = _read_leaf(p2, pid)
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
    from tinydb.index.btree import BTreeIndex
    from tinydb.index.btree_internal import _read_internal

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


# --- T-4.3: search via tree walk + range tree-descent -------------------


def test_search_basic_returns_single_rid(tmp_db_path):
    """``search(key)`` returns the rid inserted under ``key``.

    100 Int keys, no split, single-leaf tree.  ``search(42)`` returns
    the single rid that was inserted under key 42.
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        for i in range(100):
            idx.insert(i, Rid(page_id=0, slot_id=i))
        assert idx.search(42) == [Rid(page_id=0, slot_id=42)]
    finally:
        p.close()


def test_search_duplicate_keys_returns_all_rids(tmp_db_path):
    """``search(key)`` returns every rid under a duplicated key.

    Inserts 3 entries under key 42 plus 4 entries under other keys.
    ``search(42)`` must return all 3 rids (in insertion order).
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        idx.insert(42, Rid(page_id=7, slot_id=0))
        idx.insert(42, Rid(page_id=7, slot_id=1))
        idx.insert(42, Rid(page_id=7, slot_id=2))
        idx.insert(10, Rid(page_id=7, slot_id=3))
        idx.insert(99, Rid(page_id=7, slot_id=4))
        assert idx.search(42) == [
            Rid(page_id=7, slot_id=0),
            Rid(page_id=7, slot_id=1),
            Rid(page_id=7, slot_id=2),
        ]
    finally:
        p.close()


def test_search_key_absent_returns_empty(tmp_db_path):
    """``search(key)`` for a missing key returns an empty list."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        for i in range(50):
            idx.insert(i, Rid(page_id=0, slot_id=i))
        assert idx.search(9999) == []
    finally:
        p.close()


def test_search_after_split_finds_keys_across_leaves(tmp_db_path):
    """After a leaf split, ``search`` walks the tree to find a key in
    any leaf.
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        for i in range(300):
            idx.insert(i, Rid(page_id=0, slot_id=i))
        # Pick a key in a leaf past the split boundary.
        assert idx.search(250) == [Rid(page_id=0, slot_id=250)]
        assert idx.search(0) == [Rid(page_id=0, slot_id=0)]
        assert idx.search(299) == [Rid(page_id=0, slot_id=299)]
    finally:
        p.close()


def test_search_empty_index_returns_empty(tmp_db_path):
    """``search`` on an empty (never-inserted) index returns ``[]``."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        assert idx.search(42) == []
    finally:
        p.close()


def test_range_tree_descent_finds_correct_starting_leaf(tmp_db_path):
    """``range(lo, hi)`` descends to the leftmost leaf whose key may
    satisfy ``lo`` and walks the sibling chain.

    Inserts 300 Int keys, then ``range(50, 60)`` must return rids for
    exactly keys 50..60 (11 entries) in key order.  This proves the
    tree descent landed on the right starting leaf — picking the
    wrong leaf would either miss key 50 or include key 61+.
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        for i in range(300):
            idx.insert(i, Rid(page_id=0, slot_id=i))
        result = list(idx.range(50, 60))
        assert result == [Rid(page_id=0, slot_id=i) for i in range(50, 61)]
    finally:
        p.close()


def test_range_inclusive_false_excludes_hi_in_split_tree(tmp_db_path):
    """With ``inclusive=False``, the ``hi`` endpoint is excluded even
    after a split has produced multiple leaves.
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        for i in range(300):
            idx.insert(i, Rid(page_id=0, slot_id=i))
        result = list(idx.range(50, 60, inclusive=False))
        # 50..59 inclusive (60 excluded).
        assert result == [Rid(page_id=0, slot_id=i) for i in range(50, 60)]
    finally:
        p.close()


def test_range_with_lo_greater_than_hi_returns_empty(tmp_db_path):
    """``range(lo, hi)`` with ``lo > hi`` returns an empty iterator."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        for i in range(50):
            idx.insert(i, Rid(page_id=0, slot_id=i))
        assert list(idx.range(40, 10)) == []
    finally:
        p.close()


def test_range_with_lo_equal_to_hi_returns_single_key(tmp_db_path):
    """``range(lo, lo)`` returns rids for the single key ``lo``."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        for i in range(300):
            idx.insert(i, Rid(page_id=0, slot_id=i))
        result = list(idx.range(123, 123))
        assert result == [Rid(page_id=0, slot_id=123)]
    finally:
        p.close()


# --- NIT #5: _split_internal happy path ---------------------------------


def test_split_internal_happy_path_produces_valid_children(tmp_db_path):
    """NIT #5: an internal-node split must produce a child internal
    node with a well-formed (keys, children) shape.

    200-char Text keys keep leaves small (~19 entries per page), so
    500 inserts force both leaf splits and an internal-node split.
    After the work, the tree has an internal root whose children
    include at least one internal node (the right side of an internal
    split).  Range over the full keyspace must return every entry.
    """
    from tinydb.index.btree import BTreeIndex, InternalNode
    from tinydb.index.btree_internal import _read_internal

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Text)
        for i in range(500):
            idx.insert(f"k-{i:200d}", Rid(page_id=0, slot_id=i))
        # The root must be an internal node after all those splits.
        assert isinstance(idx._root_view, InternalNode)
        root = idx._root_view
        # The internal split path returns (push_up_key, right_pid) where
        # the right child is itself a fresh internal node.  Verify
        # consistency: len(children) == len(keys) + 1.
        assert len(root.keys) + 1 == len(root.children)
        # Verify the tree is well-formed by reading each child and
        # checking that any internal child is also well-formed.
        for child_pid in root.children:
            child = _read_internal(p, child_pid)
            assert len(child.keys) + 1 == len(child.children)
        # And every entry is still reachable via range.
        result = list(idx.range("a", "z"))
        assert len(result) == 500
    finally:
        p.close()


def test_split_internal_data_integrity_through_reopen(tmp_db_path):
    """An internal-node split survives close+reopen with no data loss.

    Same setup as ``test_split_internal_happy_path_*``; after the
    tree has multiple internal levels, closing the Pager and
    reopening must still expose every entry.
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        idx = BTreeIndex(p, root_pid=pid, key_type=TypeTag.Text)
        for i in range(500):
            idx.insert(f"k-{i:200d}", Rid(page_id=0, slot_id=i))
        # Capture the (possibly new) root pid AFTER all splits.
        root_pid = idx._root_pid
    finally:
        p.close()

    p2 = Pager.open(tmp_db_path)
    try:
        idx2 = BTreeIndex(p2, root_pid=root_pid, key_type=TypeTag.Text)
        result = list(idx2.range("a", "z"))
        assert len(result) == 500
        # And the root is still an internal node after reopen.
        from tinydb.index.btree import InternalNode

        assert isinstance(idx2._root_view, InternalNode)
    finally:
        p2.close()


# --- NIT #1: key_type removed from reader signatures -------------------


def test_read_leaf_no_key_type_arg(tmp_db_path):
    """NIT #1: ``_read_leaf`` no longer accepts a ``key_type`` arg.

    The on-wire tag byte is authoritative, so the parameter was
    misleading dead weight.  Calling with the new 2-arg signature
    must still return a valid ``LeafNode``.
    """
    from tinydb.index.btree_leaf import _read_leaf

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        # Construct an index, insert one key, then re-read.
        from tinydb.index.btree import BTreeIndex

        idx = BTreeIndex(p, root_pid=pid, key_type=TypeTag.Int)
        idx.insert(7, Rid(page_id=0, slot_id=0))
        # 2-arg call: no key_type.
        leaf = _read_leaf(p, pid)
        assert leaf.keys == [7]
        assert leaf.rids == [Rid(page_id=0, slot_id=0)]
    finally:
        p.close()


def test_read_internal_no_key_type_arg(tmp_db_path):
    """NIT #1: ``_read_internal`` no longer accepts a ``key_type`` arg."""
    from tinydb.index.btree_internal import _read_internal

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        from tinydb.index.btree import BTreeIndex, InternalNode

        idx = BTreeIndex(p, root_pid=pid, key_type=TypeTag.Int)
        for i in range(300):
            idx.insert(i, Rid(page_id=0, slot_id=i))
        # Root has been promoted to an internal node by the split.
        assert isinstance(idx._root_view, InternalNode)
        # 2-arg call: no key_type.
        internal = _read_internal(p, idx._root_pid)
        assert len(internal.children) >= 2
    finally:
        p.close()


# --- T-4.4: delete + rebalance ------------------------------------------


# --- constants ----------------------------------------------------------


def test_btree_order_constants_exposed():
    """T-4.4: the B-tree order + min-occupancy constants must be exposed
    as class attributes on :class:`BTreeIndex` so tests can import and
    assert against them.
    """
    from tinydb.index.btree import BTreeIndex

    assert BTreeIndex.ORDER == 64
    assert BTreeIndex.MIN_LEAF_ENTRIES == 63
    assert BTreeIndex.MIN_INTERNAL_CHILDREN == 64


# --- basic delete --------------------------------------------------------


def test_delete_basic_removes_one_entry(tmp_db_path):
    """Insert 5, delete 1, the rest remain and are range-able."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        rid_map = {i: Rid(page_id=0, slot_id=i) for i in range(5)}
        for i in range(5):
            idx.insert(i, rid_map[i])
        idx.delete(2, rid_map[2])
        # search confirms removal of key 2.
        assert idx.search(2) == []
        # the other four are still searchable.
        for i in [0, 1, 3, 4]:
            assert idx.search(i) == [rid_map[i]]
        # range across everything returns the surviving 4 in order.
        assert list(idx.range(0, 100)) == [rid_map[i] for i in [0, 1, 3, 4]]
    finally:
        p.close()


def test_delete_last_entry_leaves_empty_leaf(tmp_db_path):
    """Insert a single entry, delete it; the leaf is empty and range
    yields nothing."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        idx.insert(42, Rid(0, 0))
        idx.delete(42, Rid(0, 0))
        assert idx.search(42) == []
        assert list(idx.range(0, 100)) == []
    finally:
        p.close()


def test_delete_nonexistent_is_silent_noop(tmp_db_path):
    """``delete(key, rid)`` for an absent (key, rid) is a silent no-op.

    Matches ``dict.pop(key, None)`` semantics for the case where the
    key exists in the index but the specific rid does not.  No
    exception, no change to other entries.
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        rid_a = Rid(page_id=0, slot_id=0)
        rid_b = Rid(page_id=0, slot_id=99)  # never inserted
        idx.insert(42, rid_a)
        # Should not raise.
        idx.delete(42, rid_b)
        idx.delete(99, rid_a)  # key absent — also no-op
        # rid_a must still be there under key 42.
        assert idx.search(42) == [rid_a]
    finally:
        p.close()


# --- sequential delete + persistence ------------------------------------


def test_delete_all_to_empty(tmp_db_path):
    """Insert 50, delete them all; the index reports an empty range."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        rids = [Rid(page_id=0, slot_id=i) for i in range(50)]
        for i in range(50):
            idx.insert(i, rids[i])
        for i in range(50):
            idx.delete(i, rids[i])
        assert list(idx.range(0, 1000)) == []
        for i in range(50):
            assert idx.search(i) == []
    finally:
        p.close()


def test_delete_all_through_root_collapse(tmp_db_path):
    """Insert enough Int keys to force an internal-root split; deleting
    all entries must collapse the root back to a single leaf.

    500 Int keys forces both leaf and internal-node splits.  As we
    delete every entry, the root must eventually become a leaf again
    (root collapse).  The final leaf carries no entries.
    """
    from tinydb.index.btree import BTreeIndex, InternalNode, LeafNode

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        rids = [Rid(page_id=0, slot_id=i) for i in range(500)]
        for i in range(500):
            idx.insert(i, rids[i])
        # Sanity: the root is internal after the splits.
        assert isinstance(idx._root_view, InternalNode)
        # Delete all entries (in arbitrary order).
        for i in range(500):
            idx.delete(i, rids[i])
        # After collapsing, root should be a leaf (or have been replaced
        # by the surviving leaf subtree).
        assert isinstance(idx._root_view, LeafNode)
        assert idx._root_view.keys == []
        assert list(idx.range(0, 1000)) == []
    finally:
        p.close()


def test_delete_leftmost_key_preserves_rest(tmp_db_path):
    """Delete the smallest key in the index; the rest remain in order."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        rid_1 = Rid(page_id=0, slot_id=1)
        rids = [Rid(page_id=0, slot_id=i) for i in range(2, 101)]
        idx.insert(1, rid_1)
        for i in range(2, 101):
            idx.insert(i, rids[i - 2])
        idx.delete(1, rid_1)
        assert idx.search(1) == []
        assert list(idx.range(2, 100)) == rids
    finally:
        p.close()


def test_delete_rightmost_key_preserves_rest(tmp_db_path):
    """Delete the largest key in the index; the rest remain in order."""
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        rids = [Rid(page_id=0, slot_id=i) for i in range(1, 100)]
        idx.insert(100, Rid(page_id=0, slot_id=100))
        for i in range(1, 100):
            idx.insert(i, rids[i - 1])
        idx.delete(100, Rid(page_id=0, slot_id=100))
        assert idx.search(100) == []
        assert list(idx.range(1, 99)) == rids
    finally:
        p.close()


# --- borrow / merge ----------------------------------------------------


def test_delete_triggers_borrow_between_leaves(tmp_db_path):
    """Insert enough keys to produce multiple leaves, then delete from
    one side enough to trigger a borrow from the sibling.  All
    surviving entries must remain reachable and in key order.
    """
    from tinydb.index.btree import BTreeIndex, MIN_LEAF_ENTRIES, LeafNode

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        # 500 Int keys forces leaf splits (a single leaf fits ~340 Int
        # entries, so 500 needs at least two leaves).
        rids = [Rid(page_id=0, slot_id=i) for i in range(500)]
        for i in range(500):
            idx.insert(i, rids[i])
        # Delete entries that all land in the same leaf (the first
        # one), pushing it below MIN_LEAF_ENTRIES.  We don't know
        # precisely where the split point lies, so delete the lowest
        # keys first — most of them are in the leftmost leaf.
        deleted = {i for i in range(0, 500, 5)}
        for i in sorted(deleted):
            idx.delete(i, rids[i])
        # Surviving entries are those not in `deleted`.  Note: any
        # borrow/merge must keep all of them.
        surviving_keys = [i for i in range(500) if i not in deleted]
        surviving_rids = [rids[i] for i in surviving_keys]
        # Range must return the surviving entries in key order.
        assert list(idx.range(0, 1000)) == surviving_rids
    finally:
        p.close()


def test_delete_triggers_merge_when_sibling_cannot_borrow(tmp_db_path):
    """When both leaves are at the minimum, deleting forces a merge —
    a leaf is absorbed into its sibling.  Range still returns all
    surviving entries in order.
    """
    from tinydb.index.btree import BTreeIndex, MIN_LEAF_ENTRIES

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        rids = [Rid(page_id=0, slot_id=i) for i in range(500)]
        for i in range(500):
            idx.insert(i, rids[i])
        # Delete enough from one side to force a merge.  Take the
        # first ~80% (way more than half) so every leaf must shrink
        # below MIN; the remaining leaves must merge to satisfy the
        # occupancy invariant.
        deleted = {i for i in range(0, 500, 1) if i % 5 != 0}  # ~400 deletes
        for i in sorted(deleted):
            idx.delete(i, rids[i])
        # Surviving entries: those not deleted (1 % 5 == 0 -> i in [0, 5, 10, ...])
        surviving = [i for i in range(500) if i not in deleted]
        # Range must return surviving entries in key order.
        result = list(idx.range(0, 1000))
        assert result == [rids[i] for i in surviving]
    finally:
        p.close()


# --- duplicate keys ----------------------------------------------------


def test_delete_duplicate_key_specific_rid(tmp_db_path):
    """Inserting the same key with multiple rids and deleting one rid
    must leave the others intact.
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        rid_a = Rid(page_id=7, slot_id=0)
        rid_b = Rid(page_id=7, slot_id=1)
        rid_c = Rid(page_id=7, slot_id=2)
        idx.insert(42, rid_a)
        idx.insert(42, rid_b)
        idx.insert(42, rid_c)
        idx.delete(42, rid_b)
        assert idx.search(42) == [rid_a, rid_c]
    finally:
        p.close()


def test_delete_mismatched_rid_is_noop(tmp_db_path):
    """``delete(key, rid)`` with a rid that was never inserted under
    ``key`` is a silent no-op; the inserted rid remains.
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        idx, _pid = _make_index(p, TypeTag.Int)
        rid_a = Rid(page_id=7, slot_id=0)
        rid_b = Rid(page_id=7, slot_id=1)
        idx.insert(42, rid_a)
        idx.delete(42, rid_b)  # rid_b was never inserted under 42
        assert idx.search(42) == [rid_a]
    finally:
        p.close()


# --- persistence -------------------------------------------------------


def test_delete_persists_across_reopen(tmp_db_path):
    """Insert 100, delete 50, flush+reopen; the surviving 50 are
    still in the index.
    """
    from tinydb.index.btree import BTreeIndex

    p = Pager.open(tmp_db_path)
    try:
        pid = p.allocate_page()
        idx = BTreeIndex(p, root_pid=pid, key_type=TypeTag.Int)
        rids = [Rid(page_id=0, slot_id=i) for i in range(100)]
        for i in range(100):
            idx.insert(i, rids[i])
        # Delete the first 50 entries.
        for i in range(50):
            idx.delete(i, rids[i])
    finally:
        p.close()

    p2 = Pager.open(tmp_db_path)
    try:
        idx2 = BTreeIndex(p2, root_pid=pid, key_type=TypeTag.Int)
        surviving = [rids[i] for i in range(50, 100)]
        assert list(idx2.range(0, 1000)) == surviving
        for i in range(50):
            assert idx2.search(i) == []
        for i in range(50, 100):
            assert idx2.search(i) == [rids[i]]
    finally:
        p2.close()