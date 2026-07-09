"""Storage subpackage: page-based file I/O, buffer pool, heap, catalog.

Public surface (re-exported here for convenience)::

    from tinydb.storage import Pager, BufferPool, Heap, Rid, FreeSpaceMap
"""

from tinydb.storage.buffer_pool import BufferPool
from tinydb.storage.free_space import FreeSpaceMap
from tinydb.storage.heap import Heap, Rid
from tinydb.storage.pager import MAGIC, PAGE_SIZE, Pager

__all__ = [
    "BufferPool",
    "FreeSpaceMap",
    "Heap",
    "MAGIC",
    "PAGE_SIZE",
    "Pager",
    "Rid",
]
