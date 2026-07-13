"""IndexManager — catalog integration, write hooks, UNIQUE, persistence.

REQ coverage
------------
* REQ-IDX-4 — every INSERT / UPDATE / DELETE on a table maintains all
  indexes declared for that table.  The executor calls
  :meth:`on_insert` / :meth:`on_update` / :meth:`on_delete` on each
  write; the manager extracts the indexed key columns, looks up the
  matching B-tree indexes and updates them in place.
* REQ-IDX-5 — UNIQUE indexes reject duplicate keys at insert time and
  allow NULL values (NULL does not participate in the duplicate check).
* REQ-IDX-6 — index metadata (root_pid, columns, unique flag) is
  persisted in the catalog (page 2).  On restart, :class:`IndexManager`
  rebuilds :class:`BTreeIndex` objects by reading the root page for
  each persisted entry.

Key shape
---------
For an index on a single column ``c`` the B-tree key is the scalar
``row[c_idx]`` encoded under the column's own :class:`TypeTag`.
For composite indexes on ``(c1, c2, ...)`` the B-tree key is the
tuple ``(row[c1_idx], row[c2_idx], ...)`` encoded with
:class:`TypeTag.Json` — tuples round-trip as JSON lists (lex
order on lists matches lex order on tuples).

Deviation from the brief's "always pass tuples" recommendation: the
codec enforces strict value/tag pairing, so a one-element tuple
``(email_str,)`` under :class:`TypeTag.Text` fails.  Using a scalar
for single-column indexes keeps the codec happy; using a tuple for
composite indexes matches the T-4.5 lexicographic path.

NULL handling
-------------
NULLs are encoded with :class:`TypeTag.Null` and round-trip back to
Python ``None``.  The UNIQUE check skips keys that contain ``None``
because per REQ-IDX-5 NULL does not participate in the uniqueness
constraint.
"""

from __future__ import annotations

from typing import Any, List, Sequence, Tuple

from tinydb.errors import ConstraintViolation
from tinydb.index.btree import BTreeIndex
from tinydb.index.btree_pages import all_page_ids
from tinydb.storage.catalog import Catalog, IndexMeta, TableMeta
from tinydb.storage.heap import Rid
from tinydb.storage.pager import Pager
from tinydb.types.system import Column, TypeTag

__all__ = ["IndexManager", "IndexMeta"]


class IndexManager:
    """Maintain all B-tree indexes declared in the catalog.

    Lifecycle:

    * On construction the manager walks the catalog's index list and
      builds an in-memory map ``name -> IndexMeta`` and a parallel
      map ``name -> BTreeIndex``.  Each B-tree is bound to the
      ``root_pid`` from the catalog; its lazy load reads the page on
      first access (T-4.1 contract).
    * :meth:`create_index` allocates a fresh page for the new B-tree
      root, registers the metadata in the catalog, and adds the live
      :class:`BTreeIndex` to the in-memory map.
    * :meth:`on_insert` / :meth:`on_update` / :meth:`on_delete` are
      the write hooks the executor calls on every row mutation.

    Thread-safety: not thread-safe; matches the v0.1 single-writer
    fence.
    """

    def __init__(self, catalog: Catalog, pager: Pager) -> None:
        self._catalog = catalog
        self._pager = pager
        self._meta_by_name: dict[str, IndexMeta] = {}
        self._index_by_name: dict[str, BTreeIndex] = {}
        self._load_from_catalog()

    # -- helpers ---------------------------------------------------------

    def _load_from_catalog(self) -> None:
        """Rebuild the in-memory index map from the catalog."""
        for meta in self._catalog.all_indexes():
            self._meta_by_name[meta.name] = meta
            self._index_by_name[meta.name] = self._open_index(meta)

    def _open_index(self, meta: IndexMeta) -> BTreeIndex:
        """Open the B-tree for a persisted :class:`IndexMeta`."""
        table_meta = self._catalog.get_table(meta.table)
        key_type = self._indexed_key_type(table_meta, meta.columns)
        return BTreeIndex(self._pager, root_pid=meta.root_pid, key_type=key_type)

    @staticmethod
    def _indexed_key_type(table_meta: TableMeta, columns: Tuple[str, ...]) -> TypeTag:
        """Return the on-disk :class:`TypeTag` to use for B-tree keys.

        Single-column: uses the column's own tag (a scalar value
        encodes under the matching tag).  Composite: uses
        :class:`TypeTag.Json` (tuples round-trip as JSON lists).

        NULL keys are skipped entirely (see :meth:`on_insert`) so
        the key_type only needs to handle non-NULL values.
        """
        cols_by_name = {c.name: c for c in table_meta.columns}
        if len(columns) == 1:
            return cols_by_name[columns[0]].tag
        return TypeTag.Json

    @staticmethod
    def _extract_key(
        row: tuple,
        columns: Tuple[str, ...],
        table_meta: TableMeta,
    ) -> Any:
        """Return the B-tree key for ``row`` indexed by ``columns``.

        Single-column: returns the scalar value.  Multi-column:
        returns the tuple ``(row[col_0], row[col_1], ...)``.
        """
        col_to_idx = {c.name: i for i, c in enumerate(table_meta.columns)}
        if len(columns) == 1:
            return row[col_to_idx[columns[0]]]
        return tuple(row[col_to_idx[col]] for col in columns)

    @staticmethod
    def _key_contains_none(key: Any) -> bool:
        """Return True if ``key`` (scalar or tuple) contains ``None``.

        Per REQ-IDX-5 NULLs do not participate in the UNIQUE check.
        A scalar key is treated as a one-element sequence for the
        purpose of this check.
        """
        if isinstance(key, tuple):
            return any(v is None for v in key)
        return key is None

    def _indexes_for_table(self, table: str) -> list[tuple[IndexMeta, BTreeIndex]]:
        """Return all live ``(meta, index)`` pairs for ``table``."""
        return [
            (meta, self._index_by_name[name])
            for name, meta in self._meta_by_name.items()
            if meta.table == table
        ]

    # -- public API ------------------------------------------------------

    def create_index(
        self,
        name: str,
        table: str,
        columns: Sequence[str],
        *,
        unique: bool = False,
    ) -> IndexMeta:
        """Create a new index ``name`` on ``(table, columns)``.

        Allocates a fresh B-tree root page, registers the index in the
        catalog (so it survives restart, REQ-IDX-6) and adds a live
        :class:`BTreeIndex` to the in-memory map.

        Raises :class:`ValueError` on duplicate name, empty ``columns``;
        :class:`KeyError` if ``table`` is not registered.
        """
        if name in self._meta_by_name:
            raise ValueError(f"index {name!r} already exists")
        cols = tuple(columns)
        if not cols:
            raise ValueError("index must reference at least one column")
        # Validate the table and the columns early so we don't allocate
        # a page we'd then have to free.
        table_meta = self._catalog.get_table(table)
        col_names = {c.name for c in table_meta.columns}
        for col in cols:
            if col not in col_names:
                raise ValueError(
                    f"column {col!r} not in table {table!r}"
                )
        root_pid = self._pager.allocate_page()
        meta = self._catalog.create_index(
            name=name,
            table=table,
            columns=cols,
            root_pid=root_pid,
            unique=unique,
        )
        self._meta_by_name[name] = meta
        self._index_by_name[name] = self._open_index(meta)
        # Backfill: scan existing rows and populate the B-tree.
        # Rows inserted AFTER create_index are populated via
        # on_insert hooks; rows inserted BEFORE create_index are
        # picked up here.
        self._backfill_index(table_meta, cols, self._index_by_name[name])
        return meta

    def _backfill_index(self, table_meta, columns, idx) -> None:
        from tinydb.types.codec import decode_row
        from tinydb.storage.heap import Heap
        heap = Heap(self._pager)
        heap._head_pid = table_meta.heap_pid
        tags = tuple(c.tag for c in table_meta.columns)
        col_names = {c.name: i for i, c in enumerate(table_meta.columns)}
        col_idx = tuple(col_names[c] for c in columns)
        # Single-column: scalar key under the column's own tag.
        # Multi-column: tuple key encoded via Json (matches _extract_key).
        for rid in heap.scan():
            blob = heap.read(rid)
            if blob is None:
                continue
            row = decode_row(blob, tags)
            values = [row[i] for i in col_idx]
            if any(v is None for v in values):
                continue
            key = values[0] if len(values) == 1 else tuple(values)
            idx.insert(key, rid)

    def drop_index(self, name: str) -> None:
        """Drop the index ``name`` and free its B-tree pages.

        Walks the B-tree to discover every page it owns, then returns
        each one to the free list.  The catalog entry is removed first
        so that a crash mid-walk leaves the catalog consistent (the
        B-tree pages just become orphaned free-list candidates).

        Raises :class:`KeyError` if the index does not exist.
        """
        meta = self._catalog.drop_index(name)
        idx = self._index_by_name.pop(name, None)
        self._meta_by_name.pop(name, None)
        if idx is not None:
            for pid in all_page_ids(idx):
                if pid >= 4:  # skip reserved pages 0..3
                    self._pager.free_page(pid)

    def get(
        self, table: str, columns: Sequence[str]
    ) -> BTreeIndex | None:
        """Return the :class:`BTreeIndex` for ``(table, columns)`` or ``None``."""
        cols = tuple(columns)
        for name, meta in self._meta_by_name.items():
            if meta.table == table and meta.columns == cols:
                return self._index_by_name[name]
        return None

    def get_by_name(self, name: str) -> BTreeIndex | None:
        """Return the :class:`BTreeIndex` for ``name`` or ``None``."""
        idx = self._index_by_name.get(name)
        if idx is None:
            return None
        return idx

    def list_indexes(self, table: str | None = None) -> list[str]:
        """Return the live index names; optionally filtered by ``table``."""
        if table is None:
            return sorted(self._meta_by_name)
        return sorted(
            name
            for name, meta in self._meta_by_name.items()
            if meta.table == table
        )

    # -- write hooks (REQ-IDX-4 + REQ-IDX-5) -----------------------------

    def check_unique(self, table: str, row: tuple) -> None:
        """Raise :class:`ConstraintViolation` if ``row`` would clash with a
        UNIQUE index on ``table`` — without touching the index or the heap.

        Called by :class:`Insert` / :class:`Update` *before* the heap write
        so that a rejected row leaves no in-memory residue.  T-6.4 uses
        this to keep the in-memory heap clean on rollback; T-6.6 will
        replace the in-memory discard with a real UNDO log on disk.

        Only the new key is checked; existing rows keep their UNIQUE
        protection from :meth:`on_insert` / :meth:`on_update`.  NULLs
        are skipped from the uniqueness check (REQ-IDX-5), exactly
        as in :meth:`on_insert`.
        """
        table_meta = self._catalog.get_table(table)
        for meta, idx in self._indexes_for_table(table):
            if not meta.unique:
                continue
            key = self._extract_key(row, meta.columns, table_meta)
            if self._key_contains_none(key):
                continue
            if idx.search(key):
                raise ConstraintViolation(
                    f"UNIQUE constraint violated on {table!r}."
                    f"{'.'.join(meta.columns)}: duplicate key {key!r}"
                )

    def on_insert(self, table: str, rid: Rid, row: tuple) -> None:
        """Maintain every index on ``table`` after an INSERT.

        ``row`` is the encoded row tuple in the table's column order.
        For each index the manager extracts the relevant key columns,
        enforces UNIQUE (skipping NULLs) and inserts ``(key, rid)``.

        NULL handling: when the key contains ``None`` the entry is
        not added to the B-tree (the codec cannot round-trip a
        mixed-type key, and per REQ-IDX-5 NULL does not participate
        in the uniqueness check).
        """
        table_meta = self._catalog.get_table(table)
        for meta, idx in self._indexes_for_table(table):
            key = self._extract_key(row, meta.columns, table_meta)
            if self._key_contains_none(key):
                continue
            if meta.unique:
                existing = idx.search(key)
                if existing:
                    raise ConstraintViolation(
                        f"UNIQUE constraint violated on {table!r}."
                        f"{'.'.join(meta.columns)}: duplicate key {key!r}"
                    )
            idx.insert(key, rid)

    def on_update(
        self, table: str, rid: Rid, old_row: tuple, new_row: tuple
    ) -> None:
        """Maintain every index on ``table`` after an UPDATE.

        For each index the old key is removed and the new key inserted
        (in that order).  UNIQUE is enforced on the new key.  NULLs
        are skipped from indexing as in :meth:`on_insert`.
        """
        table_meta = self._catalog.get_table(table)
        for meta, idx in self._indexes_for_table(table):
            old_key = self._extract_key(old_row, meta.columns, table_meta)
            new_key = self._extract_key(new_row, meta.columns, table_meta)
            # Remove the old entry first (no-op if absent / if NULL).
            if not self._key_contains_none(old_key):
                idx.delete(old_key, rid)
            if self._key_contains_none(new_key):
                continue
            if meta.unique:
                existing = idx.search(new_key)
                if existing:
                    raise ConstraintViolation(
                        f"UNIQUE constraint violated on {table!r}."
                        f"{'.'.join(meta.columns)}: duplicate key {new_key!r}"
                    )
            idx.insert(new_key, rid)

    def on_delete(self, table: str, rid: Rid, row: tuple) -> None:
        """Maintain every index on ``table`` after a DELETE."""
        table_meta = self._catalog.get_table(table)
        for meta, idx in self._indexes_for_table(table):
            key = self._extract_key(row, meta.columns, table_meta)
            if self._key_contains_none(key):
                continue
            idx.delete(key, rid)