"""Tests for tinydb.tx.WAL — append-only CRC32-protected log.

Frame layout (13-byte header + payload + 4-byte CRC32 LE):
    [lsn:u64 BE] [type:u8] [payload_len:u32 BE] [payload] [crc32:u32 LE]

LSNs start at 1 and are monotonic. Recovery from an existing file is
performed by re-reading frames; a partial tail frame is silently
ignored (truncation is checkpoint's job, not WAL's).
"""
from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from tinydb.errors import TinydbError
from tinydb.tx import WAL, WALRecord


def _path(tmp_path: Path, name: str = "test.wal") -> Path:
    return tmp_path / name


# ---------------------------------------------------------------------------
# 1. Empty WAL: next_lsn starts at 1.
# ---------------------------------------------------------------------------
def test_empty_wal_next_lsn_is_one(tmp_path):
    wal = WAL(_path(tmp_path), mode="w+b")
    assert wal.next_lsn == 1
    wal.close()


# ---------------------------------------------------------------------------
# 2. Append one record -> LSN == 1, then next_lsn advances to 2.
# ---------------------------------------------------------------------------
def test_append_one_record_returns_lsn_one(tmp_path):
    wal = WAL(_path(tmp_path), mode="w+b")
    lsn = wal.append(type=4, payload=b"hello")
    assert lsn == 1
    assert wal.next_lsn == 2
    wal.close()


# ---------------------------------------------------------------------------
# 3. Multiple appends -> LSNs are 1,2,3 and payload bytes round-trip.
# ---------------------------------------------------------------------------
def test_three_records_lsns_and_payload_roundtrip(tmp_path):
    wal = WAL(_path(tmp_path), mode="w+b")
    payloads = [b"alpha", b"bravo!", b"charlie=="]
    for p in payloads:
        wal.append(type=4, payload=p)
    assert wal.next_lsn == 4

    out = list(wal.iter_from(0))
    assert [r.lsn for r in out] == [1, 2, 3]
    for r, want in zip(out, payloads):
        assert r.payload == want
        assert r.type == 4
    wal.close()


# ---------------------------------------------------------------------------
# 4. iter_from(0) yields all records on a populated WAL.
# ---------------------------------------------------------------------------
def test_iter_from_zero_yields_all(tmp_path):
    wal = WAL(_path(tmp_path), mode="w+b")
    for p in (b"x", b"y", b"z"):
        wal.append(type=1, payload=p)
    out = list(wal.iter_from(0))
    assert len(out) == 3
    assert [r.payload for r in out] == [b"x", b"y", b"z"]
    wal.close()


# ---------------------------------------------------------------------------
# 5. iter_from(2) yields only records with lsn >= 2.
# ---------------------------------------------------------------------------
def test_iter_from_filters_by_lsn(tmp_path):
    wal = WAL(_path(tmp_path), mode="w+b")
    for p in (b"a", b"b", b"c"):
        wal.append(type=1, payload=p)
    out = list(wal.iter_from(2))
    assert [r.lsn for r in out] == [2, 3]
    assert [r.payload for r in out] == [b"b", b"c"]
    wal.close()


# ---------------------------------------------------------------------------
# 6. CORRUPTION: flipping a payload bit invalidates CRC -> WALCorruptionError.
# ---------------------------------------------------------------------------
def test_corruption_detection_raises(tmp_path):
    from tinydb.tx.wal import WALCorruptionError  # module-level re-export

    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    wal.append(type=4, payload=b"good-1")
    wal.append(type=4, payload=b"good-2-and-tampered")
    wal.close()

    # Flip one byte inside the SECOND frame's payload region to
    # invalidate its CRC. Recovery walks the first frame successfully,
    # so iter_from is what surfaces the CRC mismatch on the second one.
    raw = bytearray(p.read_bytes())
    # First frame: 13 hdr + 6 payload + 4 crc = 23 bytes.  Second frame's
    # payload starts at offset 23 + 13 = 36.  Tamper inside byte 38.
    second_payload_start = 23 + 13
    raw[second_payload_start + 2] ^= 0x80
    p.write_bytes(bytes(raw))

    wal = WAL(p, mode="r+b")
    try:
        with pytest.raises(WALCorruptionError):
            list(wal.iter_from(0))
    finally:
        wal.close()


# ---------------------------------------------------------------------------
# 6b. The same error lives in tinydb.errors and is a TinydbError subclass.
# ---------------------------------------------------------------------------
def test_wal_corruption_is_tinydb_error():
    from tinydb.errors import WALCorruptionError

    assert issubclass(WALCorruptionError, TinydbError)
    err = WALCorruptionError("boom")
    assert isinstance(err, TinydbError)


# ---------------------------------------------------------------------------
# 7. Truncated tail frame: iter_from stops cleanly (no exception).
# ---------------------------------------------------------------------------
def test_truncated_tail_frame_stops_clean(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    wal.append(type=4, payload=b"frame1")
    wal.append(type=4, payload=b"frame2")
    wal.append(type=4, payload=b"frame3")
    wal.close()

    # Chop the file mid-way through the last frame.
    raw = p.read_bytes()
    p.write_bytes(raw[: len(raw) - 8])

    wal = WAL(p, mode="r+b")
    try:
        out = list(wal.iter_from(0))
        # Two full frames are recoverable; the third is dropped as a torn tail.
        assert [r.payload for r in out] == [b"frame1", b"frame2"]
    finally:
        wal.close()


# ---------------------------------------------------------------------------
# 8. truncate_to(lsn) drops records with LSN >= lsn and resets next_lsn.
# ---------------------------------------------------------------------------
def test_truncate_to_drops_records_at_or_above(tmp_path):
    wal = WAL(_path(tmp_path), mode="w+b")
    for p in (b"keep1", b"drop1", b"drop2"):
        wal.append(type=4, payload=p)
    wal.truncate_to(2)
    assert wal.next_lsn == 2
    out = list(wal.iter_from(0))
    assert [r.lsn for r in out] == [1]
    assert out[0].payload == b"keep1"
    wal.close()


# ---------------------------------------------------------------------------
# 9. Close + reopen preserves next_lsn (recovery).
# ---------------------------------------------------------------------------
def test_reopen_recovers_next_lsn(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    wal.append(type=4, payload=b"first")
    wal.append(type=4, payload=b"second")
    assert wal.next_lsn == 3
    wal.close()

    wal = WAL(p, mode="r+b")
    try:
        assert wal.next_lsn == 3
        out = list(wal.iter_from(0))
        assert [r.payload for r in out] == [b"first", b"second"]
    finally:
        wal.close()


# ---------------------------------------------------------------------------
# 10. fsync() is callable and does not raise.
# ---------------------------------------------------------------------------
def test_fsync_callable_no_raise(tmp_path):
    wal = WAL(_path(tmp_path), mode="w+b")
    wal.append(type=4, payload=b"durability")
    wal.fsync()  # must not raise
    wal.close()


# ---------------------------------------------------------------------------
# 11. Empty payload -> 17-byte frame (13 header + 0 payload + 4 CRC).
# ---------------------------------------------------------------------------
def test_empty_payload_frame_size(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    lsn = wal.append(type=4, payload=b"")
    assert lsn == 1
    wal.close()
    assert p.stat().st_size == 17

    wal = WAL(p, mode="r+b")
    try:
        out = list(wal.iter_from(0))
        assert len(out) == 1
        assert out[0].payload == b""
    finally:
        wal.close()


# ---------------------------------------------------------------------------
# 12. Unknown record type (200) is preserved on read; client decides.
# ---------------------------------------------------------------------------
def test_unknown_record_type_preserved(tmp_path):
    wal = WAL(_path(tmp_path), mode="w+b")
    wal.append(type=200, payload=b"future-data")
    out = list(wal.iter_from(0))
    assert out[0].type == 200
    assert out[0].payload == b"future-data"
    wal.close()


# ---------------------------------------------------------------------------
# 13. Public WALRecord is a frozen dataclass with the expected fields.
# ---------------------------------------------------------------------------
def test_walrecord_is_immutable():
    r = WALRecord(lsn=1, type=4, payload=b"x")
    assert r.lsn == 1
    assert r.type == 4
    assert r.payload == b"x"
    with pytest.raises(Exception):
        # frozen=True forbids attribute assignment
        r.lsn = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 14. CRC covers [lsn | type | payload_len | payload] exactly, in that order.
# ---------------------------------------------------------------------------
def test_crc_covers_header_and_payload(tmp_path):
    p = _path(tmp_path)
    wal = WAL(p, mode="w+b")
    wal.append(type=4, payload=b"\x01\x02\x03")
    wal.close()

    raw = bytearray(p.read_bytes())
    # Strip the trailing 4-byte CRC and recompute over [header | payload].
    # Layout: 8 lsn + 1 type + 4 payload_len = 13-byte header.
    crc_stored = int.from_bytes(bytes(raw[-4:]), "little")
    crc_check = zlib.crc32(bytes(raw[:-4]))
    assert crc_stored == crc_check
