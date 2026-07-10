"""B-tree rebalance primitives — borrow + merge between siblings.

Extracted from :mod:`tinydb.index.btree_delete` in T-4.4 to keep that
module under the 400-line cap once both pieces are in place.  All
operations assume the B+ convention: parent.keys[i] = smallest key in
children[i + 1]'s subtree, so the parent separator is also the first
key of the right child.
"""

from __future__ import annotations

from tinydb.index.btree_internal import InternalNode, _write_internal
from tinydb.index.btree_leaf import LeafNode, _write_leaf
from tinydb.types.system import TypeTag

__all__ = ["borrow_from_sibling", "merge_with_sibling"]


# --- borrow -------------------------------------------------------------


def borrow_from_sibling(
    pager,
    parent_pid: int,
    parent: InternalNode,
    child_idx: int,
    *,
    prefer_left: bool,
    key_type: TypeTag,
    min_leaf_entries: int,
    min_internal_children: int,
    read_node_view,
) -> bool:
    """Borrow one entry from a sibling of the child at ``child_idx``.

    Tries the left sibling first when ``prefer_left`` is True (and the
    child has a left sibling); otherwise the right sibling.  Returns
    True on success — on success the parent, child, and sibling pages
    are all re-written to disk.

    The conventions follow the codebase's B+ style:
      * parent.keys[i] = smallest key in children[i + 1]'s subtree.
      * children[i + 1].keys[0] = parent.keys[i] (a "boundary" key
        that sits in both children[i + 1] and the parent).

    Borrow-from-LEFT (B is the left sibling, A is the underflowing child
    to B's right):
      * Move B's LAST entry (key K_l, rid R_l) up to the parent
        separator slot, replacing the old separator.
      * Insert K_l at A's FRONT (the existing A.keys[0] — the old
        separator value — shifts to A.keys[1]).
      * B loses its last entry.

    Borrow-from-RIGHT (B is the right sibling, A is the underflowing
    child to B's left):
      * Move B's FIRST entry (key K_sep, rid R_first) — which equals
        the parent separator — to A's END.
      * Update the parent separator to B's NEW first key
        (B.keys[0] AFTER the pop).
      * B loses its first entry.
    """
    if prefer_left:
        if child_idx == 0:
            return False
        sibling_idx = child_idx - 1
        separator_idx = sibling_idx
    else:
        if child_idx + 1 >= len(parent.children):
            return False
        sibling_idx = child_idx + 1
        separator_idx = child_idx

    sibling_pid = parent.children[sibling_idx]
    child_pid = parent.children[child_idx]
    sibling = read_node_view(sibling_pid)
    child = read_node_view(child_pid)
    _ensure_same_kind(sibling, child, "borrow")

    if not _sibling_has_spare(
        sibling,
        min_leaf_entries=min_leaf_entries,
        min_internal_children=min_internal_children,
    ):
        return False

    if isinstance(sibling, LeafNode):
        if prefer_left:
            # Borrow LEFT: take sibling's last entry.
            new_sep = sibling.keys.pop()
            borrowed_rid = sibling.rids.pop()
            parent.keys[separator_idx] = new_sep
            child.keys.insert(0, new_sep)
            child.rids.insert(0, borrowed_rid)
        else:
            # Borrow RIGHT: take sibling's first entry.
            borrowed_key = sibling.keys.pop(0)
            borrowed_rid = sibling.rids.pop(0)
            # The new parent separator is what sibling's first key is
            # NOW (after the pop), not what it was before.
            parent.keys[separator_idx] = sibling.keys[0]
            child.keys.append(borrowed_key)
            child.rids.append(borrowed_rid)
        _write_leaf(pager, sibling_pid, sibling, key_type)
        _write_leaf(pager, child_pid, child, key_type)
    else:
        # Internal sibling — same convention, plus a child pointer
        # moves with the borrowed key.
        if prefer_left:
            new_sep = sibling.keys.pop()
            borrowed_child = sibling.children.pop()
            parent.keys[separator_idx] = new_sep
            child.keys.insert(0, new_sep)
            child.children.insert(0, borrowed_child)
        else:
            borrowed_key = sibling.keys.pop(0)
            borrowed_child = sibling.children.pop(0)
            parent.keys[separator_idx] = sibling.keys[0]
            child.keys.append(borrowed_key)
            child.children.append(borrowed_child)
        _write_internal(pager, sibling_pid, sibling, key_type)
        _write_internal(pager, child_pid, child, key_type)

    _write_internal(pager, parent_pid, parent, key_type)
    return True


def _sibling_has_spare(
    node, *, min_leaf_entries: int, min_internal_children: int
) -> bool:
    """Return True iff the node has more than the minimum entries."""
    if isinstance(node, LeafNode):
        return len(node.keys) > min_leaf_entries
    if isinstance(node, InternalNode):
        return len(node.children) > min_internal_children
    raise RuntimeError(
        f"_sibling_has_spare: unexpected node type {type(node).__name__}"
    )


# --- merge --------------------------------------------------------------


def merge_with_sibling(
    pager,
    parent_pid: int,
    parent: InternalNode,
    child_idx: int,
    key_type: TypeTag,
    min_leaf_entries: int,
    min_internal_children: int,
    read_node_view,
) -> None:
    """Merge the child at ``child_idx`` with a sibling (right if available).

    After the merge, the parent has one fewer separator and one fewer
    child.  The "winning" page is whichever page is still referenced
    from the parent; the other becomes an orphan (its slot stays
    allocated, but is no longer referenced from the tree).  No
    re-allocation of the free-space map — orphan pages are tolerated.

    The ``min_leaf_entries`` and ``min_internal_children`` arguments
    are accepted for symmetry with :func:`borrow_from_sibling` but are
    not consulted — merges always run.
    """
    del min_leaf_entries, min_internal_children  # unused; signature parity
    if child_idx + 1 < len(parent.children):
        _merge_into_right(
            pager,
            parent_pid,
            parent,
            child_idx,
            key_type,
            read_node_view=read_node_view,
        )
        return
    if child_idx > 0:
        _merge_into_right(
            pager,
            parent_pid,
            parent,
            child_idx - 1,
            key_type,
            read_node_view=read_node_view,
        )
        return
    # Single-child parent (root case): no sibling to merge with.
    # The caller — collapse_root_if_singleton — handles this case.
    raise RuntimeError(
        "merge_with_sibling called with no sibling available "
        f"(parent has {len(parent.children)} child(ren))"
    )


def _merge_into_right(
    pager,
    parent_pid: int,
    parent: InternalNode,
    left_idx: int,
    key_type: TypeTag,
    *,
    read_node_view,
) -> None:
    """Merge ``children[left_idx]`` into ``children[left_idx + 1]`` (right wins).

    Drops ``parent.keys[left_idx]`` and ``parent.children[left_idx]``;
    the right page is rewritten with the merged contents.  Used both
    for "merge child into right" and (via ``left_idx = child_idx - 1``)
    "merge left into child".
    """
    left_pid = parent.children[left_idx]
    right_pid = parent.children[left_idx + 1]
    sep = parent.keys[left_idx]
    left = read_node_view(left_pid)
    right = read_node_view(right_pid)
    _ensure_same_kind(left, right, "merge")

    if isinstance(left, LeafNode) and isinstance(right, LeafNode):
        new_right = LeafNode(
            keys=left.keys + right.keys,
            rids=left.rids + right.rids,
            next_leaf_pid=right.next_leaf_pid,
        )
        _write_leaf(pager, right_pid, new_right, key_type)
    else:
        if not (
            isinstance(left, InternalNode) and isinstance(right, InternalNode)
        ):
            raise RuntimeError(
                f"merge: left/right type mismatch "
                f"({type(left).__name__} vs {type(right).__name__})"
            )
        # Internal merge: the parent separator becomes a key in the
        # merged result so the data round-trips correctly.
        new_right = InternalNode(
            keys=left.keys + [sep] + right.keys,
            children=left.children + right.children,
        )
        _write_internal(pager, right_pid, new_right, key_type)

    # Drop the separator between left and right; drop the left child.
    del parent.keys[left_idx]
    del parent.children[left_idx]
    _write_internal(pager, parent_pid, parent, key_type)


# --- shared helpers -----------------------------------------------------


def _ensure_same_kind(left, right, op: str) -> None:
    """Raise ``RuntimeError`` if ``left`` and ``right`` are not the same
    node kind (leaf vs internal).  Caller operations require kind
    agreement.
    """
    if type(left) is not type(right):
        raise RuntimeError(
            f"{op}: node type mismatch "
            f"({type(left).__name__} vs {type(right).__name__})"
        )
