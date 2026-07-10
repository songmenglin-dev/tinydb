"""B-tree split helpers.

Extracted from ``BTreeIndex`` in T-4.4 to keep :mod:`tinydb.index.btree`
under the 400-line cap once the delete + rebalance helpers land.  The
two helpers here are pure functions of the supplied ``pager``,
``key_type``, and the page id + node to split — they have no stateful
binding to ``BTreeIndex`` and so live happily at module scope.
"""

from __future__ import annotations

from typing import Any

from tinydb.index.btree_internal import InternalNode, _write_internal
from tinydb.index.btree_leaf import LeafNode, _write_leaf
from tinydb.storage.pager import Pager
from tinydb.types.system import TypeTag

__all__ = ["split_leaf", "split_internal"]


def split_leaf(
    pager: Pager, pid: int, leaf: LeafNode, key_type: TypeTag
) -> tuple[Any, int]:
    """Split ``leaf`` at ``pid`` into two pages.

    The left half stays at ``pid``; the right half lives on a fresh
    page.  The left's ``next_leaf_pid`` is rewritten to point at the new
    right page so the sibling chain stays walkable; the right inherits
    whatever sibling ``leaf`` had.  Returns ``(sep_key, right_pid)``
    where ``sep_key`` is the smallest key in the right page — the value
    the parent must promote.
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


def split_internal(
    pager: Pager, pid: int, node: InternalNode, key_type: TypeTag
) -> tuple[Any, int]:
    """Split ``node`` at ``pid`` into two internal pages.

    The middle key is pushed up to the parent and does NOT appear in
    either child.  Returns ``(push_up_key, right_pid)``.
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
