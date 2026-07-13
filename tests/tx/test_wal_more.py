"""Extra WAL tests — corruption / truncation / reopen paths.

Complements `tests/tx/test_wal.py` (which covers the happy path: append,
iter_from, monotonic LSN).  This file targets the error-handling and
lifecycle code in :mod:`tinydb.tx.wal` that the happy-path tests don't
exercise:

* CRC-mismatch detection → :class:`WALCorruptionError`.
* Torn tail (truncated mid-frame) → iter_from stops cleanly.
* ``truncate_to(N)`` removes records ≥ N and updates ``next_lsn``.
* New session over an existing WAL recovers LSN by walking frames.
* ``w+b`` open + close + reopen lifecycle.
* Frame header with unknown type byte → record still decodes.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from tinydb.errors import WALCorruptionError
from tinydb.tx import WAL, WALRecord


_HEADER_FMT = ">QBI"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_CRC_FMT = "<I"
_CRC_SIZE = struct.calcsize(_CRC_FMT)


def _path(tmp_path: Path, name: str = "wal_more.wal") -> Path:
    return tmp_path / name


# ---------------------------------------------------------------------------
# 1. New session over an existing WAL recovers LSN by walking frames.
# ---------------------------------------------------------------------------
def test_reopen_recovered_lsn_matches_appended_count(tmp_path):
    """Closing and reopening preserves ``next_lsn``."""
    p = _path(tmp_path)
    w1 = WAL(p, mode="w+b")
    for i in range(5):
        w1.append(type=4, payload=f"frame-{i}".encode())
    assert w1.next_lsn == 6
    w1.close()

    w2 = WAL(p, mode="r+b")  # default mode: recover_lsn
    assert w2.next_lsn == 6
    out = list(w2.iter_from(0))
    assert [r.lsn for r in out] == [1, 2, 3, 4, 5]
    w2.close()


# ---------------------------------------------------------------------------
# 2. CRC corruption → WALCorruptionError on iter_from.
# ---------------------------------------------------------------------------
def test_crc_mismatch_raises_corruption_error(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    wal.append(type=4, payload=b"good")
    wal.close()

    # Flip a byte inside the first frame's CRC field (last 4 bytes).
    raw = p.read_bytes()
    # Frame layout: 13-byte header + 4-byte payload + 4-byte CRC = 21 bytes.
    assert len(raw) == _HEADER_SIZE + 4 + _CRC_SIZE
    # Flip the last byte of the file (inside CRC).
    tampered = raw[:-1] + bytes([raw[-1] ^ 0xFF])
    p.write_bytes(tampered)

    wal = WAL(p, mode="r+b")  # recover_lsn is silent on torn tail
    with pytest.raises(WALCorruptionError):
        list(wal.iter_from(0))


# ---------------------------------------------------------------------------
# 3. CRC truncation (file ends mid-CRC) → iter_from stops cleanly.
# ---------------------------------------------------------------------------
def test_truncated_crc_stops_cleanly(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    wal.append(type=4, payload=b"complete")
    wal.close()

    raw = p.read_bytes()
    # Chop off the last 2 CRC bytes.
    p.write_bytes(raw[:-2])

    wal = WAL(p, mode="r+b")
    # The torn-tail branch returns without yielding.
    out = list(wal.iter_from(0))
    assert out == []
    # recover_lsn returns 1 because the torn frame was discarded.
    assert wal.next_lsn == 1
    wal.close()


# ---------------------------------------------------------------------------
# 4. Truncated last-frame (write 5 then halve) → iter_from yields intact frames.
# ---------------------------------------------------------------------------
def test_truncated_payload_stops_cleanly(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    for i in range(5):
        wal.append(type=4, payload=f"frame-{i}".encode())
    wal.close()

    raw = p.read_bytes()
    # Keep the first three frames (3 * (13 + 9 + 4) = 78 bytes) plus
    # the header of the 4th frame (13 bytes), then truncate.
    keep = 3 * (_HEADER_SIZE + 9 + _CRC_SIZE) + _HEADER_SIZE
    p.write_bytes(raw[:keep])

    wal = WAL(p, mode="r+b")
    out = list(wal.iter_from(0))
    # The first 3 frames are intact; the 4th's payload is torn so
    # the iterator stops.
    assert [r.payload for r in out] == [b"frame-0", b"frame-1", b"frame-2"]
    assert wal.next_lsn == 4  # one past the last good frame
    wal.close()


# ---------------------------------------------------------------------------
# 5. truncate_to(N) removes records ≥ N.
# ---------------------------------------------------------------------------
def test_truncate_to_removes_records_at_and_after_lsn(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    for i in range(5):
        wal.append(type=4, payload=f"f{i}".encode())
    wal.truncate_to(3)  # remove LSNs 3, 4, 5
    assert wal.next_lsn == 3
    out = list(wal.iter_from(0))
    assert [r.lsn for r in out] == [1, 2]
    wal.close()


def test_truncate_to_out_of_range_raises(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    wal.append(type=4, payload=b"x")
    with pytest.raises(ValueError):
        wal.truncate_to(0)
    with pytest.raises(ValueError):
        wal.truncate_to(99)
    wal.close()


# ---------------------------------------------------------------------------
# 6. After truncate, reopen and continue appending — LSN is contiguous.
# ---------------------------------------------------------------------------
def test_truncate_then_append_reuses_lsns(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    for i in range(4):
        wal.append(type=4, payload=f"f{i}".encode())
    wal.truncate_to(3)
    wal.close()

    wal = WAL(p, mode="r+b")
    assert wal.next_lsn == 3
    lsn = wal.append(type=4, payload=b"after")
    assert lsn == 3
    assert wal.next_lsn == 4
    out = list(wal.iter_from(0))
    assert [r.payload for r in out] == [b"f0", b"f1", b"after"]
    wal.close()


# ---------------------------------------------------------------------------
# 7. Mode 'w+b' open + close + reopen — fresh LSN counter.
# ---------------------------------------------------------------------------
def test_wb_mode_truncates_existing_file(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    wal.append(type=4, payload=b"a")
    wal.append(type=4, payload=b"b")
    wal.close()

    wal = WAL(p, mode="w+b")  # truncates
    assert wal.next_lsn == 1
    assert list(wal.iter_from(0)) == []
    wal.close()


# ---------------------------------------------------------------------------
# 8. Frame header with unknown type byte → record is yielded unchanged.
# ---------------------------------------------------------------------------
def test_unknown_type_byte_passes_through(tmp_path):
    """The WAL is typed but type-agnostic — unknown codes survive."""
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    # Type byte 99 is not in the RT_* enum but the WAL doesn't care.
    wal.append(type=99, payload=b"opaque")
    out = list(wal.iter_from(0))
    assert len(out) == 1
    assert out[0].type == 99
    assert out[0].payload == b"opaque"
    wal.close()


# ---------------------------------------------------------------------------
# 9. iter_from past the last LSN → empty.
# ---------------------------------------------------------------------------
def test_iter_from_past_tail_is_empty(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    wal.append(type=4, payload=b"a")
    wal.append(type=4, payload=b"b")
    assert list(wal.iter_from(100)) == []
    wal.close()


# ---------------------------------------------------------------------------
# 10. fsync does not crash on a writable WAL.
# ---------------------------------------------------------------------------
def test_fsync_is_no_error(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    wal.append(type=4, payload=b"a")
    wal.fsync()  # just exercises the path; no assertion other than no-exception
    wal.close()


# ---------------------------------------------------------------------------
# 11. After truncation, recover_lsn walks the surviving frames.
# ---------------------------------------------------------------------------
def test_recover_lsn_after_truncate(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    for i in range(6):
        wal.append(type=4, payload=f"f{i}".encode())
    wal.truncate_to(4)
    wal.close()

    wal = WAL(p, mode="r+b")
    assert wal.next_lsn == 4
    out = list(wal.iter_from(0))
    assert [r.payload for r in out] == [b"f0", b"f1", b"f2"]
    wal.close()