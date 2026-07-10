"""B-tree leaf node — page layout and (de)serialisation.

The leaf is one :data:`~tinydb.storage.pager.PAGE_SIZE`-byte page::

    offset  0: u8  node_type              (= 0x01)
    offset  1: u24 reserved               (zero)
    offset  4: u32 next_leaf_pid          (sibling chain; 0xFFFFFFFF = end)
    offset  8: u16 key_count
    offset 10: u16 reserved               (zero)
    offset 12: payload start
        entries: [u16 key_len][key_bytes][u32 page_id][u16 slot_id]

``_write_leaf`` raises :class:`BTreeOverflowError` (from
:mod:`tinydb.index.btree`) when the next entry would not fit; the
insert path catches it and splits the leaf.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

from tinydb.errors import BTreeOverflowError
from tinydb.storage.heap import Rid
from tinydb.storage.pager import PAGE_SIZE, Pager
from tinydb.types.codec import decode_value, encode_value
from tinydb.types.system import TypeTag

# Sentinel for "no sibling leaf" (also re-exported from btree).
NO_NEXT: int = 0xFFFFFFFF

__all__ = ["LeafNode", "NO_NEXT", "_read_leaf", "_read_leaf_from_bytes", "_write_leaf"]

# Header layout (kept in sync with btree_internal.py).
_LEAF_NODE_TYPE: int = 0x01
_LEAF_NEXT_PID_OFF: int = 4
_LEAF_KEY_COUNT_OFF: int = 8
HEADER_SIZE: int = 12

# Payload entry field sizes.
_KEY_LEN_SIZE: int = 2
_RID_PAGE_SIZE: int = 4
_RID_SLOT_SIZE: int = 2

_KEY_LEN_STRUCT = struct.Struct("<H")
_RID_PAGE_STRUCT = struct.Struct("<I")
_RID_SLOT_STRUCT = struct.Struct("<H")


@dataclass
class LeafNode:
    """In-memory representation of a single B-tree leaf page.

    ``keys`` and ``rids`` are parallel lists sorted ascending by
    ``keys``; duplicates are permitted (B-trees allow non-unique keys).
    ``next_leaf_pid`` points to the next page in forward-scan order, or
    :data:`NO_NEXT` if this is the tail leaf.
    """

    keys: list[Any] = field(default_factory=list)
    rids: list[Rid] = field(default_factory=list)
    next_leaf_pid: int = NO_NEXT


def _write_leaf(pager: Pager, pid: int, leaf: LeafNode, key_type: TypeTag) -> None:
    """Encode ``leaf`` and overwrite page ``pid``.

    Raises :class:`BTreeOverflowError` if the entries would not fit in
    a single page; the insert path catches this and splits the leaf.
    The page is always exactly :data:`PAGE_SIZE` bytes; trailing bytes
    after the last entry are left as zero.
    """
    page = bytearray(PAGE_SIZE)
    page[0] = _LEAF_NODE_TYPE  # type byte at offset 0
    struct.pack_into("<I", page, _LEAF_NEXT_PID_OFF, leaf.next_leaf_pid)
    struct.pack_into("<H", page, _LEAF_KEY_COUNT_OFF, len(leaf.keys))
    # offsets 1..4 and 10..12 stay zero (reserved).

    offset = HEADER_SIZE
    for key, rid in zip(leaf.keys, leaf.rids):
        encoded = encode_value(key, key_type)
        key_len = len(encoded)
        if key_len > 0xFFFF:
            raise ValueError(
                f"encoded key too long: {key_len} bytes (max 65535)"
            )
        needed = _KEY_LEN_SIZE + key_len + _RID_PAGE_SIZE + _RID_SLOT_SIZE
        if offset + needed > PAGE_SIZE:
            raise BTreeOverflowError(
                f"leaf overflow on page {pid}: entry "
                f"{len(leaf.keys)} does not fit "
                f"({offset + needed} > {PAGE_SIZE})"
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


def _read_leaf(pager: Pager, pid: int) -> LeafNode:
    """Decode page ``pid`` into a :class:`LeafNode`.

    Thin wrapper that reads the page and delegates to
    :func:`_read_leaf_from_bytes`.  Callers that already hold the
    page bytes (e.g. ``_read_node_view`` after type-byte inspection)
    should call the from-bytes variant to avoid a second read.

    Accepts a 0x00 type byte (freshly allocated, never written) as an
    empty leaf for T-4.1 backward compatibility.  Also coerces a
    zero-filled ``next_leaf_pid`` to :data:`NO_NEXT` (NIT #1) so chain
    walking never dereferences page 0.
    """
    return _read_leaf_from_bytes(pager.read_page(pid), pid)


def _read_leaf_from_bytes(page: bytes, pid: int) -> LeafNode:
    """Decode an already-read leaf ``page`` into a :class:`LeafNode`.

    The on-wire tag byte at offset 0 is authoritative; no separate
    ``key_type`` argument is needed.  See :func:`_read_leaf` for the
    backward-compat coercion of a stale ``next_leaf_pid == 0``.
    """
    node_type = page[0]
    if node_type not in (0x00, _LEAF_NODE_TYPE):
        raise ValueError(
            f"page {pid} is not a leaf (node_type=0x{node_type:02x})"
        )
    (next_pid,) = struct.unpack_from("<I", page, _LEAF_NEXT_PID_OFF)
    (key_count,) = struct.unpack_from("<H", page, _LEAF_KEY_COUNT_OFF)

    keys: list[Any] = []
    rids: list[Rid] = []
    offset = HEADER_SIZE
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

    # NIT #1 fix: T-4.1 leaves were persisted with next_leaf_pid == 0;
    # coerce to NO_NEXT once a split introduces siblings so chain walks
    # don't dereference page 0.
    if next_pid == 0 and key_count == 0:
        next_pid = NO_NEXT

    return LeafNode(keys=keys, rids=rids, next_leaf_pid=next_pid)