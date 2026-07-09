"""Slotted-page record store.

REQ coverage
------------
* REQ-STO-5 — heap of records organised in slots within pages.
* REQ-STO-2 — cross-page overflow: a fresh page is allocated and linked
  when the current tail cannot hold a new record + slot.
* REQ-STO-7 — :class:`~tinydb.storage.free_space.FreeSpaceMap`
  bookkeeping; the Heap refreshes per-page free bytes after every write.

Page layout (PAGE_SIZE bytes, 4096 by default)::

    +---------------------+ offset 0
    | next_page_id   u32  |  0xFFFFFFFF = end-of-chain
    +---------------------+ offset 4
    | slot_count     u16  |
    +---------------------+ offset 6
    | data_end       u16  |  next free byte in data area
    +---------------------+ offset 8
    | reserved (4 B)      |
    +---------------------+ offset 12 (DATA_START)
    | data records grow  →
    | ...
    +---------------------+  slots_start = PAGE_SIZE - slot_count * SLOT_SIZE
    | free space
    +---------------------+
    | slot N-1 (6 bytes)  |  ← slots grow backward
    | ...
    | slot 0 (6 bytes)    |
    +---------------------+ PAGE_SIZE

Each slot is 6 bytes: ``u16`` rec_offset, ``u16`` rec_length, ``u8``
flags (0 = empty / deleted, 1 = used), ``u8`` reserved.

On a delete the slot is just flagged empty; the data area is not
compacted.  Free bytes shrink only on inserts.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator, Optional

from tinydb.storage.free_space import FreeSpaceMap
from tinydb.storage.pager import PAGE_SIZE, Pager

# --- layout constants ---------------------------------------------------

HEADER_SIZE: int = 12
DATA_START: int = HEADER_SIZE
SLOT_SIZE: int = 6
NO_NEXT: int = 0xFFFF_FFFF

# --- value type --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rid:
    """Locator for a single record inside a heap page.

    ``page_id`` identifies the slotted page; ``slot_id`` the slot within
    that page.  An empty / out-of-range slot reads back as ``None``.
    """

    page_id: int
    slot_id: int


# --- page header / slot helpers ----------------------------------------


def _read_header(page: bytes) -> tuple:
    """Return ``(next_page_id, slot_count, data_end)`` from page bytes 0..7."""
    next_pid = struct.unpack_from("<I", page, 0)[0]
    slot_count = struct.unpack_from("<H", page, 4)[0]
    data_end = struct.unpack_from("<H", page, 6)[0]
    return next_pid, slot_count, data_end


def _write_header(
    page: bytearray, next_pid: int, slot_count: int, data_end: int
) -> None:
    """Write the 8-byte logical header; bytes 8..12 stay zero (reserved)."""
    struct.pack_into("<I", page, 0, next_pid)
    struct.pack_into("<H", page, 4, slot_count)
    struct.pack_into("<H", page, 6, data_end)


def _slot_offset(slot_id: int) -> int:
    """Byte offset of ``slot_id`` in the slot table (backward from PAGE_SIZE)."""
    return PAGE_SIZE - (slot_id + 1) * SLOT_SIZE


def _read_slot(page: bytes, slot_id: int) -> tuple:
    """Return ``(rec_offset, rec_length, flags)``."""
    return struct.unpack_from("<HHB", page, _slot_offset(slot_id))


def _write_slot(
    page: bytearray, slot_id: int, rec_offset: int, rec_length: int, flags: int
) -> None:
    """Write slot's offset/length/flags; the reserved byte stays zero."""
    struct.pack_into(
        "<HHB", page, _slot_offset(slot_id), rec_offset, rec_length, flags
    )


def _slots_start(slot_count: int) -> int:
    """Byte offset where the slot table begins (slot_count slots)."""
    return PAGE_SIZE - slot_count * SLOT_SIZE


# --- Heap --------------------------------------------------------------


class Heap:
    """Slotted-page record store backed by a Pager.

    A Heap owns a singly-linked list of data pages (the *chain*).
    Inserts scan the chain to find a page with room; if none, a fresh
    overflow page is allocated and linked at the previous tail.

    Thread-safety: not thread-safe — matches the v0.1 single-writer
    fence.
    """

    def __init__(self, pager: Pager, table_id: int = 0) -> None:
        self._pager = pager
        self._table_id = table_id
        # Allocate and initialise the first page (header = empty chain head).
        self._head_pid: int = pager.allocate_page()
        page = bytearray(pager.read_page(self._head_pid))
        _write_header(page, NO_NEXT, 0, DATA_START)
        pager.write_page(self._head_pid, bytes(page))
        # Per-page free-byte tracker (REQ-STO-7).
        self._fsm = FreeSpaceMap()
        self._refresh_fsm(self._head_pid)

    # -- introspection ---------------------------------------------------

    @property
    def head_pid(self) -> int:
        """Page id of the first (head) page in the chain."""
        return self._head_pid

    @property
    def table_id(self) -> int:
        return self._table_id

    @property
    def free_space(self) -> FreeSpaceMap:
        """Live :class:`FreeSpaceMap`; updated on every insert/delete."""
        return self._fsm

    # -- core API --------------------------------------------------------

    def insert(self, encoded: bytes) -> Rid:
        """Append ``encoded`` to the heap and return its Rid.

        Walks the chain to find a page with enough room for
        ``SLOT_SIZE + len(encoded)`` bytes.  Allocates and links a new
        overflow page when the tail cannot fit one more (slot, record)
        pair.
        """
        record_len = len(encoded)
        needed = SLOT_SIZE + record_len

        pid = self._head_pid
        while True:
            free = self._refresh_fsm(pid)
            if free >= needed:
                break
            # Not enough room here — follow the chain.
            page = self._pager.read_page(pid)
            next_pid = struct.unpack_from("<I", page, 0)[0]
            if next_pid == NO_NEXT:
                # Tail — no room anywhere; spill to a fresh page.
                new_pid = self._append_overflow_page(pid)
                # Refresh the stale tail (next pointer changed) and the
                # new page (initial FSM entry).
                self._refresh_fsm(pid)
                self._refresh_fsm(new_pid)
                pid = new_pid
                break
            pid = next_pid

        # ``pid`` has room.  Append the record and a fresh slot.
        page = bytearray(self._pager.read_page(pid))
        next_pid, slot_count, data_end = _read_header(page)
        new_slot_id = slot_count
        new_slot_count = slot_count + 1
        new_data_end = data_end + record_len
        # Copy the record bytes into the data area.
        page[data_end : data_end + record_len] = encoded
        # Write the newly-grown slot at its tail position.
        _write_slot(page, new_slot_id, data_end, record_len, 1)
        # Update the header in place.
        _write_header(page, next_pid, new_slot_count, new_data_end)
        self._pager.write_page(pid, bytes(page))
        self._refresh_fsm(pid)
        return Rid(page_id=pid, slot_id=new_slot_id)

    def read(self, rid: Rid) -> Optional[bytes]:
        """Return the bytes at ``rid``, or ``None`` if the slot is empty."""
        page = self._pager.read_page(rid.page_id)
        _, slot_count, _ = _read_header(page)
        if rid.slot_id >= slot_count:
            return None
        rec_offset, rec_length, flags = _read_slot(page, rid.slot_id)
        if flags == 0 or rec_length == 0:
            return None
        return bytes(page[rec_offset : rec_offset + rec_length])

    def delete(self, rid: Rid) -> None:
        """Mark the slot at ``rid`` empty.

        Out-of-range Rids are silently ignored — deleting a slot that
        was never inserted is a no-op rather than an error.
        """
        page = bytearray(self._pager.read_page(rid.page_id))
        _, slot_count, _ = _read_header(page)
        if rid.slot_id >= slot_count:
            return
        _write_slot(page, rid.slot_id, 0, 0, 0)
        self._pager.write_page(rid.page_id, bytes(page))

    def scan(self) -> Iterator[Rid]:
        """Yield every live Rid in the heap, page-by-page, slot-in-order."""
        pid: int = self._head_pid
        while pid != NO_NEXT:
            page = self._pager.read_page(pid)
            next_pid, slot_count, _ = _read_header(page)
            for slot_id in range(slot_count):
                _, _, flags = _read_slot(page, slot_id)
                if flags != 0:
                    yield Rid(page_id=pid, slot_id=slot_id)
            pid = next_pid

    # -- internals --------------------------------------------------------

    def _refresh_fsm(self, pid: int) -> int:
        """Recompute and record free bytes for ``pid``; return the free count."""
        page = self._pager.read_page(pid)
        _, slot_count, data_end = _read_header(page)
        free = _slots_start(slot_count) - data_end
        self._fsm.update(pid, free)
        return free

    def _append_overflow_page(self, tail_pid: int) -> int:
        """Allocate a fresh page, link it after ``tail_pid``, return its pid."""
        new_pid = self._pager.allocate_page()
        # Update the old tail's next pointer.
        tail_page = bytearray(self._pager.read_page(tail_pid))
        next_pid, slot_count, data_end = _read_header(tail_page)
        _write_header(tail_page, new_pid, slot_count, data_end)
        self._pager.write_page(tail_pid, bytes(tail_page))
        # Initialise the new page as a fresh chain tail.
        new_page = bytearray(self._pager.read_page(new_pid))
        _write_header(new_page, NO_NEXT, 0, DATA_START)
        self._pager.write_page(new_pid, bytes(new_page))
        return new_pid


__all__ = ["Heap", "Rid"]
