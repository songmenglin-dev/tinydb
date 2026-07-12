"""Tests for tinydb.tx.TransactionManager — BEGIN / COMMIT / ROLLBACK.

The TransactionManager sits between :class:`WriteLock` (T-6.1) and the
:class:`WAL` (T-6.2).  These tests use a real WAL on disk and a stub
Pager — T-6.3 writes no PAGE records (those land in T-6.4), so the
manager only needs *something* to store against the pager slot.
"""
from __future__ import annotations

import struct
import threading
import time
from pathlib import Path
from typing import List

import pytest

from tinydb.errors import TinydbError
from tinydb.tx import (
    RT_BEGIN,
    RT_COMMIT,
    RT_ROLLBACK,
    WAL,
    TransactionContext,
    TransactionManager,
)
from tinydb.tx.manager import NestedTransactionError


class _StubPager:
    """Stand-in pager; the manager only stores it (T-6.4 writes pages)."""

    def __init__(self) -> None:
        self.flushed = 0


def _make_manager(tmp_path: Path) -> tuple[TransactionManager, WAL]:
    wal = WAL(tmp_path / "manager.wal", mode="w+b")
    return TransactionManager(_StubPager(), wal), wal


def _decode_tx_id(payload: bytes) -> int:
    return struct.unpack(">Q", payload)[0]


def _wal_records(wal: WAL) -> List:
    return list(wal.iter_from(1))


# 1. Happy path: with mgr.transaction() → BEGIN + COMMIT in WAL.
def test_transaction_happy_path_records_begin_and_commit(tmp_path):
    mgr, wal = _make_manager(tmp_path)
    with mgr.transaction() as tx:
        assert isinstance(tx, TransactionContext)
        assert mgr.active_tx is tx
    records = _wal_records(wal)
    assert [r.type for r in records] == [RT_BEGIN, RT_COMMIT]
    assert records[0].lsn == 1 and records[1].lsn == 2
    assert mgr.active_tx is None
    wal.close()


# 2. Exception inside the with-block → BEGIN + ROLLBACK; exc propagates.
def test_exception_inside_transaction_records_rollback(tmp_path):
    mgr, wal = _make_manager(tmp_path)
    class Boom(RuntimeError):
        pass
    with pytest.raises(Boom):
        with mgr.transaction():
            raise Boom("kaboom")
    records = _wal_records(wal)
    assert [r.type for r in records] == [RT_BEGIN, RT_ROLLBACK]
    assert mgr.active_tx is None
    wal.close()


# 3. Nested with-block raises NestedTransactionError; the error derives
#    from TinydbError so callers can catch a single base type.
def test_nested_transaction_raises(tmp_path):
    mgr, wal = _make_manager(tmp_path)
    assert isinstance(NestedTransactionError(), TinydbError)
    with pytest.raises(NestedTransactionError):
        with mgr.transaction():
            with mgr.transaction():
                pytest.fail("inner transaction must not be entered")
    records = _wal_records(wal)
    assert [r.type for r in records] == [RT_BEGIN, RT_ROLLBACK]
    wal.close()


# 4. After commit, active_tx is None and the lock is released (the
#    same thread can re-enter begin).
def test_commit_releases_lock(tmp_path):
    mgr, wal = _make_manager(tmp_path)
    with mgr.transaction():
        pass
    assert mgr.active_tx is None
    tx = mgr.begin()
    assert tx.tx_id == 2
    mgr.rollback(tx)
    wal.close()


# 5. After rollback, active_tx is None and the lock is released.
def test_rollback_releases_lock(tmp_path):
    mgr, wal = _make_manager(tmp_path)
    class _ForceRollback(Exception):
        pass
    with pytest.raises(_ForceRollback):
        with mgr.transaction():
            raise _ForceRollback()
    assert mgr.active_tx is None
    tx = mgr.begin()
    assert tx.tx_id == 2
    mgr.rollback(tx)
    wal.close()


# 6. commit() / rollback() with a non-active tx raises ValueError.
def test_commit_with_stale_tx_raises_value_error(tmp_path):
    mgr, wal = _make_manager(tmp_path)
    stale = TransactionContext(tx_id=999, begin_lsn=1, manager=mgr)
    with pytest.raises(ValueError):
        mgr.commit(stale)
    assert mgr.active_tx is None
    assert _wal_records(wal) == []
    wal.close()


def test_rollback_with_stale_tx_raises_value_error(tmp_path):
    mgr, wal = _make_manager(tmp_path)
    stale = TransactionContext(tx_id=999, begin_lsn=1, manager=mgr)
    with pytest.raises(ValueError):
        mgr.rollback(stale)
    assert mgr.active_tx is None
    assert _wal_records(wal) == []
    wal.close()


# 7. begin() without commit/rollback records BEGIN only (the lock is
#    held until the caller releases it).
def test_begin_without_finish_records_begin_only(tmp_path):
    mgr, wal = _make_manager(tmp_path)
    tx = mgr.begin()
    try:
        assert mgr.active_tx is tx
        records = _wal_records(wal)
        assert len(records) == 1 and records[0].type == RT_BEGIN
    finally:
        mgr.rollback(tx)
    wal.close()


# 8. Two threads: T1 holds BEGIN; T2's begin() blocks until T1 commits.
def test_thread_blocks_until_other_commits(tmp_path):
    mgr, wal = _make_manager(tmp_path)

    t1_in_tx = threading.Event()
    t1_release = threading.Event()
    watcher_done = threading.Event()
    watcher_result: list = []

    def t1():
        with mgr.transaction():
            t1_in_tx.set()
            assert t1_release.wait(timeout=5.0), "watcher never finished"

    def watcher():
        # This call must block while T1 holds the lock.
        tx = mgr.begin()
        watcher_result.append(tx)
        mgr.rollback(tx)  # release on the acquiring thread
        watcher_done.set()

    th1 = threading.Thread(target=t1)
    th_w = threading.Thread(target=watcher)
    th1.start()
    assert t1_in_tx.wait(timeout=5.0)
    th_w.start()
    time.sleep(0.05)
    assert not watcher_done.is_set(), "watcher returned before T1 released"
    t1_release.set()
    th1.join(timeout=5.0)
    th_w.join(timeout=5.0)
    assert watcher_done.is_set()
    assert len(watcher_result) == 1 and watcher_result[0].tx_id == 2

    records = _wal_records(wal)
    assert [r.type for r in records] == [
        RT_BEGIN, RT_COMMIT, RT_BEGIN, RT_ROLLBACK,
    ]
    wal.close()


# 9. tx_id increments monotonically across BEGIN/COMMIT cycles.
def test_tx_id_increments_monotonically(tmp_path):
    mgr, wal = _make_manager(tmp_path)
    ids = []
    for _ in range(5):
        with mgr.transaction() as tx:
            ids.append(tx.tx_id)
    assert ids == [1, 2, 3, 4, 5]
    wal.close()


# 10. Records carry the correct tx_id in their payload.
def test_records_carry_tx_id_in_payload(tmp_path):
    mgr, wal = _make_manager(tmp_path)
    with mgr.transaction() as tx:
        txid = tx.tx_id
    begin, commit = _wal_records(wal)
    assert _decode_tx_id(begin.payload) == txid
    assert _decode_tx_id(commit.payload) == txid
    wal.close()