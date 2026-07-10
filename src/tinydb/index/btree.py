"""B-tree index — leaves, internal nodes, split, delete, rebalance.

The leaf / internal page layouts and (de)serialisers live in
:mod:`tinydb.index.btree_leaf` and :mod:`tinydb.index.btree_internal`;
this module owns the cross-cutting :class:`BTreeIndex` class and the
public API (insert, search, range, delete, flush).

Every node page is one :data:`~tinydb.storage.pager.PAGE_SIZE` byte
buffer.  The very first byte is a node-type tag (0x01 leaf, 0x02
internal) so the reader can dispatch to the right layout; this is
the only deviation from the T-4.1 layout, needed because the two
on-wire layouts below overlap in their use of offset 0..4.  See
:mod:`tinydb.index.btree_leaf` and :mod:`tinydb.index.btree_internal`
for the per-type detail.

Deferred to later tasks: catalog integration (T-4.6).
"""

from __future__ import annotations

from typing import Any, Iterator

from tinydb.errors import BTreeOverflowError  # re-exported below
from tinydb.storage.heap import Rid
from tinydb.storage.pager import Pager
from tinydb.types.system import TypeTag

from tinydb.index import btree_delete
from tinydb.index.btree_internal import (
    InternalNode,
    _is_past_upper,
    _lower_bound,
    _read_internal_from_bytes,
    _upper_bound,
    _write_internal,
)
from tinydb.index.btree_leaf import (
    LeafNode,
    _read_leaf_from_bytes,
    _write_leaf,
)
from tinydb.index.btree_split import split_internal, split_leaf

# Sentinel: no sibling leaf / tail marker for the sibling chain.
NO_NEXT: int = 0xFFFFFFFF

# Node-type tag bytes (offset 0 of every node page).
_LEAF_NODE_TYPE: int = 0x01
_INTERNAL_NODE_TYPE: int = 0x02

__all__ = [
    "BTreeIndex",
    "BTreeOverflowError",
    "InternalNode",
    "LeafNode",
    "MIN_INTERNAL_CHILDREN",
    "MIN_INTERNAL_KEYS",
    "MIN_LEAF_ENTRIES",
    "NO_NEXT",
    "ORDER",
]

# --- B-tree order constants (REQ-IDX-1 + design D-4) -------------------
#
# The on-disk layout permits up to 2N - 1 leaf entries and 2N internal
# children before an overflow; the minimum occupancy after a delete is
# N - 1 leaf entries / N internal children.  These constants are
# exposed as module globals and re-exported as class attributes on
# :class:`BTreeIndex` so callers (and tests) can reference them by name.
ORDER: int = 64
MIN_LEAF_ENTRIES: int = ORDER - 1   # = 63
MIN_INTERNAL_KEYS: int = ORDER - 1  # = 63 (internal has children - 1 keys)
MIN_INTERNAL_CHILDREN: int = ORDER  # = 64


# --- BTreeIndex ---------------------------------------------------------


class BTreeIndex:
    """B-tree index over a :class:`Pager`-backed 4 KB page set.

    The tree grows beyond a single leaf by splitting nodes on insert
    overflow, and shrinks back via borrow / merge / root collapse on
    :meth:`delete`.  ``__init__`` performs no I/O — the root page is
    loaded lazily on the first read or write; :meth:`flush` re-writes
    the current state for callers that want explicit persistence.

    The :data:`ORDER`, :data:`MIN_LEAF_ENTRIES`, :data:`MIN_INTERNAL_KEYS`
    and :data:`MIN_INTERNAL_CHILDREN` constants are exposed both as
    module globals and as class attributes.  Deferred to later tasks:
    catalog integration (T-4.6).
    """

    # Expose order constants as class attributes too.
    ORDER: int = ORDER
    MIN_LEAF_ENTRIES: int = MIN_LEAF_ENTRIES
    MIN_INTERNAL_KEYS: int = MIN_INTERNAL_KEYS
    MIN_INTERNAL_CHILDREN: int = MIN_INTERNAL_CHILDREN

    def __init__(self, pager: Pager, root_pid: int, key_type: TypeTag) -> None:
        self._pager = pager
        self._root_pid = root_pid
        self._key_type = key_type
        self._loaded: bool = False
        # Cached root view, populated lazily by ``_ensure_loaded``.
        self._root_view: LeafNode | InternalNode | None = None

    # -- helpers ---------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        page = self._pager.read_page(self._root_pid)
        node_type = page[0]
        # 0x00 = fresh page (zero-I/O ``__init__``); 0x01 = leaf.
        if node_type in (0x00, _LEAF_NODE_TYPE):
            self._root_view = _read_leaf_from_bytes(page, self._root_pid)
        elif node_type == _INTERNAL_NODE_TYPE:
            self._root_view = _read_internal_from_bytes(
                page, self._root_pid
            )
        else:
            raise ValueError(
                f"root page {self._root_pid} has unknown node_type "
                f"0x{node_type:02x}"
            )
        self._loaded = True

    def _persist_root(self) -> None:
        """Write the in-memory root view back to the root page."""
        view = self._root_view
        if isinstance(view, LeafNode):
            _write_leaf(self._pager, self._root_pid, view, self._key_type)
        elif isinstance(view, InternalNode):
            _write_internal(
                self._pager, self._root_pid, view, self._key_type
            )
        else:
            raise RuntimeError(
                f"cannot persist root at pid={self._root_pid}: "
                "view is None (insert not yet initialised)"
            )

    # -- tree-walk primitives --------------------------------------------

    def _find_child(self, key: Any, internal: InternalNode) -> int:
        """Index into ``internal.children`` whose subtree contains ``key``.

        Children are left-inclusive: ``children[i]`` contains all keys
        ``< keys[i]`` (for ``i > 0``); the rightmost child has no upper
        bound.  Returns ``len(children) - 1`` if ``key`` exceeds every
        separator.
        """
        idx = _upper_bound(internal.keys, key)
        return min(idx, len(internal.children) - 1)

    # -- public API ------------------------------------------------------

    def search(self, key: Any) -> list[Rid]:
        """Return every rid whose key equals ``key`` (O(log n + k)).

        ``key`` may be a scalar or a tuple (composite key, e.g.
        ``("Smith", "Alice")``); tuple comparison is lexicographic.
        Descends from the root through internal nodes, then scans
        the matching leaf for all entries with that key.
        Duplicates are returned in insertion order.  A search whose
        key type is not comparable to the index's key type returns
        ``[]`` rather than raising ``TypeError``.
        """
        try:
            if self._root_view is None:
                self._ensure_loaded()
            node: LeafNode | InternalNode | None = self._root_view
            if node is None:
                return []
            pid = self._root_pid
            while isinstance(node, InternalNode):
                child_idx = self._find_child(key, node)
                pid = node.children[child_idx]
                node = self._read_node_view(pid)
            if not isinstance(node, LeafNode):
                raise RuntimeError(
                    f"expected leaf at pid={pid}, got "
                    f"{type(node).__name__}"
                )
            leaf = node
            start = _lower_bound(leaf.keys, key)
            end = _upper_bound(leaf.keys, key)
            return list(leaf.rids[start:end])
        except TypeError:
            return []

    def range(
        self, lo: Any, hi: Any, *, inclusive: bool = True
    ) -> Iterator[Rid]:
        """Yield rids whose keys lie in ``[lo, hi]`` (or ``[lo, hi)``).

        ``lo`` and ``hi`` may be scalars or tuples (composite keys);
        tuple comparison is lexicographic.  Descends to the leftmost
        leaf whose key is ``>= lo`` (tree descent, T-4.3), then
        walks the sibling chain.

        Prefix-bound semantics (T-4.5): when ``lo == hi`` and
        ``inclusive=True`` the bound is treated as a prefix, so
        ``range(("Smith",), ("Smith",), inclusive=True)`` yields
        every entry whose key starts with ``("Smith",)``.  A
        ``TypeError`` from an incompatible comparison is caught and
        the iterator yields nothing.
        """
        # lo == hi with inclusive=True means "prefix range".
        try:
            prefix_mode = (lo == hi) and inclusive
        except TypeError:
            return
        try:
            if lo > hi:
                return
            if self._root_view is None:
                self._ensure_loaded()
            leaf = self._descend_to_first_leaf(lo)
            while leaf is not None:
                start = _lower_bound(leaf.keys, lo)
                for i in range(start, len(leaf.keys)):
                    key = leaf.keys[i]
                    if _is_past_upper(
                        key, hi, inclusive, prefix_mode=prefix_mode
                    ):
                        return
                    yield leaf.rids[i]
                if leaf.next_leaf_pid == NO_NEXT:
                    return
                leaf = _read_leaf_from_bytes(
                    self._pager.read_page(leaf.next_leaf_pid),
                    leaf.next_leaf_pid,
                )
        except TypeError:
            return

    def _descend_to_first_leaf(self, key: Any) -> LeafNode | None:
        """Walk the tree from the root to the leaf that owns the
        leftmost matching key (or ``None`` if the tree is empty).
        """
        if self._root_view is None:
            self._ensure_loaded()
        node = self._root_view
        if node is None:
            return None
        while isinstance(node, InternalNode):
            child_idx = self._find_child(key, node)
            pid = node.children[child_idx]
            node = self._read_node_view(pid)
        if not isinstance(node, LeafNode):
            raise RuntimeError(
                f"expected leaf at descent, got {type(node).__name__}"
            )
        return node

    def insert(self, key: Any, rid: Rid) -> None:
        """Insert ``(key, rid)``; splits nodes on overflow.

        ``key`` may be a scalar or a tuple (composite key); the tree
        is kept sorted by Python's natural ``<`` ordering, which is
        lexicographic for tuples.
        """
        self._ensure_loaded()
        self._ensure_loaded()
        split = self._insert_into(self._root_pid, self._root_view, key, rid)
        if split is not None:
            # The root split: allocate a new internal node as the new
            # root and rewrite root_pid.
            new_root_pid = self._pager.allocate_page()
            new_root = InternalNode(
                keys=[split[0]],
                children=[self._root_pid, split[1]],
            )
            _write_internal(
                self._pager, new_root_pid, new_root, self._key_type
            )
            self._root_pid = new_root_pid
            self._root_view = new_root

    def _insert_into(
        self,
        pid: int,
        node: LeafNode | InternalNode,
        key: Any,
        rid: Rid,
    ) -> tuple[Any, int] | None:
        """Insert into subtree rooted at ``pid``.  Return
        ``(push_up_key, right_pid)`` if this node split, else ``None``.
        """
        if isinstance(node, LeafNode):
            pos = _upper_bound(node.keys, key)
            node.keys.insert(pos, key)
            node.rids.insert(pos, rid)
            try:
                _write_leaf(self._pager, pid, node, self._key_type)
                return None
            except BTreeOverflowError:
                push_up_key, right_pid = split_leaf(
                    self._pager, pid, node, self._key_type
                )
                return push_up_key, right_pid
        # Internal node: descend.
        if not isinstance(node, InternalNode):
            raise RuntimeError(
                f"_insert_into: expected InternalNode at pid={pid}, "
                f"got {type(node).__name__}"
            )
        child_idx = self._find_child(key, node)
        child_pid = node.children[child_idx]
        child_node = self._read_node_view(child_pid)
        child_split = self._insert_into(child_pid, child_node, key, rid)
        if child_split is None:
            return None
        # Child split: splice the new separator into this internal node.
        push_up_key, right_pid = child_split
        node.keys.insert(child_idx, push_up_key)
        node.children.insert(child_idx + 1, right_pid)
        try:
            _write_internal(self._pager, pid, node, self._key_type)
            return None
        except BTreeOverflowError:
            up_key, new_right = split_internal(
                self._pager, pid, node, self._key_type
            )
            return up_key, new_right

    def _read_node_view(self, pid: int) -> LeafNode | InternalNode:
        """Read a single page and return it as a leaf or internal node.

        Reads the page exactly once and dispatches on the type byte
        before handing the bytes to the from-bytes reader.  This
        avoids the double-page-read that an earlier T-4.2 path
        incurred (NIT #4).
        """
        page = self._pager.read_page(pid)
        node_type = page[0]
        if node_type in (0x00, _LEAF_NODE_TYPE):
            return _read_leaf_from_bytes(page, pid)
        if node_type == _INTERNAL_NODE_TYPE:
            return _read_internal_from_bytes(page, pid)
        raise ValueError(
            f"page {pid} has unknown node_type 0x{node_type:02x}"
        )

    def delete(self, key: Any, rid: Rid) -> None:
        """Remove ``(key, rid)`` from the tree, rebalancing on underflow.

        Behaviour:

        * Silent no-op when ``(key, rid)`` is not present — matches
          ``dict.pop(key, None)`` semantics.  No exception is raised.
        * On underflow, prefer borrowing from the left sibling
          (keeps the parent separator stable); fall back to merging
          with the right sibling (right wins — child page orphan).
        * Root collapse: if the root is an internal node left with a
          single child after a merge, that child takes over as root.

        Duplicates: only the specific ``rid`` under ``key`` is
        removed.  ``key`` may be a scalar or a tuple (composite
        key); tuple comparison is lexicographic.
        """
        self._ensure_loaded()
        if self._root_view is None:
            return
        btree_delete.delete_from_subtree(
            self._pager,
            self._root_pid,
            self._root_view,
            key,
            rid,
            self._key_type,
            order=ORDER,
            min_leaf_entries=MIN_LEAF_ENTRIES,
            min_internal_children=MIN_INTERNAL_CHILDREN,
            read_node_view=self._read_node_view,
            find_child=self._find_child,
        )
        # Try to collapse the root if it ended up as a singleton
        # internal node.  Uses a single-element list as an out-param
        # so the helper can mutate the BTreeIndex's view atomically.
        root_ref: list[LeafNode | InternalNode | None] = [self._root_view]
        new_pid, _ = btree_delete.collapse_root_if_singleton(
            self._pager, root_ref, self._read_node_view
        )
        if new_pid is not None:
            self._root_pid = new_pid
            self._root_view = root_ref[0]

    def flush(self) -> None:
        """Re-write the current root to disk.  Idempotent; cheap.

        Internal pages touched by the last insert are already persisted
        by ``_insert_into``; this is here for callers that want to
        guarantee the root page is on disk after a sequence of inserts.
        """
        if self._loaded and self._root_view is not None:
            self._persist_root()
