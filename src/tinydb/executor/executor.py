"""Executor — drive a :class:`Plan` tree against a :class:`Catalog`.

T-5.2 supports only ``SeqScan`` / ``Filter`` / ``Project``.  T-5.3
adds ``IndexScan``; T-5.5 adds DML; T-5.6 adds aggregates; T-6.6
plumbs the optional :class:`TransactionManager` so DML page writes
become part of the WAL.

Split out of :mod:`tinydb.executor.planner` to keep the planner under
its 280-line file cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from tinydb.executor.ops import Plan
from tinydb.index.btree import BTreeIndex
from tinydb.index.manager import IndexManager
from tinydb.storage.catalog import Catalog, TableMeta
from tinydb.storage.heap import Heap
from tinydb.storage.pager import Pager


@dataclass
class Executor:
    """Drive a :class:`Plan` tree against a :class:`Catalog`.

    The executor owns a per-table :class:`Heap` cache so repeated
    ``SeqScan`` accesses don't re-bind a fresh heap.  Reads share a
    single :class:`Pager` (passed at construction) so the catalog
    and the heap pages see consistent bytes.

    ``indexer`` is optional: when present the executor can resolve
    :class:`~tinydb.executor.ops.IndexScan` plans against the live
    B-tree indexes; when ``None`` the planner's index-selection path
    will skip and the executor falls back to SeqScan.

    ``mgr`` is optional (T-6.6): when present the executor forwards
    ``mgr.log_page_write`` to each new :class:`Heap` so DML page
    mutations get logged into the WAL.  When ``None`` DML is silent
    on the WAL (autocommit / single-shot CLI use).
    """

    catalog: Catalog
    pager: Optional[Pager] = None
    indexer: Optional[IndexManager] = None
    mgr: object = None
    _heaps: dict = field(default_factory=dict)

    def execute(self, plan: Plan) -> list:
        """Materialise the rows of ``plan`` into a list of tuples.

        SELECT returns a flat list of row tuples (in projection order).
        DML (Insert/Update/Delete) returns ``[(affected_count,)]``
        (T-5.5).  Sort / Limit run via ``plan.open`` (T-5.4).
        """
        return list(plan.open(self))

    def heap_for(self, meta: TableMeta) -> Heap:
        """Return the Heap bound to ``meta``, creating it on first access.

        Falls back to the catalog's pager when the executor was built
        without one — the catalog and the heap share the same page
        file, so this is safe in single-file deployments.
        """
        heap = self._heaps.get(meta.table_id)
        if heap is not None:
            return heap
        pager = self.pager
        if pager is None:
            pager = getattr(self.catalog, "_pager", None)
        if pager is None:
            raise RuntimeError(
                "Executor needs a Pager to bind heaps (pager=None)"
            )
        cb = getattr(self.mgr, "log_page_write", None) if self.mgr else None
        heap = Heap(pager, table_id=meta.table_id, on_page_write=cb)
        heap._head_pid = meta.heap_pid  # rebind to catalog's heap
        self._heaps[meta.table_id] = heap
        return heap

    def name_to_idx_for(self, table: str) -> dict:
        """Return ``{column_name: row_position}`` for the named table."""
        meta = self.catalog.get_table(table)
        return {c.name: i for i, c in enumerate(meta.columns)}

    def indexer_for(self, table: str, index_name: str) -> Optional[BTreeIndex]:
        """Return the live :class:`BTreeIndex` for ``index_name``.

        ``None`` when no :class:`IndexManager` is bound or the index
        is not registered.  IndexScan.open uses this to resolve the
        B-tree without reaching into the manager directly.
        """
        if self.indexer is None:
            return None
        return self.indexer.get_by_name(index_name)


__all__ = ["Executor"]
