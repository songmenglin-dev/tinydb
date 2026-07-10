"""B-tree leaf-only index — single-leaf insert + scan, no split.

T-4.1 covers REQ-IDX-1 (leaf part) only: a single in-memory leaf node
holding ``(key, rid)`` pairs sorted ascending by key, persisted to a
4 KB page via the :class:`~tinydb.storage.pager.Pager`.

Page layout
-----------

Each leaf occupies exactly one page::

    offset 0: u32  next_leaf_pid   (sibling chain; 0xFFFFFFFF = end)
    offset 4: u16  key_count       (number of (key, rid) pairs)
    offset 6: u16  reserved        (zero)
    offset 8: payload start

Payload is a flat sequence of fixed-ish entries, each one::

    [u16 key_len][key_bytes][u32 page_id][u16 slot_id]

``key_bytes`` is whatever :func:`tinydb.types.codec.encode_value`
produces for the configured ``TypeTag`` (it carries the tag byte at the
front, which is what :func:`tinydb.types.codec.decode_value` reads on
the way out).

Splitting, internal nodes, tree-walk search, and delete/rebalance are
deferred to T-4.2..T-4.4 — this module intentionally grows no wider
than a single leaf.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Iterator

from tinydb.storage.heap import Rid
from tinydb.storage.pager import PAGE_SIZE, Pager
from tinydb.types.codec import decode_value, encode_value
from tinydb.types.system import TypeTag

# Sentinel: no sibling leaf (or, more precisely, "this is the tail of
# the chain"; the first leaf has next_leaf_pid == NO_NEXT for now since
# there is only one leaf).
NO_NEXT: int = 0xFFFFFFFF

# Header occupies the first 8 bytes of the page; payload follows.
LEAF_HEADER_SIZE: int = 8

# Page-header field offsets.
_NEXT_PID_OFF: int = 0
_KEY_COUNT_OFF: int = 4

# Payload entry field sizes.
_KEY_LEN_SIZE: int = 2
_RID_PAGE_SIZE: int = 4
_RID_SLOT_SIZE: int = 2

# Per-entry struct formats.
_KEY_LEN_STRUCT = struct.Struct("<H")
_RID_PAGE_STRUCT = struct.Struct("<I")
_RID_SLOT_STRUCT = struct.Struct("<H")


@dataclass
class LeafNode:
    """In-memory representation of a single B-tree leaf page.

    ``keys`` and ``rids`` are parallel lists sorted ascending by ``keys``;
    duplicates are permitted (B-trees allow non-unique keys).  When
    T-4.2 introduces splits, leaves gain siblings and ``next_leaf_pid``
    points to the next page in forward-scan order.
    """

    keys: list[Any] = field(default_factory=list)
    rids: list[Rid] = field(default_factory=list)
    next_leaf_pid: int = NO_NEXT


# --- page (de)serialisation --------------------------------------------


def _read_leaf(pager: Pager, pid: int, key_type: TypeTag) -> LeafNode:
    """Decode page ``pid`` into a :class:`LeafNode`.

    The key ``TypeTag`` is supplied so decode_value can validate, but
    we only use it implicitly via the codec — the on-wire byte at the
    front of each entry is authoritative.
    """
    del key_type  # tag is read from the encoded bytes; the param is for clarity.
    page = pager.read_page(pid)
    (next_pid,) = struct.unpack_from("<I", page, _NEXT_PID_OFF)
    (key_count,) = struct.unpack_from("<H", page, _KEY_COUNT_OFF)

    keys: list[Any] = []
    rids: list[Rid] = []
    offset = LEAF_HEADER_SIZE
    for _ in range(key_count):
        (key_len,) = _KEY_LEN_STRUCT.unpack_from(page, offset)
        offset += _KEY_LEN_SIZE
        key_buf = page[offset : offset + key_len]
        value, _ = decode_value(key_buf, 0)
        offset += key_len
        (page_id,) = _RID_PAGE_STRUCT.unpack_from(page, offset)
        offset += _RID_PAGE_SIZE
        (slot_id,) = _RID_SLOT_STRUCT.unpack_from(page, offset)
        offset += _RID_SLOT_SIZE
        keys.append(value)
        rids.append(Rid(page_id=page_id, slot_id=slot_id))
    return LeafNode(keys=keys, rids=rids, next_leaf_pid=next_pid)


def _write_leaf(pager: Pager, pid: int, leaf: LeafNode, key_type: TypeTag) -> None:
    """Encode ``leaf`` and overwrite page ``pid``.

    The page is always exactly :data:`PAGE_SIZE` bytes; trailing bytes
    after the last entry are left as zero.
    """
    page = bytearray(PAGE_SIZE)
    struct.pack_into("<I", page, _NEXT_PID_OFF, leaf.next_leaf_pid)
    struct.pack_into("<H", page, _KEY_COUNT_OFF, len(leaf.keys))
    # offsets 6..8 stay zero (reserved).

    offset = LEAF_HEADER_SIZE
    for key, rid in zip(leaf.keys, leaf.rids):
        encoded = encode_value(key, key_type)
        key_len = len(encoded)
        if key_len > 0xFFFF:
            raise ValueError(
                f"encoded key too long: {key_len} bytes (max 65535)"
            )
        _KEY_LEN_STRUCT.pack_into(page, offset, key_len)
        offset += _KEY_LEN_SIZE
        page[offset : offset + key_len] = encoded
        offset += key_len
        _RID_PAGE_STRUCT.pack_into(page, offset, rid.page_id)
        offset += _RID_PAGE_SIZE
        _RID_SLOT_STRUCT.pack_into(page, offset, rid.slot_id)
        offset += _RID_SLOT_SIZE

    pager.write_page(pid, bytes(page))


# --- BTreeIndex ---------------------------------------------------------


class BTreeIndex:
    """Single-leaf B-tree index over a Pager-backed 4 KB page.

    ``__init__`` performs no I/O — the root page is loaded lazily on
    the first read or write.  Each :meth:`insert` persists immediately
    (the leaf is the whole index, so there's no split to defer), and
    :meth:`flush` re-writes the current state for callers that want
    explicit persistence.

    Deferred to later tasks (T-4.2..T-4.4):

    * :meth:`delete` — raises :class:`NotImplementedError`.
    * :meth:`search` — raises :class:`NotImplementedError`; T-4.3
      will replace the linear leaf scan with a real tree walk.
    """

    def __init__(self, pager: Pager, root_pid: int, key_type: TypeTag) -> None:
        self._pager = pager
        self._root_pid = root_pid
        self._key_type = key_type
        self._leaf: LeafNode | None = None
        self._loaded: bool = False

    # -- helpers ---------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._leaf = _read_leaf(self._pager, self._root_pid, self._key_type)
            self._loaded = True

    def _persist(self) -> None:
        assert self._leaf is not None
        _write_leaf(self._pager, self._root_pid, self._leaf, self._key_type)

    def _lower_bound(self, key: Any) -> int:
        """Leftmost index where ``keys[i] >= key`` (a.k.a. ``bisect_left``).

        Used by :meth:`range` so every duplicate at ``lo`` is included.
        """
        assert self._leaf is not None
        lo, hi = 0, len(self._leaf.keys)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._leaf.keys[mid] < key:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def _upper_bound(self, key: Any) -> int:
        """Leftmost index where ``keys[i] > key`` (a.k.a. ``bisect_right``).

        Used by :meth:`insert` so duplicates keep their insertion
        order: a new key lands *after* any existing equals rather than
        before them.
        """
        assert self._leaf is not None
        lo, hi = 0, len(self._leaf.keys)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._leaf.keys[mid] <= key:
                lo = mid + 1
            else:
                hi = mid
        return lo

    # -- public API ------------------------------------------------------

    def search(self, key: Any) -> list[Rid]:
        """Return every rid whose key equals ``key``.

        Placeholder — the real tree-walk search arrives in T-4.3.
        """
        raise NotImplementedError("search via tree walk arrives in T-4.3")

    def range(
        self, lo: Any, hi: Any, *, inclusive: bool = True
    ) -> Iterator[Rid]:
        """Yield rids whose keys lie in ``[lo, hi]`` (or ``[lo, hi)``).

        Single-leaf for now: we binary-search the start position and
        walk forward until the key crosses ``hi``.  When T-4.2 adds
        splits this becomes a sibling-chain traversal.
        """
        if lo > hi:
            return
        self._ensure_loaded()
        assert self._leaf is not None
        start = self._lower_bound(lo)
        for i in range(start, len(self._leaf.keys)):
            key = self._leaf.keys[i]
            if inclusive:
                if key > hi:
                    break
            else:
                if key >= hi:
                    break
            yield self._leaf.rids[i]

    def insert(self, key: Any, rid: Rid) -> None:
        """Insert ``(key, rid)`` and persist the leaf immediately."""
        self._ensure_loaded()
        assert self._leaf is not None
        pos = self._upper_bound(key)
        self._leaf.keys.insert(pos, key)
        self._leaf.rids.insert(pos, rid)
        self._persist()

    def delete(self, key: Any, rid: Rid) -> None:
        """Remove ``(key, rid)`` from the leaf.

        Placeholder — delete + rebalance arrive in T-4.4.
        """
        raise NotImplementedError("delete + rebalance arrives in T-4.4")

    def flush(self) -> None:
        """Re-write the current leaf to disk.  Idempotent; cheap."""
        if self._loaded and self._leaf is not None:
            self._persist()


__all__ = ["BTreeIndex", "LeafNode", "NO_NEXT"]