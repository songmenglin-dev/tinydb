"""Index subpackage: ordered (key, rid) mapping backed by B-tree.

The tree grows beyond a single leaf via the split algorithm added in
T-4.2; leaves and internal nodes share the same :class:`Pager` page
pool, distinguished by a node-type byte at offset 0.

Public surface (re-exported here for convenience)::

    from tinydb.index import (
        BTreeIndex, BTreeOverflowError, InternalNode, LeafNode, NO_NEXT,
    )
"""

from tinydb.errors import BTreeOverflowError
from tinydb.index.btree import BTreeIndex, InternalNode, LeafNode, NO_NEXT

__all__ = [
    "BTreeIndex",
    "BTreeOverflowError",
    "InternalNode",
    "LeafNode",
    "NO_NEXT",
]