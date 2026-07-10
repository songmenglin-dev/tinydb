"""Fixed-size page I/O over a single ``.db`` file.

This is the lowest layer of the storage engine.  Above it sit the
:class:`~tinydb.storage.buffer_pool.BufferPool` (LRU cache) and the
table heap.  The pager knows nothing about rows, schemas, or the WAL —
its only job is to map a ``page_id`` to a 4 KB slice of the file.

File layout::

    +---------+---------+---------+---------+---------+---------+
    | Page 0  | Page 1  | Page 2  | Page 3  | Page 4  |  ...    |
    | header  | reserved catalog         |  data pages...        |
    +---------+---------+---------+---------+---------+---------+

Page 0 is the on-disk header.  Pages 1..3 are reserved for the catalog
(see T-2.4) and cannot be allocated for data.  Page 4 onward is where
records, free-space maps, B-tree nodes, and the WAL tail live.

Header (page 0) byte layout
---------------------------
* ``0..7``  : 8-byte ASCII magic :data:`MAGIC` (``"T1NYDB01"``).
* ``8..9``  : ``u16`` format version (``1``).
* ``10..11``: ``u16`` page size in bytes (always 4096 in v0.1).
* ``12..15``: ``u32`` total pages currently allocated in the file.
* ``16..19``: ``u32`` head of the free-page linked list, or
  ``0xFFFFFFFF`` when empty.
* ``20..4095``: reserved, currently zero.

The free list itself is a singly linked list threading through free
pages: each free page stores the next free ``page_id`` (or
``0xFFFFFFFF``) at offset ``0``.  Because the magic lives at offset 0,
the data in a free page overlaps the magic — but free pages are never
read as data, so this is fine.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import IO, Union

# --- public constants ----------------------------------------------------

#: Default (and only, in v0.1) page size in bytes.
PAGE_SIZE: int = 4096

#: 8-byte ASCII magic written into page 0.  Spells "TINY DB 0.1" so
#: humans can ``file(1)`` a tinydb file.
MAGIC: bytes = b"T1NYDB01"

#: Total bytes occupied by the on-disk header (always exactly one page).
HEADER_SIZE: int = PAGE_SIZE

# --- internal layout -----------------------------------------------------

_HEADER_VERSION: int = 1

#: Reserved pages at the start of the file (header + catalog reservation).
_RESERVED_PAGES: int = 4

#: Sentinel used in the free-list next-pointer slots to denote "no next".
_NO_FREE: int = 0xFFFFFFFF

# Header field offsets.
_HDR_MAGIC_OFF: int = 0
_HDR_VERSION_OFF: int = 8
_HDR_PAGE_SIZE_OFF: int = 10
_HDR_NUM_PAGES_OFF: int = 12
_HDR_FREE_HEAD_OFF: int = 16

# Layout of the header in bytes (struct format + size for re-use).
_HEADER_NUM_PAGES_STRUCT = struct.Struct("<I")
_HEADER_FREE_HEAD_STRUCT = struct.Struct("<I")
_HEADER_VERSION_STRUCT = struct.Struct("<H")
_HEADER_PAGE_SIZE_STRUCT = struct.Struct("<H")
_FREE_NEXT_STRUCT = struct.Struct("<I")

PathLike = Union[str, os.PathLike]


class Pager:
    """Fixed-size page I/O over a single ``.db`` file.

    Use :meth:`open` to construct (it is an alias for ``__init__``).
    The pager is also a context manager; ``close`` is called on
    ``__exit__``.

    Thread-safety: not thread-safe.  tinydb v0.1 is single-process
    single-writer per its scope fence.
    """

    def __init__(self, path: PathLike, page_size: int = PAGE_SIZE) -> None:
        if page_size != PAGE_SIZE:
            raise ValueError(
                f"tinydb v0.1 only supports page_size={PAGE_SIZE}, got {page_size}"
            )
        self._path: Path = Path(path)
        self._page_size: int = page_size
        self._num_pages: int = 0
        self._free_head: int = _NO_FREE
        self._fp: IO[bytes] | None = None
        self._closed: bool = False
        try:
            self._open_file()
        except Exception:
            # Don't leak a half-open file handle if initialisation fails.
            if self._fp is not None:
                try:
                    self._fp.close()
                except Exception:
                    pass
                self._fp = None
            raise

    @classmethod
    def open(cls, path: PathLike, page_size: int = PAGE_SIZE) -> "Pager":
        """Factory matching the rest of tinydb's ``open(...)`` API."""
        return cls(path, page_size=page_size)

    # -- lifecycle --------------------------------------------------------

    def _open_file(self) -> None:
        if self._path.exists():
            size = self._path.stat().st_size
            if size > 0 and size % self._page_size != 0:
                raise ValueError(
                    f"file size {size} is not a multiple of page_size "
                    f"{self._page_size}"
                )
            self._fp = open(self._path, "r+b")
            if size == 0:
                # Empty file on disk — treat as a fresh database.
                self._init_new()
            else:
                self._read_header()
        else:
            self._init_new()

    def _init_new(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # If we got here via the "file does not exist" branch, _fp is
        # still None — open it now in write mode.
        if self._fp is None:
            self._fp = open(self._path, "w+b")
        else:
            self._fp.seek(0)
            self._fp.truncate()
        self._num_pages = _RESERVED_PAGES
        self._free_head = _NO_FREE
        # Write the header (page 0).
        self._write_header()
        # Zero-fill the reserved catalog pages so they read as zeros.
        self._fp.seek(0, os.SEEK_END)
        end = self._fp.tell()
        target = self._num_pages * self._page_size
        if end < target:
            self._fp.write(b"\x00" * (target - end))
        self._fp.flush()
        os.fsync(self._fp.fileno())

    def _read_header(self) -> None:
        assert self._fp is not None
        self._fp.seek(0)
        header = self._fp.read(self._page_size)
        if header[0:8] != MAGIC:
            raise ValueError(
                f"not a tinydb file: magic mismatch (got {header[0:8]!r})"
            )
        (version,) = _HEADER_VERSION_STRUCT.unpack_from(header, _HDR_VERSION_OFF)
        if version != _HEADER_VERSION:
            raise ValueError(f"unsupported header version: {version}")
        (page_size,) = _HEADER_PAGE_SIZE_STRUCT.unpack_from(header, _HDR_PAGE_SIZE_OFF)
        if page_size != self._page_size:
            raise ValueError(
                f"file page_size {page_size} != runtime page_size {self._page_size}"
            )
        (self._num_pages,) = _HEADER_NUM_PAGES_STRUCT.unpack_from(
            header, _HDR_NUM_PAGES_OFF
        )
        (self._free_head,) = _HEADER_FREE_HEAD_STRUCT.unpack_from(
            header, _HDR_FREE_HEAD_OFF
        )

    def _write_header(self) -> None:
        assert self._fp is not None
        # Read the current page 0 so we preserve any caller-written bytes
        # in the reserved region (offsets >= 20).  The header is the only
        # contract we own; everything else on page 0 is the caller's.
        self._fp.seek(0)
        current = self._fp.read(self._page_size)
        if len(current) != self._page_size:
            current = b"\x00" * self._page_size
        buf = bytearray(current)
        buf[_HDR_MAGIC_OFF : _HDR_MAGIC_OFF + 8] = MAGIC
        _HEADER_VERSION_STRUCT.pack_into(buf, _HDR_VERSION_OFF, _HEADER_VERSION)
        _HEADER_PAGE_SIZE_STRUCT.pack_into(buf, _HDR_PAGE_SIZE_OFF, self._page_size)
        _HEADER_NUM_PAGES_STRUCT.pack_into(buf, _HDR_NUM_PAGES_OFF, self._num_pages)
        _HEADER_FREE_HEAD_STRUCT.pack_into(buf, _HDR_FREE_HEAD_OFF, self._free_head)
        self._fp.seek(0)
        self._fp.write(bytes(buf))
        self._fp.flush()

    def close(self) -> None:
        """Flush the header and fsync the file.  Idempotent."""
        if self._closed:
            return
        if self._fp is not None:
            try:
                self._write_header()
            except Exception:
                # Best-effort: still try to flush and close.
                pass
            try:
                self._fp.flush()
                os.fsync(self._fp.fileno())
            except Exception:
                pass
            try:
                self._fp.close()
            except Exception:
                pass
        self._fp = None
        self._closed = True

    # -- context manager --------------------------------------------------

    def __enter__(self) -> "Pager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # -- public read-only properties --------------------------------------

    @property
    def num_pages(self) -> int:
        """Total number of pages currently allocated in the file."""
        self._check_open()
        return self._num_pages

    @property
    def page_size(self) -> int:
        return self._page_size

    @property
    def path(self) -> Path:
        return self._path

    # -- page primitives (REQ-STO-4) --------------------------------------

    def read_page(self, pid: int) -> bytes:
        """Return the full ``page_size``-byte content of page ``pid``.

        Raises :class:`IndexError` if ``pid`` is negative or beyond the
        currently allocated page count.
        """
        self._check_open()
        if pid < 0:
            raise IndexError(f"page_id {pid} < 0")
        if pid >= self._num_pages:
            raise IndexError(
                f"page_id {pid} beyond allocated {self._num_pages}"
            )
        assert self._fp is not None
        self._fp.seek(pid * self._page_size)
        data = self._fp.read(self._page_size)
        if len(data) != self._page_size:
            raise OSError(
                f"short read on page {pid}: expected {self._page_size} bytes, "
                f"got {len(data)}"
            )
        return data

    def write_page(self, pid: int, data: bytes) -> None:
        """Write ``data`` (must be exactly ``page_size`` bytes) to page ``pid``.

        Writing past the current end of the file extends it with
        zero-filled pages.  Writing to page 0 protects the on-disk
        header fields — only the reserved region (offset >= 20) is
        caller-controlled.
        """
        self._check_open()
        if len(data) != self._page_size:
            raise ValueError(
                f"page payload must be exactly {self._page_size} bytes, "
                f"got {len(data)}"
            )
        if pid < 0:
            raise IndexError(f"page_id {pid} < 0")
        assert self._fp is not None
        if pid >= self._num_pages:
            self._extend_to(pid + 1)
        if pid == 0:
            data = self._protect_header(data)
        self._fp.seek(pid * self._page_size)
        self._fp.write(data)
        self._fp.flush()

    def allocate_page(self) -> int:
        """Return a fresh, zero-filled ``page_id``.

        Prefers the free list; falls back to extending the file.
        """
        self._check_open()
        assert self._fp is not None
        if self._free_head != _NO_FREE:
            pid = self._free_head
            # Pop the head: read the next pointer from the page itself.
            self._fp.seek(pid * self._page_size)
            (next_free,) = _FREE_NEXT_STRUCT.unpack(self._fp.read(4))
            self._free_head = next_free
            # The re-allocated page is no longer free — zero it so callers
            # don't observe the stale next-pointer.
            self._fp.seek(pid * self._page_size)
            self._fp.write(b"\x00" * self._page_size)
            self._fp.flush()
            self._write_header()
            return pid
        # No free page: extend the file by one.
        pid = self._num_pages
        self._extend_to(pid + 1)
        return pid

    def free_page(self, pid: int) -> None:
        """Return ``pid`` to the free list.

        Reserved pages (0..3) cannot be freed.  The file length is not
        reduced — tinydb reuses pages via the free list rather than
        truncating.
        """
        self._check_open()
        if pid < 0:
            raise ValueError(f"page_id {pid} < 0")
        if pid < _RESERVED_PAGES:
            raise ValueError(
                f"page_id {pid} is reserved (0..{_RESERVED_PAGES - 1})"
            )
        if pid >= self._num_pages:
            raise ValueError(f"page_id {pid} beyond allocated {self._num_pages}")
        assert self._fp is not None
        # Link this page in front of the free list.
        self._fp.seek(pid * self._page_size)
        self._fp.write(_FREE_NEXT_STRUCT.pack(self._free_head))
        self._fp.flush()
        self._free_head = pid
        self._write_header()

    # -- internals --------------------------------------------------------

    def _extend_to(self, new_num_pages: int) -> None:
        """Grow the file so it holds at least ``new_num_pages`` pages."""
        if new_num_pages <= self._num_pages:
            return
        assert self._fp is not None
        gap_pages = new_num_pages - self._num_pages
        self._fp.seek(self._num_pages * self._page_size)
        self._fp.write(b"\x00" * (gap_pages * self._page_size))
        self._fp.flush()
        self._num_pages = new_num_pages
        self._write_header()

    def _protect_header(self, data: bytes) -> bytes:
        """Mask out the header fields in ``data`` (page 0 payload)."""
        buf = bytearray(data)
        buf[_HDR_MAGIC_OFF : _HDR_MAGIC_OFF + 8] = MAGIC
        _HEADER_VERSION_STRUCT.pack_into(buf, _HDR_VERSION_OFF, _HEADER_VERSION)
        _HEADER_PAGE_SIZE_STRUCT.pack_into(buf, _HDR_PAGE_SIZE_OFF, self._page_size)
        _HEADER_NUM_PAGES_STRUCT.pack_into(buf, _HDR_NUM_PAGES_OFF, self._num_pages)
        _HEADER_FREE_HEAD_STRUCT.pack_into(buf, _HDR_FREE_HEAD_OFF, self._free_head)
        return bytes(buf)

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("Pager is closed")


__all__ = ["Pager", "MAGIC", "PAGE_SIZE", "HEADER_SIZE"]