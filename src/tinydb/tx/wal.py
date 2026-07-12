"""Write-Ahead Log — append-only log of typed records.

A :class:`WAL` is a thin wrapper over a binary file handle.  Records are
appended using :meth:`WAL.append`; the file is always grown, never
shrunk (truncation is the checkpoint layer's job, T-6.7).

Frame layout (13-byte header + payload + 4-byte CRC32 LE):

    [lsn:u64 BE | type:u8 | payload_len:u32 BE | payload | crc32:u32 LE]

The CRC covers exactly ``[lsn | type | payload_len | payload]`` and is
stored little-endian to match :func:`zlib.crc32` conventions.  LSNs and
``payload_len`` are big-endian, so the frame is *asymmetric*: any tool
that parses it must know to swap byte order for the CRC field but not
the LSN / length fields.  This deviation is documented in the report.

CRC-32 (ISO 3309 / ITU-T V.42) is used via :func:`zlib.crc32` rather
than CRC-32C — CRC-32C would require a C extension we cannot take on as
a dependency.  The single-bit detection property is preserved.
"""
from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Union

from tinydb.errors import WALCorruptionError

__all__ = [
    "WAL",
    "WALRecord",
    "WALCorruptionError",
    "RT_BEGIN",
    "RT_COMMIT",
    "RT_ROLLBACK",
    "RT_PAGE",
    "RT_CKPT",
]

_HEADER_FMT = ">QBI"  # LSN (u64 BE), type (u8), payload_len (u32 BE)
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 13
_CRC_FMT = "<I"  # CRC32 LE
_CRC_SIZE = struct.calcsize(_CRC_FMT)  # 4

# Record type codes (extensible enum).
RT_BEGIN = 1
RT_COMMIT = 2
RT_ROLLBACK = 3
RT_PAGE = 4
RT_CKPT = 5


@dataclass(frozen=True, slots=True)
class WALRecord:
    """One decoded WAL frame.

    Attributes
    ----------
    lsn:
        Monotonically increasing; the first record written by a fresh
        WAL has LSN == 1.
    type:
        One of the ``RT_*`` codes, or any application-defined value;
        the WAL passes unknown types through unchanged.
    payload:
        Opaque bytes; interpretation is the caller's responsibility.
    """

    lsn: int
    type: int
    payload: bytes


def _crc32(blob: bytes) -> int:
    """Unsigned CRC-32 of ``blob`` (matches the LE-encoded on-disk form)."""
    return zlib.crc32(blob) & 0xFFFFFFFF


class WAL:
    """Append-only log with CRC32-protected frames.

    Open in ``"r+b"`` (default) to recover :attr:`next_lsn` from disk;
    pass ``"w+b"`` to truncate.  Not safe for concurrent writers — pair
    with :class:`tinydb.tx.WriteLock`.
    """

    __slots__ = ("_path", "_fp", "_next_lsn", "_closed")

    def __init__(self, path: Union[str, Path], *, mode: str = "r+b") -> None:
        self._path = Path(path)
        self._fp = self._path.open(mode)
        self._closed = False
        if mode == "r+b":
            self._next_lsn = self._recover_lsn()
        else:
            self._fp.seek(0)
            self._fp.truncate()
            self._next_lsn = 1

    def close(self) -> None:
        if not self._closed:
            try:
                self._fp.flush()
            finally:
                self._fp.close()
                self._closed = True

    def __enter__(self) -> "WAL":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def fsync(self) -> None:
        """Force pending bytes to stable storage."""
        self._fp.flush()
        os.fsync(self._fp.fileno())

    @property
    def next_lsn(self) -> int:
        """LSN that the next :meth:`append` call will assign."""
        return self._next_lsn

    @property
    def size(self) -> int:
        """Current file length in bytes."""
        self._fp.seek(0, 2)
        return self._fp.tell()

    def append(self, type: int, payload: bytes) -> int:
        """Append one frame; return its assigned LSN."""
        lsn = self._next_lsn
        body = struct.pack(_HEADER_FMT, lsn, type, len(payload)) + payload
        crc = _crc32(body)
        self._fp.seek(0, 2)
        self._fp.write(body + struct.pack(_CRC_FMT, crc))
        self._fp.flush()
        self._next_lsn = lsn + 1
        return lsn

    def truncate_to(self, lsn: int) -> None:
        """Remove all frames with LSN >= ``lsn`` (used by T-6.7)."""
        if lsn < 1 or lsn > self._next_lsn:
            raise ValueError(
                f"truncate_to lsn={lsn} out of range [1, {self._next_lsn}]"
            )
        self._fp.seek(0)
        offset = 0
        while True:
            header = self._fp.read(_HEADER_SIZE)
            if len(header) < _HEADER_SIZE:
                break
            (frame_lsn, _type, payload_len) = struct.unpack(_HEADER_FMT, header)
            full_len = _HEADER_SIZE + _CRC_SIZE + payload_len
            if frame_lsn >= lsn:
                self._fp.seek(offset)
                self._fp.truncate()
                self._next_lsn = lsn
                return
            self._fp.seek(payload_len + _CRC_SIZE, 1)
            offset += full_len

    def iter_from(self, lsn: int) -> Iterator[WALRecord]:
        """Yield records with LSN >= ``lsn``.

        Stops cleanly at a torn tail; raises
        :class:`WALCorruptionError` on a completed frame whose CRC32
        does not match its contents.
        """
        if lsn < 1:
            lsn = 1
        self._fp.seek(0)
        while True:
            offset = self._fp.tell()
            header = self._fp.read(_HEADER_SIZE)
            if len(header) == 0:
                return
            if len(header) < _HEADER_SIZE:
                return  # torn tail
            (frame_lsn, frame_type, payload_len) = struct.unpack(
                _HEADER_FMT, header
            )
            payload = self._fp.read(payload_len)
            crc_bytes = self._fp.read(_CRC_SIZE)
            if len(payload) < payload_len or len(crc_bytes) < _CRC_SIZE:
                return  # torn tail
            expected = _crc32(header + payload)
            stored = struct.unpack(_CRC_FMT, crc_bytes)[0]
            if expected != stored:
                raise WALCorruptionError(
                    f"WAL CRC mismatch at offset {offset}: "
                    f"expected {expected:#010x}, got {stored:#010x} "
                    f"(lsn={frame_lsn}, type={frame_type})"
                )
            if frame_lsn >= lsn:
                yield WALRecord(frame_lsn, frame_type, payload)

    def _recover_lsn(self) -> int:
        """Walk the file finding the next-to-assign LSN.

        A torn tail or any CRC mismatch stops the walk silently: the
        WAL opens with ``next_lsn`` set to the last good frame + 1, and
        :meth:`iter_from` is responsible for raising on a corrupt
        completed frame.
        """
        next_lsn = 1
        self._fp.seek(0)
        while True:
            header = self._fp.read(_HEADER_SIZE)
            if len(header) < _HEADER_SIZE:
                return next_lsn
            (frame_lsn, _frame_type, payload_len) = struct.unpack(
                _HEADER_FMT, header
            )
            tail = self._fp.read(payload_len + _CRC_SIZE)
            if len(tail) < payload_len + _CRC_SIZE:
                return next_lsn
            stored = struct.unpack(_CRC_FMT, tail[payload_len:])[0]
            expected = _crc32(header + tail[:payload_len])
            if frame_lsn != next_lsn or expected != stored:
                return next_lsn  # corrupt or torn — soft stop
            next_lsn += 1
