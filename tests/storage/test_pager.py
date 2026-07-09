"""Tests for the Pager — fixed-size page I/O over a single .db file.

T-2.1 RED phase.  Covers REQ-STO-1 (single file persistence),
REQ-STO-2 (page-based storage, default 4096 bytes), and REQ-STO-4
(page primitives: read / write / allocate / free).
"""

from __future__ import annotations

import struct

import pytest

from tinydb.storage.pager import HEADER_SIZE, MAGIC, PAGE_SIZE, Pager


# --- file creation & header ----------------------------------------------


def test_open_creates_missing_file(tmp_db_path):
    # tmp_db_path points at a non-existent file (see tests/conftest.py).
    assert not tmp_db_path.exists()
    p = Pager.open(tmp_db_path)
    try:
        # Opening the database creates the file on disk.
        assert tmp_db_path.exists()
        # File starts with 4 pages: 1 header + 3 reserved for catalog.
        assert tmp_db_path.stat().st_size == 4 * PAGE_SIZE
    finally:
        p.close()


def test_header_carries_magic_version_page_size(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        magic = p.read_page(0)[0:8]
        version, page_size = struct.unpack_from("<HH", p.read_page(0), 8)
        assert magic == MAGIC
        assert version == 1
        assert page_size == PAGE_SIZE
    finally:
        p.close()


def test_open_existing_file_preserves_header(tmp_db_path):
    # First Pager writes a recognisable payload; reopen and read it back.
    p1 = Pager.open(tmp_db_path)
    try:
        # Write a sentinel byte sequence at offset 100 of page 0.
        page = bytearray(p1.read_page(0))
        page[100:108] = b"SNUFFLE!"
        p1.write_page(0, bytes(page))
    finally:
        p1.close()

    p2 = Pager.open(tmp_db_path)
    try:
        assert p2.read_page(0)[100:108] == b"SNUFFLE!"
    finally:
        p2.close()


def test_custom_page_size_rejected():
    # REQ-STO-2 mandates 4096 bytes.  Other values are not supported in
    # v0.1 — we keep the API narrow on purpose.
    with pytest.raises(ValueError):
        Pager.open("/tmp/anything.db", page_size=8192)


# --- page I/O ------------------------------------------------------------


def test_read_page_returns_full_page_size(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        assert len(p.read_page(0)) == PAGE_SIZE
        # Unallocated pages beyond the header read as zero bytes (sparse
        # semantics) so callers can probe for free space cheaply.
        assert p.read_page(1) == b"\x00" * PAGE_SIZE
    finally:
        p.close()


def test_write_then_read_page_roundtrips(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        payload = bytes((i * 7 + 13) & 0xFF for i in range(PAGE_SIZE))
        p.write_page(2, payload)
        assert p.read_page(2) == payload
    finally:
        p.close()


def test_write_extends_file_and_updates_header(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        # Initial allocation: header + 3 reserved catalog pages.
        assert p.num_pages == 4
        # Writing page 5 grows the file.
        p.write_page(5, b"\xAB" * PAGE_SIZE)
        assert p.num_pages == 6
        assert tmp_db_path.stat().st_size == PAGE_SIZE * 6
    finally:
        p.close()


def test_read_beyond_allocated_raises(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        with pytest.raises(IndexError):
            p.read_page(99)
    finally:
        p.close()


def test_write_requires_full_page_payload(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        with pytest.raises(ValueError):
            p.write_page(0, b"too short")
    finally:
        p.close()


# --- allocation / free list ----------------------------------------------


def test_allocate_page_returns_new_pid(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        # First allocation skips the reserved header page (pid 0) and
        # also skips the catalog reservation (pages 1..3) used by T-2.4.
        first = p.allocate_page()
        second = p.allocate_page()
        assert first >= 4
        assert second == first + 1
        # Allocation grew the file accordingly.
        assert p.num_pages == second + 1
    finally:
        p.close()


def test_free_then_allocate_reuses_page(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        # Allocate then free — allocate again must reuse the same pid
        # before extending the file.
        pid = p.allocate_page()
        p.free_page(pid)
        reused = p.allocate_page()
        assert reused == pid
        assert p.num_pages == pid + 1  # file did not grow
    finally:
        p.close()


def test_free_unknown_page_raises(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        with pytest.raises(ValueError):
            p.free_page(0)  # header page is not freeable
    finally:
        p.close()


# --- durability ----------------------------------------------------------


def test_close_persists_changes(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        p.write_page(4, b"\x42" * PAGE_SIZE)
    finally:
        p.close()

    # New handle sees the write — proves fsync happens on close.
    p2 = Pager.open(tmp_db_path)
    try:
        assert p2.read_page(4) == b"\x42" * PAGE_SIZE
    finally:
        p2.close()


# --- IMPROVE phase: context-manager protocol -----------------------------


def test_context_manager_closes_on_exit(tmp_db_path):
    with Pager.open(tmp_db_path) as p:
        p.write_page(4, b"\x01" * PAGE_SIZE)
    # Handle must be closed after exiting the with-block.
    assert p._closed is True


def test_context_manager_returns_self(tmp_db_path):
    with Pager.open(tmp_db_path) as p:
        assert isinstance(p, Pager)


def test_operations_after_close_raise(tmp_db_path):
    p = Pager.open(tmp_db_path)
    p.close()
    with pytest.raises(RuntimeError):
        p.read_page(0)


# --- header constants are part of the on-disk contract -------------------


def test_header_constants_are_sane():
    # The header fits in one page so we never span page boundaries when
    # serialising it.
    assert HEADER_SIZE <= PAGE_SIZE
    # Magic is a printable ASCII marker that lets humans ``file(1)`` the
    # database — fix its length so the header layout is stable.
    assert len(MAGIC) == 8


# --- corruption / mismatch handling --------------------------------------


def test_open_existing_file_with_bad_magic_raises(tmp_db_path):
    tmp_db_path.write_bytes(b"NOT A DB FILE".ljust(PAGE_SIZE, b"\x00"))
    with pytest.raises(ValueError, match="magic"):
        Pager.open(tmp_db_path)


def test_open_empty_file_recovers_and_initialises(tmp_db_path):
    # A zero-byte file on disk is treated as a fresh database (we
    # truncate and re-init the header).
    tmp_db_path.write_bytes(b"")
    p = Pager.open(tmp_db_path)
    try:
        assert p.num_pages == 4
        magic = p.read_page(0)[0:8]
        assert magic == MAGIC
    finally:
        p.close()


def test_open_non_page_aligned_file_raises(tmp_db_path):
    tmp_db_path.write_bytes(b"\x00" * (PAGE_SIZE + 1))
    with pytest.raises(ValueError, match="multiple"):
        Pager.open(tmp_db_path)


def test_negative_page_id_raises(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        with pytest.raises(IndexError):
            p.read_page(-1)
        with pytest.raises(IndexError):
            p.write_page(-1, b"\x00" * PAGE_SIZE)
        with pytest.raises(ValueError):
            p.free_page(-1)
    finally:
        p.close()


def test_free_page_beyond_allocated_raises(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        with pytest.raises(ValueError, match="beyond"):
            p.free_page(99)
    finally:
        p.close()


def test_write_page_zero_protects_header_fields(tmp_db_path):
    # Even if a caller passes a fully-zero buffer for page 0, the on-disk
    # header fields (magic/version/page_size/num_pages/free_head) must
    # remain intact — otherwise the file becomes unreadable.
    p = Pager.open(tmp_db_path)
    try:
        p.allocate_page()  # bump num_pages so it changes
        p.write_page(0, b"\x00" * PAGE_SIZE)
    finally:
        p.close()
    p2 = Pager.open(tmp_db_path)
    try:
        magic = p2.read_page(0)[0:8]
        assert magic == MAGIC
        assert p2.num_pages >= 5
    finally:
        p2.close()