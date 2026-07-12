"""Bind a :class:`Heap` to a catalog-owned table.

Centralises the ``Heap._head_pid = meta.heap_pid`` rebind that the
executor applies for every DML / read plan.  Lives in its own module
so callers don't reach into :class:`Heap`'s private fields directly.

Per T-5.2 NIT-10 the rebind is safe: ``Heap.scan()`` walks the chain
via ``next_page_id``, so as long as the catalog's ``heap_pid`` is the
true chain head the executor sees the same bytes the catalog wrote.
"""

from __future__ import annotations

from typing import Optional

from tinydb.storage.heap import Heap
from tinydb.storage.pager import Pager


def bind_heap(catalog, table_name: str) -> Heap:
    """Return a :class:`Heap` bound to ``catalog``'s ``table_name``.

    Falls back to ``catalog._pager`` when no pager is exposed
    publicly — matches the executor's own fallback in
    :meth:`Executor.heap_for`.
    """
    meta = catalog.get_table(table_name)
    pager: Optional[Pager] = getattr(catalog, "_pager", None)
    if pager is None:
        raise RuntimeError(
            "bind_heap: catalog has no pager (need engine.pager)"
        )
    heap = Heap(pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid  # rebind to catalog's chain
    return heap


__all__ = ["bind_heap"]
