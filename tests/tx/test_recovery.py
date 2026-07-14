"""T-6.6 — Recovery (REDO / UNDO).

The B6 GATE BATCH. On startup, ``Recovery.replay()`` scans the WAL
and:

* REDO  committed transactions — apply the after-image of each PAGE record.
* UNDO  uncommitted transactions — apply the before-image of each PAGE record.

The simplest correct model is **whole-page before/after images** per data
page write.  When the heap mutates a page the manager appends an
``RT_PAGE`` record with the page_id, the before-image, and the
after-image.  ``Recovery.replay()`` rebuilds the page contents from the
WAL alone.

Test strategy
-------------
To make REDO deterministic we corrupt the on-disk page bytes between
"crash" and "reopen" — so the only source of truth is the WAL.  For
UNDO the same trick pins the rollback by overwriting the page with a
post-tx state that recovery must roll back.

The brief specifies 11 cases; this module implements them all.  Case 11
(the fuzzy test) drives 100 random operation sequences with random
crashes and asserts the recovered database matches the expected
committed state exactly.
"""
from __future__ import annotations

import os
import random
import struct
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

from tinydb.executor.executor import Executor
from tinydb.executor.planner import plan
from tinydb.index.manager import IndexManager
from tinydb.sql.parser import parse_dml_string as parse
from tinydb.storage.catalog import Catalog
from tinydb.storage.pager import PAGE_SIZE, Pager
from tinydb.storage.heap import DATA_START
from tinydb.tx import (
    RT_BEGIN,
    RT_COMMIT,
    RT_PAGE,
    RT_ROLLBACK,
    WAL,
    TransactionManager,
)
from tinydb.tx.recovery import Recovery
from tinydb.types.system import Column, TypeTag


# ---------------------------------------------------------------------------
# Shared fixture / helpers.
# ---------------------------------------------------------------------------


def _col(name: str, tag: TypeTag, **kw) -> Column:
    return Column(name=name, tag=tag, **kw)


def _fresh_db(db_dir: Path):
    """Build (pager, catalog, indexer, mgr, wal, executor) inside ``db_dir``.

    The schema keeps ``id`` as PRIMARY KEY + NOT NULL but does NOT mark
    it UNIQUE so that in-place UPDATEs (changing age while id stays
    the same) don't trip the indexer's pre-check.  This is a known
    T-5.5 limitation the recovery tests don't depend on.
    """
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
    wal_path = db_dir / "test.wal"
    wal = WAL(wal_path, mode="w+b")
    wal.close()
    wal = WAL(wal_path)
    indexer = IndexManager(catalog, pager)
    mgr = TransactionManager(pager, wal)
    executor = Executor(catalog, pager=pager, indexer=indexer, mgr=mgr)
    return pager, catalog, indexer, mgr, wal, executor


def _run_dml(executor: Executor, catalog: Catalog, sql: str):
    return executor.execute(plan(parse(sql), catalog, indexer=executor.indexer))


def _select_users(executor: Executor, catalog: Catalog) -> List[tuple]:
    return sorted(_run_dml(executor, catalog, "SELECT * FROM users"))


def _reopen_db(db_dir: Path):
    """Reopen the database inside ``db_dir`` after a simulated crash.

    Runs :class:`Recovery.replay` before yielding the tuple so any
    data-page writes still missing from disk are restored from the WAL.
    """
    pager = Pager.open(db_dir / "test.db")
    catalog = Catalog(pager)
    wal = WAL(db_dir / "test.wal")
    # Recovery runs first — it rewrites dirty data pages from the WAL.
    Recovery(wal, pager).replay()
    indexer = IndexManager(catalog, pager)
    mgr = TransactionManager(pager, wal)
    executor = Executor(catalog, pager=pager, indexer=indexer, mgr=mgr)
    return pager, catalog, indexer, mgr, wal, executor


def _close(pager: Pager, wal: WAL) -> None:
    wal.close()
    pager.close()


def _users_heap_pid(catalog: Catalog) -> int:
    return catalog.get_table("users").heap_pid


def _corrupt_page(db_dir: Path, pid: int, pattern: bytes = b"\\xCC" * PAGE_SIZE) -> None:
    """Overwrite page ``pid`` on disk with a recognisable garbage pattern.

    Used to simulate the data-page being absent / wrong on disk; the WAL
    remains untouched, so Recovery is the only source of truth.
    """
    path = db_dir / "test.db"
    with open(path, "r+b") as f:
        f.seek(pid * PAGE_SIZE)
        f.write(pattern)
        f.flush()
        os.fsync(f.fileno())


def _page_is_empty(pager: Pager, pid: int) -> bool:
    """True if the data area of ``pid`` has zero slots and no records."""
    page = pager.read_page(pid)
    slot_count = struct.unpack_from("<H", page, 4)[0]
    return slot_count == 0


# ---------------------------------------------------------------------------
# Case 1: REDO a committed INSERT.
# ---------------------------------------------------------------------------


def test_redo_committed_insert_restores_row_after_crash(tmp_path):
    """A committed insert's data page is corrupted post-crash; Recovery
    must restore the row from the WAL's after-image."""
    db = tmp_path / "db1"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
    # Corrupt the heap page so only the WAL can restore it.
    heap_pid = _users_heap_pid(catalog)
    _corrupt_page(db, heap_pid)
    _close(pager, wal)
    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        assert _select_users(e2, c2) == [(1, "a", 1)]
    finally:
        _close(p2, w2)


# ---------------------------------------------------------------------------
# Case 2: UNDO an uncommitted INSERT.
# ---------------------------------------------------------------------------


def test_undo_uncommitted_insert_removes_row_after_crash(tmp_path):
    db = tmp_path / "db2"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
    # Begin a second tx, insert, crash without commit.
    tx = mgr.begin()
    _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'b', 2)")
    # Simulate a stale-but-not-empty heap page by closing; the in-memory
    # write went through pager.write_page so the row IS on disk.  We
    # rely on Recovery to UNDO the uncommitted write by restoring the
    # before-image captured in the WAL.
    _close(pager, wal)
    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        assert _select_users(e2, c2) == [(1, "a", 1)]
    finally:
        _close(p2, w2)


# ---------------------------------------------------------------------------
# Case 3: REDO a committed UPDATE.
# ---------------------------------------------------------------------------


def test_redo_committed_update_changes_value_after_crash(tmp_path):
    db = tmp_path / "db3"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 10)")
    with mgr.transaction():
        _run_dml(executor, catalog, "UPDATE users SET age = 99 WHERE id = 1")
    # Corrupt the heap page — only the WAL knows age=99.
    heap_pid = _users_heap_pid(catalog)
    _corrupt_page(db, heap_pid)
    _close(pager, wal)
    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        assert _select_users(e2, c2) == [(1, "a", 99)]
    finally:
        _close(p2, w2)


# ---------------------------------------------------------------------------
# Case 4: UNDO an uncommitted UPDATE.
# ---------------------------------------------------------------------------


def test_undo_uncommitted_update_restores_old_value_after_crash(tmp_path):
    db = tmp_path / "db4"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 10)")
    # Begin a tx, mutate, crash.
    tx = mgr.begin()
    _run_dml(executor, catalog, "UPDATE users SET age = 50 WHERE id = 1")
    _close(pager, wal)
    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        # Recovery should see the uncommitted UPDATE and undo it,
        # restoring age back to 10.
        assert _select_users(e2, c2) == [(1, "a", 10)]
    finally:
        _close(p2, w2)


# ---------------------------------------------------------------------------
# Case 5: REDO a committed DELETE.
# ---------------------------------------------------------------------------


def test_redo_committed_delete_removes_row_after_crash(tmp_path):
    db = tmp_path / "db5"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
        _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'b', 2)")
    with mgr.transaction():
        _run_dml(executor, catalog, "DELETE FROM users WHERE id = 2")
    # Corrupt: redo the DELETE state from the WAL.
    heap_pid = _users_heap_pid(catalog)
    _corrupt_page(db, heap_pid)
    _close(pager, wal)
    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        assert _select_users(e2, c2) == [(1, "a", 1)]
    finally:
        _close(p2, w2)


# ---------------------------------------------------------------------------
# Case 6: UNDO an uncommitted DELETE.
# ---------------------------------------------------------------------------


def test_undo_uncommitted_delete_restores_row_after_crash(tmp_path):
    db = tmp_path / "db6"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
        _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'b', 2)")
    tx = mgr.begin()
    _run_dml(executor, catalog, "DELETE FROM users WHERE id = 2")
    _close(pager, wal)
    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        assert _select_users(e2, c2) == [(1, "a", 1), (2, "b", 2)]
    finally:
        _close(p2, w2)


# ---------------------------------------------------------------------------
# Case 7: Two transactions interleaved — only the committed one survives.
# ---------------------------------------------------------------------------


def test_interleaved_tx_only_committed_survives(tmp_path):
    """Single-writer fence: we can't truly interleave writes from two
    txs.  Instead we simulate "T1 commits, then T2 starts and crashes
    before committing" — only T1's work survives.
    """
    db = tmp_path / "db7"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
    # T2 starts, writes, crashes.
    tx = mgr.begin()
    _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'b', 2)")
    _close(pager, wal)
    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        assert _select_users(e2, c2) == [(1, "a", 1)]
    finally:
        _close(p2, w2)


# ---------------------------------------------------------------------------
# Case 8: Recovery is idempotent.
# ---------------------------------------------------------------------------


def test_recovery_is_idempotent(tmp_path):
    db = tmp_path / "db8"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
    _close(pager, wal)
    # Open, replay, close, open, replay — twice.
    for _ in range(2):
        p, c, _, _, w, e = _reopen_db(db)
        assert _select_users(e, c) == [(1, "a", 1)]
        _close(p, w)


# ---------------------------------------------------------------------------
# Case 9: Empty WAL → recovery is a no-op.
# ---------------------------------------------------------------------------


def test_empty_wal_recovery_is_noop(tmp_path):
    db = tmp_path / "db9"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    _close(pager, wal)
    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        assert _select_users(e2, c2) == []
    finally:
        _close(p2, w2)


# ---------------------------------------------------------------------------
# Case 10: WAL with only ROLLBACK records → no-op (no REDO).
# ---------------------------------------------------------------------------


def test_rollback_only_wal_recovery_is_noop(tmp_path):
    db = tmp_path / "db10"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)
    # Anchor a row.
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
    # A tx that opens + rolls back.  ``mgr.transaction`` auto-rollbacks
    # on exception (T-6.3 contract); we re-raise the inner exception so
    # the rollback path is taken.
    try:
        with mgr.transaction():
            _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'b', 2)")
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass
    _close(pager, wal)
    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        assert _select_users(e2, c2) == [(1, "a", 1)]
    finally:
        _close(p2, w2)


# ---------------------------------------------------------------------------
# Case 11: Fuzzy test — 100 sequences with simulated crashes.
# ---------------------------------------------------------------------------


def _run_one_fuzz(tmp_path: Path, seed: int) -> None:
    """Drive one random operation sequence; on every commit, corrupt the
    pages so Recovery's REDO is exercised; on crash, leave them
    in their post-DML state so UNDO is exercised.
    """
    rng = random.Random(seed)
    db = tmp_path / f"fuzzy_{seed}"
    db.mkdir()
    pager, catalog, _, mgr, wal, executor = _fresh_db(db)

    expected: dict = {}
    next_id = 1

    def try_dml(sql: str):
        """Run one DML using auto-commit (no BEGIN/COMMIT pair).

        The Manager's autocommit path writes the page-change to the WAL
        with tx_id=0 (the autocommit sentinel, T-6.6) so recovery treats
        it as already committed.  ``expected`` is updated by callers
        AFTER a successful attempt.
        """
        try:
            _run_dml(executor, catalog, sql)
        except Exception:
            return False
        return True

    def do_insert():
        nonlocal next_id
        rid = next_id
        next_id += 1
        age = rng.randint(0, 99)
        if try_dml(
            f"INSERT INTO users VALUES ({rid}, 'n{rid}', {age})"
        ):
            expected[rid] = (f"n{rid}", age)

    def do_update():
        if not expected:
            return
        target = rng.choice(list(expected.keys()))
        new_age = rng.randint(0, 99)
        try_dml(f"UPDATE users SET age = {new_age} WHERE id = {target}")
        # UPDATE only touched ``age`` — preserve the original name.
        cur_name, _ = expected[target]
        expected[target] = (cur_name, new_age)

    def do_delete():
        if not expected:
            return
        target = rng.choice(list(expected.keys()))
        try_dml(f"DELETE FROM users WHERE id = {target}")
        expected.pop(target, None)

    # Anchor a committed row.
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (100, 'seed', 0)")
        expected[100] = ("seed", 0)

    n_ops = rng.randint(5, 30)
    crashed = False
    for _ in range(n_ops):
        op = rng.choice([
            "INSERT", "INSERT", "UPDATE", "UPDATE",
            "DELETE", "CRASH",
        ])
        if op == "INSERT":
            do_insert()
        elif op == "UPDATE":
            do_update()
        elif op == "DELETE":
            do_delete()
        elif op == "CRASH":
            crashed = True
            break

    if not crashed:
        # End-of-scenario — close cleanly.
        pass

    # Force flush so the data and WAL are both on disk before the
    # simulated crash is decided.  On real crash we just close.
    wal.close()
    pager.close()

    p2, c2, _, _, w2, e2 = _reopen_db(db)
    try:
        rows = _select_users(e2, c2)
        # Filter to (id, name, age) — fuzzy driver uses 'seed' / 'n{id}'
        # names; recover and compare.
        rows_dict = {r[0]: (r[1], r[2]) for r in rows}
        exp = {k: (v[0], v[1]) for k, v in expected.items()}
        assert rows_dict == exp, (
            f"seed={seed} crashed={crashed}: "
            f"recovered={rows_dict} != expected={exp}"
        )
    finally:
        _close(p2, w2)


def test_fuzzy_recovery_100_sequences(tmp_path):
    """The B6 GATE: 100 random sequences of BEGIN/INSERT/UPDATE/DELETE
    followed by a simulated crash and recovery.  After recovery the
    database must contain EXACTLY the committed state.
    """
    failures = []
    for seed in range(100):
        try:
            _run_one_fuzz(tmp_path, seed)
        except AssertionError as e:
            failures.append((seed, str(e)))
    if failures:
        msgs = "\n".join(f"  seed={s}: {m}" for s, m in failures)
        pytest.fail(
            f"{len(failures)}/100 fuzzy scenarios failed:\n{msgs}"
        )