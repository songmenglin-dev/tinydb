"""B-tree index — leaves, internal nodes, split algorithm.

The leaf / internal page layouts and (de)serialisers live in
:mod:`tinydb.index.btree_leaf` and :mod:`tinydb.index.btree_internal`
respectively; this module owns the cross-cutting pieces:

* :class:`BTreeIndex` — the public index class.  Holds the root page
  id and a lazy view of the root node (leaf or internal), runs
  inserts, splits on overflow, walks the tree for :meth:`search` and
  :meth:`range`.

Page layout
-----------

Every node page is one :data:`~tinydb.storage.pager.PAGE_SIZE` byte
buffer.  The very first byte is a node-type tag (0x01 leaf, 0x02
internal) so the reader can dispatch to the right layout; this is the
only deviation from the T-4.1 layout, and is needed because the two
on-wire layouts below overlap in their use of offset 0..4.  See
:mod:`tinydb.index.btree_leaf` and :mod:`tinydb.index.btree_internal`
for the per-type detail.

Deferred to later tasks: :meth:`BTreeIndex.delete` (T-4.4), composite
keys (T-4.5), catalog integration (T-4.6).
"""

from __future__ import annotations

from typing import Any, Iterator

from tinydb.errors import BTreeOverflowError  # re-exported below
from tinydb.storage.heap import Rid
from tinydb.storage.pager import Pager
from tinydb.types.system import TypeTag

from tinydb.index.btree_internal import (
    InternalNode,
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

# Sentinel: no sibling leaf / tail marker for the sibling chain.
NO_NEXT: int = 0xFFFFFFFF

# Node-type tag bytes (offset 0 of every node page).  Re-exported from
# here so callers can introspect a page type via ``btree._LEAF_NODE_TYPE``.
_LEAF_NODE_TYPE: int = 0x01
_INTERNAL_NODE_TYPE: int = 0x02

__all__ = [
    "BTreeIndex",
    "BTreeOverflowError",
    "InternalNode",
    "LeafNode",
    "NO_NEXT",
]


# --- BTreeIndex ---------------------------------------------------------


class BTreeIndex:
    """B-tree index over a :class:`Pager`-backed 4 KB page set.

    The tree grows beyond a single leaf by splitting nodes on insert
    overflow.  ``__init__`` performs no I/O — the root page is loaded
    lazily on the first read or write; :meth:`flush` re-writes the
    current state for callers that want explicit persistence.

    Deferred to later tasks:

    * :meth:`delete` — raises :class:`NotImplementedError`.
    * :meth:`search` — raises :class:`NotImplementedError`; T-4.3
      will replace the linear leaf scan with a real tree walk.
    * :meth:`range` — descends to the leftmost leaf whose key might
      satisfy ``lo``, then walks the sibling chain.  T-4.3 will replace
      this with a true tree-walking range scan.
    """

    def __init__(self, pager: Pager, root_pid: int, key_type: TypeTag) -> None:
        self._pager = pager
        self._root_pid = root_pid
        self._key_type = key_type
        self._loaded: bool = False
        # Cached root view: either a :class:`LeafNode` or an
        # :class:`InternalNode` once ``_ensure_loaded`` runs.
        self._root_view: LeafNode | InternalNode | None = None

    # -- helpers ---------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        page = self._pager.read_page(self._root_pid)
        node_type = page[0]
        # Backward compat: a freshly-allocated page is all zeros, which
        # used to mean "empty leaf" under T-4.1.  Treat 0x00 as a fresh
        # leaf so the constructor remains zero-I/O; once we write any
        # node the type byte becomes authoritative.
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
                f"view is None (insert not yet initialised)"
            )

    # -- tree-walk primitives --------------------------------------------

    def _find_child(self, key: Any, internal: InternalNode) -> int:
        """Index into ``internal.children`` whose subtree contains ``key``.

        Children are left-inclusive: ``children[i]`` contains all keys
        ``< keys[i]`` (for ``i > 0``); the rightmost child has no upper
        bound.  Returns ``len(children) - 1`` if ``key`` is larger than
        every separator.
        """
        idx = _upper_bound(internal.keys, key)
        return min(idx, len(internal.children) - 1)

    # -- split helpers ---------------------------------------------------

    @staticmethod
    def _split_leaf(
        pager: Pager, pid: int, leaf: LeafNode, key_type: TypeTag
    ) -> tuple[Any, int]:
        """Split ``leaf`` at ``pid`` into two pages.

        The left half stays at ``pid``; the right half lives on a fresh
        page.  The left's ``next_leaf_pid`` is rewritten to point at
        the new right page so the sibling chain stays walkable; the
        right inherits whatever sibling ``leaf`` had.  Returns
        ``(sep_key, right_pid)`` where ``sep_key`` is the smallest key
        in the right page — the value the parent must promote.
        """
        mid = len(leaf.keys) // 2
        old_next = leaf.next_leaf_pid
        right_pid = pager.allocate_page()
        left = LeafNode(
            keys=leaf.keys[:mid],
            rids=leaf.rids[:mid],
            next_leaf_pid=right_pid,
        )
        right = LeafNode(
            keys=leaf.keys[mid:],
            rids=leaf.rids[mid:],
            next_leaf_pid=old_next,
        )
        _write_leaf(pager, pid, left, key_type)
        _write_leaf(pager, right_pid, right, key_type)
        return right.keys[0], right_pid

    @staticmethod
    def _split_internal(
        pager: Pager, pid: int, node: InternalNode, key_type: TypeTag
    ) -> tuple[Any, int]:
        """Split ``node`` at ``pid`` into two internal pages.

        The middle key is pushed up to the parent and does NOT appear
        in either child.  Returns ``(push_up_key, right_pid)``.
        """
        mid = len(node.keys) // 2
        push_up_key = node.keys[mid]
        left = InternalNode(
            keys=node.keys[:mid],
            children=node.children[: mid + 1],
        )
        right = InternalNode(
            keys=node.keys[mid + 1 :],
            children=node.children[mid + 1 :],
        )
        right_pid = pager.allocate_page()
        _write_internal(pager, pid, left, key_type)
        _write_internal(pager, right_pid, right, key_type)
        return push_up_key, right_pid

    # -- public API ------------------------------------------------------

    def search(self, key: Any) -> list[Rid]:
        """Return every rid whose key equals ``key`` (O(log n + k)).

        Descends from the root through internal nodes, choosing the
        child whose subtree may contain ``key``, and finally scans
        the matching leaf for all entries with that key.  Duplicates
        are returned in insertion order.
        """
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

    def range(
        self, lo: Any, hi: Any, *, inclusive: bool = True
    ) -> Iterator[Rid]:
        """Yield rids whose keys lie in ``[lo, hi]`` (or ``[lo, hi)``).

        Descends to the leftmost leaf whose key is ``>= lo``, then
        walks the sibling chain via ``next_leaf_pid`` until the
        leaves' keys cross ``hi``.  The starting leaf is found via
        tree descent (T-4.3) rather than by blindly reading the
        root, so multi-leaf indexes land on the correct leaf for
        any ``lo`` value.
        """
        if lo > hi:
            return
        if self._root_view is None:
            self._ensure_loaded()
        leaf = self._descend_to_first_leaf(lo)
        while leaf is not None:
            start = _lower_bound(leaf.keys, lo)
            for i in range(start, len(leaf.keys)):
                key = leaf.keys[i]
                if inclusive:
                    if key > hi:
                        return
                else:
                    if key >= hi:
                        return
                yield leaf.rids[i]
            if leaf.next_leaf_pid == NO_NEXT:
                return
            leaf = _read_leaf_from_bytes(
                self._pager.read_page(leaf.next_leaf_pid), leaf.next_leaf_pid
            )

    def _descend_to_first_leaf(self, key: Any) -> LeafNode | None:
        """Walk the tree from the root, descending into the child whose
        subtree may contain ``key``.  Returns the leaf that owns the
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
        """Insert ``(key, rid)``; splits nodes on overflow."""
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
                push_up_key, right_pid = self._split_leaf(
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
            up_key, new_right = self._split_internal(
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
        """Remove ``(key, rid)`` from the leaf.

        Placeholder — delete + rebalance arrive in T-4.4.
        """
        raise NotImplementedError("delete + rebalance arrives in T-4.4")

    def flush(self) -> None:
        """Re-write the current root to disk.  Idempotent; cheap.

        Internal pages touched by the last insert are already persisted
        by ``_insert_into``; this is here for callers that want to
        guarantee the root page is on disk after a sequence of inserts.
        """
        if self._loaded and self._root_view is not None:
            self._persist_root()