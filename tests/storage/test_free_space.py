"""Tests for the FreeSpaceMap — per-page free-byte tracker.

T-2.3 RED phase (companion to test_heap).  Covers the bookkeeping the
Heap consults before inserting a new record.
"""

from __future__ import annotations

from tinydb.storage.free_space import FreeSpaceMap


def test_empty_map_has_no_pages():
    fm = FreeSpaceMap()
    assert len(fm) == 0
    assert fm.find_with_space(1) is None


def test_update_then_find_returns_that_page():
    fm = FreeSpaceMap()
    fm.update(page_id=4, free_bytes=200)
    fm.update(page_id=5, free_bytes=100)
    # find the page with at least 150 bytes
    assert fm.find_with_space(150) == 4
    # find the page with at least 200 bytes
    assert fm.find_with_space(200) == 4
    # exact-fit
    assert fm.find_with_space(100) in (4, 5)


def test_remove_takes_a_page_out_of_the_map():
    fm = FreeSpaceMap()
    fm.update(page_id=4, free_bytes=200)
    assert fm.find_with_space(150) == 4
    fm.remove(page_id=4)
    assert fm.find_with_space(1) is None
    assert len(fm) == 0


def test_find_with_space_returns_none_when_nothing_fits():
    fm = FreeSpaceMap()
    fm.update(page_id=4, free_bytes=50)
    assert fm.find_with_space(51) is None
