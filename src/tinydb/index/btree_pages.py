"""B-tree page enumeration — discover every page owned by an index.

Used by :meth:`tinydb.index.manager.IndexManager.drop_index` to free
the B-tree's pages after removing the index from the catalog.  Kept
in its own module so :mod:`tinydb.index.btree` stays under the
400-line cap.
"""

from __future__ import annotations

from typing import List

from tinydb.index.btree import (
    BTreeIndex,
    InternalNode,
    LeafNode,
    _INTERNAL_NODE_TYPE,
    _read_internal_from_bytes,
)
from tinydb.index.btree_leaf import NO_NEXT as _LEAF_NO_NEXT
from tinydb.index.btree_leaf import _read_leaf_from_bytes


def all_page_ids(idx: BTreeIndex) -> List[int]:
    """Return every page id currently owned by ``idx``.

    Walks from the root: collects the root and every internal-node
    child (BFS), then walks the sibling chain of every leaf reached
    so that split-off sibling leaves are also included.
    """
    idx._ensure_loaded()  # noqa: SLF001 — T-4.1 internal contract
    pager = idx._pager  # noqa: SLF001
    if idx._root_view is None:  # noqa: SLF001
        return [idx._root_pid]  # noqa: SLF001
    internal_pids: set[int] = set()
    leaf_pids: set[int] = set()
    queue: list[int] = [idx._root_pid]  # noqa: SLF001
    while queue:
        pid = queue.pop()
        if pid in internal_pids or pid in leaf_pids:
            continue
        page = pager.read_page(pid)
        node_type = page[0]
        if node_type == _INTERNAL_NODE_TYPE:
            internal_pids.add(pid)
            node: InternalNode = _read_internal_from_bytes(page, pid)
            queue.extend(node.children)
        else:
            leaf_pids.add(pid)
    # Walk sibling chains of every leaf reached.
    leaves_to_walk = list(leaf_pids)
    while leaves_to_walk:
        pid = leaves_to_walk.pop()
        node: LeafNode = _read_leaf_from_bytes(pager.read_page(pid), pid)
        nxt = node.next_leaf_pid
        if nxt != _LEAF_NO_NEXT and nxt not in leaf_pids:
            leaf_pids.add(nxt)
            leaves_to_walk.append(nxt)
    return sorted(internal_pids | leaf_pids)


__all__ = ["all_page_ids"]