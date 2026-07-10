"""Index subpackage: ordered (key, rid) mapping backed by B-tree leaves.

Public surface (re-exported here for convenience)::

    from tinydb.index import BTreeIndex, LeafNode
"""

from tinydb.index.btree import BTreeIndex, LeafNode, NO_NEXT

__all__ = ["BTreeIndex", "LeafNode", "NO_NEXT"]