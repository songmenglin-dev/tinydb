"""B-tree delete entry-point + root collapse.

The recursive :func:`delete_from_subtree` walks the tree to find the
leaf holding ``(key, rid)``, removes the entry, and signals "underflow"
back up to the caller.  When a child underflows, the actual
borrow / merge work is delegated to :mod:`tinydb.index.btree_rebalance`
so this module stays small and the borrow vs merge symmetry is in one
place.

:func:`collapse_root_if_singleton` handles the root-collapse case
(internal root left with a single child after a merge).
"""

from __future__ import annotations

from typing import Any

from tinydb.index.btree_internal import (
    InternalNode,
    _lower_bound,
    _upper_bound,
    _write_internal,
)
from tinydb.index.btree_leaf import LeafNode, _write_leaf
from tinydb.index.btree_rebalance import borrow_from_sibling, merge_with_sibling
from tinydb.storage.heap import Rid
from tinydb.types.system import TypeTag

__all__ = ["collapse_root_if_singleton", "delete_from_subtree"]


# --- entry point --------------------------------------------------------


def delete_from_subtree(
    pager,
    root_pid: int,
    root_view,
    key: Any,
    rid: Rid,
    key_type: TypeTag,
    *,
    order: int,  # noqa: ARG001 — reserved for parity with split helpers
    min_leaf_entries: int,
    min_internal_children: int,
    read_node_view,
    find_child,
) -> tuple[bool, bool]:
    """Delete ``(key, rid)`` from the subtree rooted at ``(pid, node)``.

    Returns ``(removed, underflow_at_self)`` where:

    * ``removed`` — True iff the entry was found and removed.
    * ``underflow_at_self`` — True iff this node now has fewer than
      the minimum allowed entries/children, requiring the caller (the
      *parent* of this node) to rebalance.
    """
    pid = root_pid
    node = root_view
    if isinstance(node, LeafNode):
        return _delete_from_leaf(
            pager,
            pid,
            node,
            key,
            rid,
            key_type,
            min_leaf_entries=min_leaf_entries,
        )
    if not isinstance(node, InternalNode):
        raise RuntimeError(
            f"delete_from_subtree: unexpected node type "
            f"{type(node).__name__} at pid={pid}"
        )
    child_idx = find_child(key, node)
    child_pid = node.children[child_idx]
    removed, child_underflow = delete_from_subtree(
        pager,
        child_pid,
        read_node_view(child_pid),
        key,
        rid,
        key_type,
        order=order,
        min_leaf_entries=min_leaf_entries,
        min_internal_children=min_internal_children,
        read_node_view=read_node_view,
        find_child=find_child,
    )
    if not removed or not child_underflow:
        return removed, False
    # Try borrow (left then right); only fall back to merge when no
    # sibling can spare an entry.  Borrow keeps two pages occupied;
    # a merge drops a separator from the parent and lets one page
    # become orphan.
    _try_borrow_or_merge(
        pager,
        pid,
        node,
        child_idx,
        key_type,
        min_leaf_entries=min_leaf_entries,
        min_internal_children=min_internal_children,
        read_node_view=read_node_view,
    )
    _write_internal(pager, pid, node, key_type)
    self_underflow = len(node.keys) + 1 < min_internal_children
    return True, self_underflow


def _delete_from_leaf(
    pager,
    pid: int,
    leaf: LeafNode,
    key: Any,
    rid: Rid,
    key_type: TypeTag,
    *,
    min_leaf_entries: int,
) -> tuple[bool, bool]:
    """Remove ``(key, rid)`` from the leaf at ``pid``.

    Returns ``(removed, underflow)``.  Silent no-op when ``(key, rid)``
    is absent — returns ``(False, False)``.
    """
    start = _lower_bound(leaf.keys, key)
    end = _upper_bound(leaf.keys, key)
    pos = -1
    for i in range(start, end):
        if leaf.rids[i] == rid:
            pos = i
            break
    if pos == -1:
        return False, False
    del leaf.keys[pos]
    del leaf.rids[pos]
    _write_leaf(pager, pid, leaf, key_type)
    underflow = len(leaf.keys) < min_leaf_entries
    return True, underflow


# --- dispatch ------------------------------------------------------------


def _try_borrow_or_merge(
    pager,
    parent_pid: int,
    parent: InternalNode,
    child_idx: int,
    key_type: TypeTag,
    *,
    min_leaf_entries: int,
    min_internal_children: int,
    read_node_view,
) -> None:
    """Borrow from left, then right; merge only if no sibling can spare."""
    if borrow_from_sibling(
        pager,
        parent_pid,
        parent,
        child_idx,
        prefer_left=True,
        key_type=key_type,
        min_leaf_entries=min_leaf_entries,
        min_internal_children=min_internal_children,
        read_node_view=read_node_view,
    ):
        return
    if borrow_from_sibling(
        pager,
        parent_pid,
        parent,
        child_idx,
        prefer_left=False,
        key_type=key_type,
        min_leaf_entries=min_leaf_entries,
        min_internal_children=min_internal_children,
        read_node_view=read_node_view,
    ):
        return
    merge_with_sibling(
        pager,
        parent_pid,
        parent,
        child_idx,
        key_type,
        min_leaf_entries=min_leaf_entries,
        min_internal_children=min_internal_children,
        read_node_view=read_node_view,
    )


# --- root collapse ------------------------------------------------------


def collapse_root_if_singleton(pager, root_view_ref, read_node_view):
    """Replace the root with its single child if it is an internal
    singleton.  Updates ``root_view_ref`` (a single-element list acting
    as an out-parameter to the BTreeIndex's ``_root_pid`` /
    ``_root_view`` fields).  Returns ``(new_root_pid, new_root_view)``.
    """
    del pager  # unused — kept for symmetry / future use
    view = root_view_ref[0]
    if not isinstance(view, InternalNode):
        return None, view
    if len(view.children) != 1:
        return None, view
    new_pid = view.children[0]
    new_view = read_node_view(new_pid)
    root_view_ref[0] = new_view
    return new_pid, new_view
