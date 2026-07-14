"""Lookup helper — resolve a column-rid query against a BTreeIndex.

T-5.3 boundary matrix: closed ``[lo, hi]`` is delegated to
``BTreeIndex.range``; everything else (open ``(lo, hi)``,
half-open ``[lo, hi)``/``(lo, hi]``, single-bound) walks leaves and
filters at this layer, because BTreeIndex.range treats
``lo == hi``/inclusive=True as a prefix range and cannot safely
express strict-open semantics.
"""

from __future__ import annotations

from typing import Any, Iterator, Tuple

from tinydb.index.btree import NO_NEXT, BTreeIndex
from tinydb.index.btree_internal import _lower_bound
from tinydb.index.btree_leaf import _read_leaf_from_bytes
from tinydb.index.manager import IndexManager
from tinydb.storage.heap import Rid
from tinydb.types.system import TypeTag


class IndexLookup:
    """Resolve column-rid lookups against an :class:`IndexManager`."""

    def __init__(self, mgr: IndexManager, index: BTreeIndex, key_tag: TypeTag) -> None:
        self.mgr = mgr
        self.index = index
        self.key_tag = key_tag

    def equality(self, value: Any) -> Iterator[Tuple[Rid, Any]]:
        for rid in self.index.search(value):
            yield rid, value

    def range(
        self,
        lo: Any,
        hi: Any,
        *,
        lo_inclusive: bool = True,
        hi_inclusive: bool = True,
    ) -> Iterator[Tuple[Rid, Any]]:
        if lo is not None and hi is not None and lo_inclusive and hi_inclusive:
            for rid in self.index.range(lo, hi):
                yield rid, None
            return
        yield from self._walk_leaves(
            lo, hi, lo_inclusive=lo_inclusive, hi_inclusive=hi_inclusive
        )

    def _walk_leaves(
        self,
        lo: Any,
        hi: Any,
        *,
        lo_inclusive: bool,
        hi_inclusive: bool,
    ) -> Iterator[Tuple[Rid, Any]]:
        """Walk every leaf in key order; yield rids that pass the bound test."""
        idx = self.index
        idx._ensure_loaded()
        start_key: Any = lo if lo is not None else _smallest_key(idx)
        if start_key is None:
            return
        leaf = idx._descend_to_first_leaf(start_key)
        if leaf is None:
            return
        while leaf is not None:
            start = 0 if lo is None else _lower_bound(leaf.keys, lo)
            for i in range(start, len(leaf.keys)):
                key = leaf.keys[i]
                if _is_past_hi(key, hi, hi_inclusive):
                    return
                if not _passes_lo(key, lo, lo_inclusive):
                    continue
                yield leaf.rids[i], key
            if leaf.next_leaf_pid == NO_NEXT:
                return
            leaf = _read_leaf_from_bytes(
                idx._pager.read_page(leaf.next_leaf_pid),
                leaf.next_leaf_pid,
            )


def _passes_lo(key: Any, lo: Any, lo_inclusive: bool) -> bool:
    if lo is None:
        return True
    return key >= lo if lo_inclusive else key > lo


def _is_past_hi(key: Any, hi: Any, hi_inclusive: bool) -> bool:
    if hi is None:
        return False
    return key > hi if hi_inclusive else key >= hi


def _smallest_key(idx: BTreeIndex) -> Any:
    """Probe key that lands us on the leftmost leaf (``None`` if empty)."""
    from tinydb.index.btree_internal import InternalNode

    idx._ensure_loaded()
    node = idx._root_view
    if node is None:
        return None
    while isinstance(node, InternalNode):
        pid = node.children[0]
        node = idx._read_node_view(pid)
    if not node.keys:
        return None
    return node.keys[0]


__all__ = ["IndexLookup"]
