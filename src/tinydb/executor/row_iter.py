"""Row iterators over the on-disk heap.

T-5.2 introduces :class:`TableScan` — a thin iterator over a single
:class:`~tinydb.storage.heap.Heap` that yields ``(Rid, row_tuple)``
pairs.  Higher-level plan operators (:class:`SeqScan`, :class:`Filter`,
:class:`Project`) compose these streams.

Why yield ``Rid``?
------------------
DML operators (T-5.5) need the Rid to delete / update the underlying
heap slot.  SELECT-only consumers can ignore the Rid with ``_``.
"""

from __future__ import annotations

from typing import Iterator, Sequence

from tinydb.storage.catalog import TableMeta
from tinydb.storage.heap import Heap, Rid
from tinydb.types.codec import decode_row
from tinydb.types.system import TypeTag


class TableScan:
    """Iterator over a Heap table — yields ``(rid, row_tuple)`` pairs.

    Decodes each slot's bytes through :func:`tinydb.types.codec.decode_row`
    using the table's declared :class:`TypeTag` sequence.  Tombstoned
    slots (where :meth:`Heap.read` returns ``None``) are skipped — the
    catalog invariant is that :meth:`Heap.scan` never yields a Rid
    whose slot is empty, but the defensive check costs nothing and
    protects against future heap refactors.
    """

    __slots__ = ("_heap", "_meta", "_tags")

    def __init__(self, heap: Heap, meta: TableMeta) -> None:
        self._heap = heap
        self._meta = meta
        self._tags: Sequence[TypeTag] = tuple(c.tag for c in meta.columns)

    def __iter__(self) -> Iterator[tuple]:
        for rid in self._heap.scan():
            blob = self._heap.read(rid)
            if blob is None:
                continue  # tombstoned slot — defensive
            yield rid, decode_row(blob, self._tags)


__all__ = ["TableScan"]
