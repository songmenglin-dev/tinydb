"""Storage subpackage: page-based file I/O, buffer pool, heap, catalog.

Public surface (re-exported here for convenience)::

    from tinydb.storage import Pager, BufferPool
"""

from tinydb.storage.pager import MAGIC, PAGE_SIZE, Pager

__all__ = ["Pager", "MAGIC", "PAGE_SIZE"]