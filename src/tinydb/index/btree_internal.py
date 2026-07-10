"""B-tree internal node — page layout and (de)serialisation.

The internal node is one :data:`~tinydb.storage.pager.PAGE_SIZE`-byte
page holding ``n`` separator keys and ``n + 1`` child page ids::

    offset  0: u8  node_type              (= 0x02)
    offset  1: u24 reserved               (zero)
    offset  4: u16 key_count              (= len(children) - 1)
    offset  6: u16 reserved               (zero)
    offset  8: u32 first_child_pid        (children[0])
    offset 12: payload start
        entries: [u16 key_len][key_bytes][u32 child_pid]
        for i in range(key_count):
            keys[i] separates children[i] and children[i+1]
            (so children[1..] live in the payload)

``_write_internal`` raises :class:`BTreeOverflowError` (from
:mod:`tinydb.index.btree`) when the next separator would not fit; the
insert path catches it and splits the internal node.
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

__all__ = ["InternalNode", "_read_internal", "_write_internal"]

# Header layout (kept in sync with btree_leaf.py).
_INTERNAL_NODE_TYPE: int = 0x02
_INTERNAL_KEY_COUNT_OFF: int = 4
_INTERNAL_FIRST_CHILD_OFF: int = 8
HEADER_SIZE: int = 12

_KEY_LEN_SIZE: int = 2
_CHILD_PID_SIZE: int = 4

_KEY_LEN_STRUCT = struct.Struct("<H")
_CHILD_PID_STRUCT = struct.Struct("<I")


@dataclass
class InternalNode:
    """In-memory representation of a B-tree internal-node page.

    ``keys`` has ``len(children) - 1`` separator keys; ``keys[i]``
    separates ``children[i]`` and ``children[i + 1]``.  The very first
    child is stored in the on-disk header (``first_child_pid``); the
    rest live in the payload entries alongside the separators.
    """

    keys: list[Any] = field(default_factory=list)
    children: list[int] = field(default_factory=list)


def _write_internal(
    pager: Pager, pid: int, node: InternalNode, key_type: TypeTag
) -> None:
    """Encode ``node`` and overwrite page ``pid``.

    Raises :class:`BTreeOverflowError` if the separator entries would
    not fit in a single page.
    """
    if not node.children:
        raise ValueError("internal node must have at least one child")

    page = bytearray(PAGE_SIZE)
    page[0] = _INTERNAL_NODE_TYPE  # type byte at offset 0
    struct.pack_into("<H", page, _INTERNAL_KEY_COUNT_OFF, len(node.keys))
    struct.pack_into("<I", page, _INTERNAL_FIRST_CHILD_OFF, node.children[0])
    # offsets 1..4 and 6..8 stay zero (reserved).

    offset = HEADER_SIZE
    for sep_key, child_pid in zip(node.keys, node.children[1:]):
        encoded = encode_value(sep_key, key_type)
        key_len = len(encoded)
        if key_len > 0xFFFF:
            raise ValueError(
                f"encoded key too long: {key_len} bytes (max 65535)"
            )
        needed = _KEY_LEN_SIZE + key_len + _CHILD_PID_SIZE
        if offset + needed > PAGE_SIZE:
            raise BTreeOverflowError(
                f"internal overflow on page {pid}: entry "
                f"{len(node.keys)} does not fit "
                f"({offset + needed} > {PAGE_SIZE})"
            )
        _KEY_LEN_STRUCT.pack_into(page, offset, key_len)
        offset += _KEY_LEN_SIZE
        page[offset : offset + key_len] = encoded
        offset += key_len
        _CHILD_PID_STRUCT.pack_into(page, offset, child_pid)
        offset += _CHILD_PID_SIZE

    pager.write_page(pid, bytes(page))


def _read_internal(
    pager: Pager, pid: int, key_type: TypeTag | None = None
) -> InternalNode:
    """Decode page ``pid`` into an :class:`InternalNode`.

    The ``key_type`` argument is kept for symmetry with the leaf reader
    but unused — the on-wire tag byte at the front of each encoded key
    is authoritative.  ``key_type`` is optional so callers reading for
    inspection (e.g. tests) can pass just ``(pager, pid)``.
    """
    del key_type  # on-wire tag is authoritative
    page = pager.read_page(pid)
    node_type = page[0]
    if node_type != _INTERNAL_NODE_TYPE:
        raise ValueError(
            f"page {pid} is not an internal (node_type=0x{node_type:02x})"
        )
    (key_count,) = struct.unpack_from("<H", page, _INTERNAL_KEY_COUNT_OFF)
    (first_child,) = struct.unpack_from("<I", page, _INTERNAL_FIRST_CHILD_OFF)

    keys: list[Any] = []
    children: list[int] = [first_child]
    offset = HEADER_SIZE
    for _ in range(key_count):
        (key_len,) = _KEY_LEN_STRUCT.unpack_from(page, offset)
        offset += _KEY_LEN_SIZE
        key_buf = page[offset : offset + key_len]
        value, _ = decode_value(key_buf, 0)
        offset += key_len
        (child_pid,) = _CHILD_PID_STRUCT.unpack_from(page, offset)
        offset += _CHILD_PID_SIZE
        keys.append(value)
        children.append(child_pid)

    return InternalNode(keys=keys, children=children)