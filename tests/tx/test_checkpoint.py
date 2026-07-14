"""T-6.7 — Periodic checkpoint (RT_CKPT) tests.

A :class:`tinydb.tx.Checkpoint` records a WAL anchor: it appends a
single ``RT_CKPT`` frame whose payload is the LSN at which the
checkpoint was taken.  v0.1 does NOT truncate the WAL on checkpoint
(that needs LSN-per-page tracking, deferred per T-6.6 NIT-1).  The
recovery layer already ignores unknown record types, so RT_CKPT frames
are inert during replay.

Test strategy
-------------
The brief calls for six cases.  Cases 1-3 and 5-6 exercise the WAL
shape directly; case 4 is a regression test that exercises the same
end-to-end recovery path as T-6.6 to prove checkpointing doesn't break
the B6 gate.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import List

import pytest

from tinydb.executor.executor import Executor
from tinydb.executor.planner import plan
from tinydb.index.manager import IndexManager
from tinydb.sql.parser import parse_dml_string as parse
from tinydb.storage.catalog import Catalog
from tinydb.storage.pager import PAGE_SIZE, Pager
from tinydb.tx import (
    RT_BEGIN,
    RT_CKPT,
    RT_COMMIT,
    RT_PAGE,
    WAL,
    Checkpoint,
    TransactionManager,
)
from tinydb.tx.recovery import Recovery
from tinydb.types.system import Column, TypeTag


# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def _col(name: str, tag: TypeTag, **kw) -> Column:
    return Column(name=name, tag=tag, **kw)


def _fresh_wal(db_dir: Path) -> WAL:
    """Create a fresh WAL file at ``db_dir / 'test.wal'`` and open it."""
    db_dir.mkdir(parents=True, exist_ok=True)
    wal_path = db_dir / "test.wal"
    wal = WAL(wal_path, mode="w+b")
    wal.close()
    return WAL(wal_path)


def _fresh_db(db_dir: Path):
    """Build (pager, catalog, indexer, mgr, wal, executor) inside ``db_dir``."""
    db_dir.mkdir(parents=True, exist_ok=True)
    pager = Pager.open(db_dir / "test.db")
    catalog = Catalog(pager)
    catalog.create_table(
        "users",
        [
            _col("id", TypeTag.Int, primary_key=True, not_null=True),
            _col("name", TypeTag.Text, not_null=True),
            _col("age", TypeTag.Int),
        ],
    )
    wal = _fresh_wal(db_dir)
    indexer = IndexManager(catalog, pager)
    mgr = TransactionManager(pager, wal)
    executor = Executor(catalog, pager=pager, indexer=indexer, mgr=mgr)
    return pager, catalog, indexer, mgr, wal, executor


def _run_dml(executor: Executor, catalog: Catalog, sql: str):
    return executor.execute(plan(parse(sql), catalog, indexer=executor.indexer))


def _select_users(executor: Executor, catalog: Catalog) -> List[tuple]:
    return sorted(_run_dml(executor, catalog, "SELECT * FROM users"))


def _reopen_db(db_dir: Path):
    pager = Pager.open(db_dir / "test.db")
    catalog = Catalog(pager)
    wal = WAL(db_dir / "test.wal")
    Recovery(wal, pager).replay()
    indexer = IndexManager(catalog, pager)
    mgr = TransactionManager(pager, wal)
    executor = Executor(catalog, pager=pager, indexer=indexer, mgr=mgr)
    return pager, catalog, indexer, mgr, wal, executor


def _close(pager: Pager, wal: WAL) -> None:
    wal.close()
    pager.close()


def _decode_ckpt_payload(payload: bytes) -> int:
    """Decode the RT_CKPT payload: a single u64 BE LSN."""
    assert len(payload) == 8, f"unexpected payload length {len(payload)}"
    (lsn,) = struct.unpack(">Q", payload)
    return lsn


def _corrupt_page(db_dir: Path, pid: int, pattern: bytes = b"\\xCC" * PAGE_SIZE) -> None:
    path = db_dir / "test.db"
    with open(path, "r+b") as f:
        f.seek(pid * PAGE_SIZE)
        f.write(pattern)
        f.flush()
        os.fsync(f.fileno())


# ---------------------------------------------------------------------------
# Case 1: empty checkpoint — WAL has one RT_CKPT whose LSN equals the
# LSN that was next-to-assign at the moment ``run()`` was called.
# ---------------------------------------------------------------------------


def test_checkpoint_on_empty_wal_records_next_lsn(tmp_path):
    """An empty WAL has next_lsn == 1.  ``Checkpoint.run()`` must append
    one RT_CKPT record with LSN == 1 and advance the WAL to next_lsn == 2."""
    db = tmp_path / "db1"
    db.mkdir()
    pager, catalog, _, _, wal, _ = _fresh_db(db)
    try:
        assert wal.next_lsn == 1
        cp = Checkpoint(pager, wal)
        cp.run()
        assert wal.next_lsn == 2
        # Inspect the WAL: exactly one record, type RT_CKPT.
        records = list(wal.iter_from(1))
        assert len(records) == 1
        assert records[0].type == RT_CKPT
        assert records[0].lsn == 1
        assert _decode_ckpt_payload(records[0].payload) == 1
    finally:
        _close(pager, wal)


# ---------------------------------------------------------------------------
# Case 2: checkpoint after some DML — LSN advances.
# ---------------------------------------------------------------------------


def test_checkpoint_after_dml_advances_lsn(tmp_path):
    """After committing an INSERT (BEGIN, PAGE, COMMIT) the WAL has
    next_lsn == 4.  A checkpoint must consume LSN 4 and leave next_lsn
    at 5.  The RT_CKPT payload carries the LSN it consumed (== 4).
    """
    db = tmp_path / "db2"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    try:
        with mgr.transaction():
            _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
        # WAL holds BEGIN, PAGE, COMMIT (LSNs 1..3); next_lsn is 4.
        assert wal.next_lsn == 4
        Checkpoint(pager, wal).run()
        assert wal.next_lsn == 5
        records = list(wal.iter_from(1))
        assert [r.type for r in records] == [RT_BEGIN, RT_PAGE, RT_COMMIT, RT_CKPT]
        ckpt = records[-1]
        assert ckpt.lsn == 4
        assert _decode_ckpt_payload(ckpt.payload) == 4
    finally:
        _close(pager, wal)


# ---------------------------------------------------------------------------
# Case 3: checkpoint is recorded in the WAL — readable via iter_from().
# ---------------------------------------------------------------------------


def test_checkpoint_is_visible_via_iter_from(tmp_path):
    """After a checkpoint the RT_CKPT record shows up at the tail and
    is yielded by ``wal.iter_from(1)``."""
    db = tmp_path / "db3"
    db.mkdir()
    pager, catalog, _, _, wal, _ = _fresh_db(db)
    try:
        cp = Checkpoint(pager, wal)
        cp.run()
        # iter_from(1) includes the CKPT.
        all_records = list(wal.iter_from(1))
        ckpt_records = [r for r in all_records if r.type == RT_CKPT]
        assert len(ckpt_records) == 1
        assert ckpt_records[0].lsn == 1
        # iter_from(2) skips the CKPT (LSN 1 is < 2).
        after = list(wal.iter_from(2))
        assert after == []
    finally:
        _close(pager, wal)


# ---------------------------------------------------------------------------
# Case 4: regression — recovery still produces the correct state when
# the WAL contains a checkpoint between the BEGIN/COMMIT and the crash.
# This re-uses the T-6.6 layout; the B6 gate must not regress.
# ---------------------------------------------------------------------------


def test_recovery_with_checkpoint_in_log_still_works(tmp_path):
    """T-6.6 case 1 layout, with a checkpoint inserted between COMMIT
    and the simulated crash.  Recovery still restores the row."""
    db = tmp_path / "db4"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    try:
        with mgr.transaction():
            _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
        Checkpoint(pager, wal).run()
        heap_pid = catalog.get_table("users").heap_pid
        _corrupt_page(db, heap_pid)
    finally:
        _close(pager, wal)
    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        assert _select_users(e2, c2) == [(1, "a", 1)]
    finally:
        _close(p2, w2)


# ---------------------------------------------------------------------------
# Case 5: two consecutive checkpoints → WAL contains two RT_CKPT frames.
# ---------------------------------------------------------------------------


def test_two_consecutive_checkpoints_append_two_records(tmp_path):
    """Calling ``run()`` twice appends exactly two RT_CKPT frames; the
    second payload carries a higher LSN than the first."""
    db = tmp_path / "db5"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    try:
        with mgr.transaction():
            _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
        cp = Checkpoint(pager, wal)
        cp.run()
        cp.run()
        ckpts = [r for r in wal.iter_from(1) if r.type == RT_CKPT]
        assert len(ckpts) == 2
        first_lsn, second_lsn = ckpts[0].lsn, ckpts[1].lsn
        assert second_lsn == first_lsn + 1
        # The CKPT payload carries the LSN it consumed.
        assert _decode_ckpt_payload(ckpts[0].payload) == first_lsn
        assert _decode_ckpt_payload(ckpts[1].payload) == second_lsn
    finally:
        _close(pager, wal)


# ---------------------------------------------------------------------------
# Case 6: idempotency — each ``run()`` call appends exactly ONE record.
# Not zero, not many.
# ---------------------------------------------------------------------------


def test_each_run_appends_exactly_one_rt_ckpt(tmp_path):
    """Three checkpoints in a row produce three RT_CKPT records — not
    fewer (de-dup is not desired in v0.1) and not more (splitting the
    call into multiple frames would be a layering bug)."""
    db = tmp_path / "db6"
    db.mkdir()
    pager, catalog, _, _, wal, _ = _fresh_db(db)
    try:
        cp = Checkpoint(pager, wal)
        for _ in range(3):
            before = wal.next_lsn
            cp.run()
            after = wal.next_lsn
            # Each call must advance next_lsn by exactly one (one frame).
            assert after == before + 1, (
                f"Checkpoint.run() did not advance LSN by 1: "
                f"before={before} after={after}"
            )
        ckpts = [r for r in wal.iter_from(1) if r.type == RT_CKPT]
        assert len(ckpts) == 3
        # LSNs of the CKPT frames are consecutive.
        assert [c.lsn for c in ckpts] == [ckpts[0].lsn + i for i in range(3)]
    finally:
        _close(pager, wal)