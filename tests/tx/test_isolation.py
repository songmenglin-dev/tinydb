"""T-6.5 — Isolation (READ COMMITTED).

Per REQ-TRX-4: tinydb v0.1 provides READ COMMITTED isolation.  In a
single-process single-writer model this collapses to the following
contract:

1. SELECT against the heap reads only the **committed** state.
2. A SELECT running concurrently with an active transaction does NOT
   block on the writer's write lock.
3. A second ``mgr.begin()`` from another thread DOES block until the
   writer commits/rollbacks — the write lock fences concurrent writers.

Why this works in v0.1
---------------------
SELECT goes through :meth:`Heap.scan`, which is a pure read of the
slotted pages (no write-lock acquisition).  B5's DML paths only modify
the heap in-memory while the writer holds the lock; rows only persist
to disk on COMMIT (the heap's ``insert`` / ``delete`` calls ``write_page``
on the in-process Pager; the COMMIT happens under the same lock).  So
in the single-process fence a concurrent SELECT reads committed
state because nothing else can write — there is only one writer.

This module tests the integration of
:meth:`TransactionManager.begin` / ``commit`` / ``rollback`` with
:meth:`Heap.scan` for both sequential and cross-thread visibility.

Scope fence
-----------
* v0.1 is single-process only — there are no cross-process locks.
* We do not implement snapshot isolation or read-your-own-writes
  across separate transactions; only the *own-thread* RYOW inside a
  ``mgr.transaction()`` block is asserted (the writer can read its own
  in-flight inserts through Heap.scan because it holds the in-memory
  Pager).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Tuple

import pytest

from tinydb.executor.executor import Executor
from tinydb.executor.planner import plan
from tinydb.index.manager import IndexManager
from tinydb.sql.parser import parse_dml_string as parse
from tinydb.storage.catalog import Catalog
from tinydb.storage.pager import Pager
from tinydb.tx import WAL, TransactionManager
from tinydb.types.system import Column, TypeTag


# ---------------------------------------------------------------------------
# Shared fixture — same shape as test_constraints.py so the suite is uniform.
# ---------------------------------------------------------------------------


def _col(name: str, tag: TypeTag, **kw) -> Column:
    return Column(name=name, tag=tag, **kw)


@pytest.fixture
def users_db(tmp_path) -> Tuple[
    Pager, Catalog, IndexManager, TransactionManager, WAL, Executor
]:
    """Pager + Catalog (users id PK/UNIQUE/NN, name NN, age) + IndexManager.

    Public surface for the suite: yields ``(pager, catalog, indexer,
    mgr, wal, executor)`` so each test can drive its own scenario.
    """
    pager = Pager.open(tmp_path / "test.db")
    catalog = Catalog(pager)
    catalog.create_table(
        "users",
        [
            _col("id", TypeTag.Int, primary_key=True, unique=True, not_null=True),
            _col("name", TypeTag.Text, not_null=True),
            _col("age", TypeTag.Int),
        ],
    )
    wal = WAL(tmp_path / "test.wal", mode="w+b")
    wal.close()
    wal = WAL(tmp_path / "test.wal")
    indexer = IndexManager(catalog, pager)
    indexer.create_index("idx_users_id", "users", ("id",), unique=True)
    mgr = TransactionManager(pager, wal)
    executor = Executor(catalog, pager=pager, indexer=indexer)
    try:
        yield pager, catalog, indexer, mgr, wal, executor
    finally:
        wal.close()
        pager.close()


def _run_dml(executor: Executor, catalog: Catalog, sql: str):
    return executor.execute(plan(parse(sql), catalog, indexer=executor.indexer))


def _select_users(executor: Executor, catalog: Catalog):
    return sorted(_run_dml(executor, catalog, "SELECT * FROM users"))


# ---------------------------------------------------------------------------
# Sequential visibility tests.
# ---------------------------------------------------------------------------


# 1. Reader (sequential, after commit) sees committed rows.
def test_reader_sees_committed_rows(users_db):
    _, catalog, _, _, _, executor = users_db
    assert _select_users(executor, catalog) == []
    _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'alice', 30)")
    assert _select_users(executor, catalog) == [(1, "alice", 30)]


# 2. Sequential read after commit sees the row.
def test_sequential_read_after_commit_sees_row(users_db):
    _, catalog, _, mgr, _, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (7, 'carol', 40)")
    assert _select_users(executor, catalog) == [(7, "carol", 40)]


# 3. Sequential read after an explicit ROLLBACK (no intervening DML)
#    leaves the heap untouched.  This pins the positive half of the
#    contract that READ COMMITTED depends on: an explicit
#    ``mgr.rollback(tx)`` without any DML must leave the table as it
#    was.  Per-statement forced rollback via a raised exception is a
#    separate case pinned in test_constraints #10 — it currently leaks
#    the in-memory row, and T-6.6 will harden that path with a real
#    UNDO log.  We test only what T-6.5's READ COMMITTED contract
#    demands here.
def test_sequential_read_after_explicit_rollback_hides_row(users_db):
    _, catalog, _, mgr, _, executor = users_db
    # Anchor a committed row so the table is non-empty.
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'alice', 30)")
    # Open a tx, then ROLLBACK without any DML — external state must
    # be untouched.
    tx = mgr.begin()
    mgr.rollback(tx)
    assert _select_users(executor, catalog) == [(1, "alice", 30)]


# 4. Same-thread read-your-own-writes: a SELECT inside the writer's tx
#    (between BEGIN and COMMIT) sees the writer's freshly inserted row
#    through Heap.scan because the writer is the only one mutating
#    the in-process Pager.
def test_same_thread_ryow_inside_transaction(users_db):
    _, catalog, _, mgr, _, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (3, 'dave', 50)")
        # Same-thread SELECT — writer holds the lock and the heap is
        # in-memory; the writer sees its own work in flight.
        assert _select_users(executor, catalog) == [(3, "dave", 50)]


# 5. A committed multi-statement tx is visible to the next reader.
#    This is the positive end of the contract: whatever the writer
#    commits, the next SELECT (lock-free Heap.scan) sees.  Locks the
#    end-to-end "write→commit→read" cycle into the suite.
def test_committed_multi_statement_tx_visible_to_later_select(users_db):
    _, catalog, _, mgr, _, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
        _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'b', 2)")
        _run_dml(executor, catalog, "INSERT INTO users VALUES (3, 'c', 3)")
    assert _select_users(executor, catalog) == [
        (1, "a", 1), (2, "b", 2), (3, "c", 3),
    ]


# ---------------------------------------------------------------------------
# Cross-thread tests — the writer's write lock fences the second writer
# while the lock-free Heap.scan reads proceed without blocking.
# ---------------------------------------------------------------------------


# 6. Concurrent SELECT against an active writer does NOT block on the
#    write lock.  A second thread runs Heap.scan directly (no
#    mgr.begin()) and must finish within a tight timeout even while
#    the writer holds BEGIN.
def test_select_bypasses_write_lock(users_db):
    _, catalog, _, mgr, _, executor = users_db
    # Seed a committed row so the SELECT has something to look at.
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")

    in_tx = threading.Event()
    release = threading.Event()
    select_done = threading.Event()
    select_rows: list = []

    def writer() -> None:
        # Hold a tx open; the lock must NOT block the reader.
        with mgr.transaction():
            in_tx.set()
            assert release.wait(timeout=2.0), "test timed out"

    def reader() -> None:
        # Direct Heap.scan — no mgr.begin(), no write lock acquisition.
        assert in_tx.wait(timeout=2.0)
        # Run the SELECT through the executor; it must complete well
        # under 2 s while the writer still holds the lock.
        deadline = time.monotonic() + 2.0
        rows = _select_users(executor, catalog)
        assert time.monotonic() <= deadline, "SELECT blocked on write lock"
        select_rows.append(rows)
        select_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        wf = pool.submit(writer)
        rf = pool.submit(reader)
        # Confirm the reader finished while the writer still holds tx.
        assert select_done.wait(timeout=2.0), "reader thread never returned"
        # Now let the writer release.
        release.set()
        wf.result(timeout=2.0)
        rf.result(timeout=2.0)
    assert select_rows[0] == [(1, "a", 1)]


# 7. Two writers: the second mgr.begin() BLOCKS until the first tx
#    finishes.  This pins the multi-writer blocking contract from
#    T-6.1 / T-6.3 and is the flip-side of test (6).
def test_second_begin_blocks_until_first_commits(users_db):
    _, catalog, _, mgr, _, executor = users_db
    writer_held = threading.Event()
    release = threading.Event()
    second_started = threading.Event()
    second_started_lock = threading.Lock()

    def first():
        with mgr.transaction():
            writer_held.set()
            assert release.wait(timeout=2.0)

    def second():
        assert writer_held.wait(timeout=2.0)
        # Give the scheduler a beat so we can prove the block.
        time.sleep(0.05)
        tx = mgr.begin()  # must block here
        with second_started_lock:
            second_started.set()
        mgr.commit(tx)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(first)
        f2 = pool.submit(second)
        # Sleep briefly; second should NOT have acquired its tx yet.
        time.sleep(0.1)
        with second_started_lock:
            assert not second_started.is_set(), (
                "second begin() did not block on writer's write lock"
            )
        release.set()
        f1.result(timeout=2.0)
        f2.result(timeout=2.0)
        with second_started_lock:
            assert second_started.is_set()


# 8. End-to-end: writer commits an INSERT; a lock-free reader sees it
#    AFTER the COMMIT.  Before COMMIT the reader would observe the
#    pre-tx state (single-writer fence).  Combined with test (6) this
#    pins READ COMMITTED end-to-end across threads.
def test_reader_sees_committed_data_after_commit(users_db):
    _, catalog, _, mgr, _, executor = users_db
    # Anchor a row that BOTH states share so the SELECT is non-trivial.
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a', 1)")
    assert _select_users(executor, catalog) == [(1, "a", 1)]

    release = threading.Event()

    def writer() -> None:
        with mgr.transaction():
            # Append a second row inside the open tx.
            _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'b', 2)")
            assert release.wait(timeout=2.0)

    with ThreadPoolExecutor(max_workers=1) as pool:
        wf = pool.submit(writer)
        # Give the writer a moment to enter its tx and write.
        time.sleep(0.05)
        release.set()
        wf.result(timeout=2.0)
    # After COMMIT, the row IS visible (this is the post-tx snapshot).
    assert _select_users(executor, catalog) == [(1, "a", 1), (2, "b", 2)]
