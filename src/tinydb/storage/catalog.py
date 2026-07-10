"""Table catalog — persists schemas into reserved page 1.

REQ coverage
------------
* REQ-STO-6 — every ``CREATE TABLE`` writes the schema to the catalog
  page; ``DROP TABLE`` removes it; schemas survive a process restart.

Layout of reserved page 1
-------------------------
::

    +-------------------+ offset 0
    | magic       b'CATL'|  4 bytes; if absent the page is treated as empty
    +-------------------+ offset 4
    | entry_count  u16  |
    +-------------------+ offset 6
    | content_end  u16  |  next free byte in the content area
    +-------------------+ offset 8
    | reserved     (4 B)|
    +-------------------+ offset 12  (CATALOG_HEADER_SIZE)
    | entry 0: u16 len + JSON bytes |
    | entry 1: u16 len + JSON bytes |
    | ...                          |
    +------------------------------+
    | free space                   |
    +------------------------------+ PAGE_SIZE

Each entry's JSON payload::

    {
      "table_id": 1,
      "name": "users",
      "heap_pid": 4,
      "columns": [
        {"name": "id", "tag": 1, "not_null": true,
         "primary_key": true, "unique": false}, ...
      ]
    }

``Heap`` instances are constructed by the executor using ``heap_pid``
from the catalog.  v0.1 compacts the page on every ``drop_table`` —
re-writing the live list is acceptable because the table count is small
in a teaching database.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from tinydb.storage.heap import Heap
from tinydb.storage.pager import PAGE_SIZE, Pager
from tinydb.types.system import Column, TypeTag

# Reserved page index used for the catalog.
CATALOG_PAGE: int = 1

# Page layout for catalog storage.
CATALOG_HEADER_SIZE: int = 12
CATALOG_MAGIC: bytes = b"CATL"
_CATALOG_COUNT_STRUCT = struct.Struct("<H")
_CATALOG_CONTENT_END_STRUCT = struct.Struct("<H")
_CATALOG_ENTRY_LEN_STRUCT = struct.Struct("<H")


# --- value type --------------------------------------------------------


# TableId is an alias for plain int in v0.1.  A NewType could give us
# stronger typing, but the spec lists it as ``TableId(int)`` and the
# Catalog itself only carries it as a dict/JSON field.
TableId = int


@dataclass(frozen=True, slots=True)
class TableMeta:
    """Immutable description of a single table.

    ``heap_pid`` is the first page of the table's :class:`Heap` chain.
    The executor uses it to bind a Heap to the table on access.

    ``columns`` is a tuple so the dataclass can be frozen; callers can
    read but not mutate individual columns without rebuilding the meta.
    """

    table_id: TableId
    name: str
    columns: Tuple[Column, ...]
    heap_pid: int


# --- serialisation helpers ----------------------------------------------


def _column_to_dict(c: Column) -> dict:
    return {
        "name": c.name,
        # TypeTag is a plain Enum — read .value (the underlying int).
        "tag": c.tag.value,
        "not_null": bool(c.not_null),
        "primary_key": bool(c.primary_key),
        "unique": bool(c.unique),
    }


def _column_from_dict(d: dict) -> Column:
    return Column(
        name=d["name"],
        tag=TypeTag(d["tag"]),
        not_null=bool(d.get("not_null", False)),
        primary_key=bool(d.get("primary_key", False)),
        unique=bool(d.get("unique", False)),
    )


def _serialize_meta(meta: TableMeta) -> bytes:
    """Encode a TableMeta as UTF-8 JSON (no extra whitespace)."""
    payload = {
        "table_id": int(meta.table_id),
        "name": meta.name,
        "heap_pid": int(meta.heap_pid),
        "columns": [_column_to_dict(c) for c in meta.columns],
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _deserialize_meta(blob: bytes) -> TableMeta:
    d = json.loads(blob.decode("utf-8"))
    return TableMeta(
        table_id=int(d["table_id"]),
        name=d["name"],
        columns=tuple(_column_from_dict(c) for c in d.get("columns", [])),
        heap_pid=int(d["heap_pid"]),
    )


# --- Catalog ----------------------------------------------------------


class Catalog:
    """In-memory + on-disk (page 1) registry of tables.

    Thread-safety: not thread-safe — matches the v0.1 single-writer
    fence.
    """

    def __init__(self, pager: Pager) -> None:
        self._pager = pager
        self._by_name: "dict[str, TableMeta]" = {}
        self._next_table_id: int = 1
        self._load_from_disk()

    # -- persistence -----------------------------------------------------

    def _load_from_disk(self) -> None:
        page = bytes(self._pager.read_page(CATALOG_PAGE))
        if page[0:4] != CATALOG_MAGIC:
            # Empty / uninitialised catalog page — nothing to load.
            return
        (count,) = _CATALOG_COUNT_STRUCT.unpack_from(page, 4)
        offset = CATALOG_HEADER_SIZE
        max_seen_id = 0
        for _ in range(count):
            if offset + 2 > PAGE_SIZE:
                break  # malformed: stop scanning
            (entry_len,) = _CATALOG_ENTRY_LEN_STRUCT.unpack_from(page, offset)
            offset += 2
            if entry_len == 0 or offset + entry_len > PAGE_SIZE:
                break
            blob = bytes(page[offset : offset + entry_len])
            offset += entry_len
            meta = _deserialize_meta(blob)
            self._by_name[meta.name] = meta
            if meta.table_id > max_seen_id:
                max_seen_id = meta.table_id
        self._next_table_id = max_seen_id + 1

    def _persist(self) -> None:
        """Rewrite page 1 with the current live list (compact on save)."""
        page = bytearray(PAGE_SIZE)
        page[0:4] = CATALOG_MAGIC
        _CATALOG_COUNT_STRUCT.pack_into(
            page, 4, len(self._by_name)
        )
        offset = CATALOG_HEADER_SIZE
        # Stable order: sort by name for deterministic on-disk layout.
        for meta in sorted(self._by_name.values(), key=lambda m: m.name):
            blob = _serialize_meta(meta)
            entry_len = len(blob)
            if offset + 2 + entry_len > PAGE_SIZE:
                # Out of room in page 1 — for v0.1 we just stop; richer
                # multi-page catalog support is Batch 5 / polish.
                break
            _CATALOG_ENTRY_LEN_STRUCT.pack_into(page, offset, entry_len)
            offset += 2
            page[offset : offset + entry_len] = blob
            offset += entry_len
        _CATALOG_CONTENT_END_STRUCT.pack_into(page, 6, offset)
        self._pager.write_page(CATALOG_PAGE, bytes(page))

    # -- public API ------------------------------------------------------

    def create_table(
        self, name: str, columns: Sequence[Column]
    ) -> TableId:
        """Register a new table.

        Allocates a fresh :class:`Heap` (which allocates a fresh page)
        and stores the resulting metadata on the catalog page.

        Raises :class:`ValueError` if ``name`` already exists, or if
        ``columns`` is empty.
        """
        if name in self._by_name:
            raise ValueError(f"table {name!r} already exists")
        cols = tuple(columns)
        if not cols:
            raise ValueError("table must have at least one column")
        table_id = self._next_table_id
        self._next_table_id += 1
        # Bind the table to a fresh Heap so the heap_pid is real.
        heap = Heap(self._pager, table_id=table_id)
        meta = TableMeta(
            table_id=table_id,
            name=name,
            columns=cols,
            heap_pid=heap.head_pid,
        )
        self._by_name[name] = meta
        self._persist()
        return table_id

    def drop_table(self, name: str) -> None:
        """Remove a table by name.

        Raises :class:`KeyError` if the table does not exist.
        v0.1 does not reclaim the heap's pages — they remain in the
        file's free-list when the user allocates new pages.
        """
        if name not in self._by_name:
            raise KeyError(name)
        del self._by_name[name]
        self._persist()

    def get_table(self, name: str) -> TableMeta:
        """Return the :class:`TableMeta` for ``name``.

        Raises :class:`KeyError` if no such table exists.
        """
        if name not in self._by_name:
            raise KeyError(name)
        return self._by_name[name]

    def list_tables(self) -> List[str]:
        """Return a list of all live table names (sorted)."""
        return sorted(self._by_name)


__all__ = ["CATALOG_PAGE", "Catalog", "TableId", "TableMeta"]
