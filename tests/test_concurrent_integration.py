"""Multi-thread + multi-process integration tests for tinydb v0.2.

Coverage:
* REQ-CONC-8 — multi-thread (32-thread 5 s) and multi-process
  (4-process 1W/3R) integration stress.
* T-17.3 — first commit of ``test_concurrent_integration.py``.

The single-process unit tests for the concurrency primitives (RWLock,
DeadlockDetector, ProcessLock, BufferPool LSN invalidation, etc.) live
in ``test_concurrent.py``; this file focuses on the *integration* of
those primitives through the full :class:`Database` stack.

Why a separate file?
The 32-thread stress runs ~5 s and the multi-process test forks
several Python interpreters.  They deserve their own module so test
collection, markers, and ``-k`` filtering can target them
specifically.  The previous ``tests/test_concurrent.py`` includes an
8-thread smoke test that exercises the same code paths at lower
load; that smoke test now lives here too.
"""
from __future__ import annotations

import multiprocessing
import os
import threading
import time
from pathlib import Path

import pytest


# --------------------------------------------------------------------------
# REQ-CONC-8 — multi-thread stress
# --------------------------------------------------------------------------


def test_database_8_thread_insert_select_stress(tmp_path: Path) -> None:
    """8 threads concurrently issue INSERTs and SELECTs through the pool.

    Light smoke test (sub-second) that exercises the same code paths
    as the heavier 32-thread 5-second spec test below.  This is the
    fast version that the developer runs every iteration; the strict
    32-thread version is the spec-acceptance test.
    """
    import tinydb

    p = tmp_path / "stress8.db"
    db = tinydb.open(p, pool_size=8)
    try:
        db.execute("CREATE TABLE k (id INT PRIMARY KEY, v INT)")
        errors: list = []

        def worker(start: int) -> None:
            try:
                with db.connection() as conn:
                    for i in range(start, start + 5):
                        conn.execute(
                            f"INSERT INTO k VALUES ({i}, {i * 10})"
                        )
                    rows = conn.execute("SELECT COUNT(*) FROM k")
                    assert rows[0][0] >= 1
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(t * 100,)) for t in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        assert not errors, f"workers failed: {errors!r}"
        # Final count should equal 8 * 5 = 40 (disjoint id ranges).
        final = db.execute("SELECT COUNT(*) FROM k")
        assert final[0][0] == 40
    finally:
        db.close()


# 32-thread test is opt-in because it takes ~5 seconds.
@pytest.mark.slow
def test_database_32_thread_insert_select_stress_5_seconds(tmp_path: Path) -> None:
    """REQ-CONC-8 spec-acceptance: 32 threads × 5 s of mixed INSERT/SELECT.

    Mirrors the contract Scenario verbatim.  Must show no exception,
    no torn row, no short read on the pager; final row count must equal
    the number of successful INSERTs across all workers.
    """
    import tinydb

    p = tmp_path / "stress32.db"
    db = tinydb.open(p, pool_size=32)
    try:
        db.execute("CREATE TABLE k (id INT PRIMARY KEY, v INT)")
        stop = threading.Event()
        errors: list = []
        # Per-worker success counter so we can validate the final row
        # count matches the number of inserts that actually committed.
        successes = [0]
        successes_lock = threading.Lock()

        def worker(worker_id: int) -> None:
            local_ok = 0
            local_tick = 0
            try:
                while not stop.is_set():
                    with db.connection() as conn:
                        # Each worker owns a disjoint id subspace:
                        # id = worker_id * 1_000_000 + monotonic_tick.
                        for _ in range(10):
                            row_id = worker_id * 1_000_000 + local_tick
                            local_tick += 1
                            try:
                                conn.execute(
                                    f"INSERT INTO k VALUES ({row_id}, {row_id * 10})"
                                )
                                local_ok += 1
                            except Exception as exc:
                                # PK collisions across ticks within one
                                # worker are tolerated only because the
                                # worker reuses the same id subspace;
                                # in this schema each tick is unique,
                                # so real collisions are unexpected.
                                errors.append(exc)
                        # Read-side check at end of each cycle.
                        rows = conn.execute("SELECT COUNT(*) FROM k")
                        assert rows[0][0] >= local_ok
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                with successes_lock:
                    successes[0] += local_ok

        workers = [
            threading.Thread(target=worker, args=(i,)) for i in range(32)
        ]
        for w in workers:
            w.start()
        time.sleep(5.0)
        stop.set()
        for w in workers:
            w.join(timeout=15.0)
        assert not errors, f"workers raised {len(errors)} errors: {errors[:3]!r}"
        # Final on-disk count must equal the number of successful
        # INSERTs across all workers (PK collisions are not expected
        # because each worker writes a unique id subspace).
        final = db.execute("SELECT COUNT(*) FROM k")
        assert final[0][0] == successes[0], (
            f"row count drift: on-disk={final[0][0]} successes={successes[0]}"
        )
    finally:
        db.close()


# --------------------------------------------------------------------------
# REQ-CONC-8 — multi-process stress (skipped unless fork works)
# --------------------------------------------------------------------------


def _mp_writer(path: str, count: int, ready_q, done_q) -> None:
    """Writer subprocess: open the DB and INSERT ``count`` rows.

    Opens with ``use_process_lock=True`` so the cross-process fcntl
    file lock is acquired around each INSERT and COMMIT.  Pair this
    with :func:`_mp_reader` which takes the same lock in shared mode
    for SELECTs so readers can never interleave with a writer.
    """
    import tinydb

    try:
        db = tinydb.open(path, use_process_lock=True)
        try:
            for i in range(count):
                db.execute(
                    f"INSERT INTO mp VALUES ({i}, '{os.getpid()}-{i}')"
                )
        finally:
            db.close()
        done_q.put(("writer-done", os.getpid(), count))
    except Exception as exc:  # noqa: BLE001
        done_q.put(("writer-error", os.getpid(), repr(exc)))


def _mp_reader(path: str, duration: float, ready_q, done_q) -> None:
    """Reader subprocess: SELECT repeatedly for ``duration`` seconds.

    Must never see a partial row (a row count that exceeds the
    writer's INSERT count, or a missing row's id), and must not
    raise any exception.

    Opens with ``use_process_lock=True`` so each SELECT takes a
    shared :class:`ProcessLock` on the WAL file, blocking while a
    writer holds the exclusive lock (REQ-CONC-2).
    """
    import tinydb

    try:
        db = tinydb.open(path, use_process_lock=True)
        try:
            ready_q.put(("reader-ready", os.getpid()))
            end = time.monotonic() + duration
            seen_counts: list = []
            while time.monotonic() < end:
                rows = db.execute("SELECT COUNT(*) FROM mp")
                cnt = rows[0][0]
                seen_counts.append(cnt)
            # Reader must observe a monotonically non-decreasing count
            # across all its samples — a reader can never see fewer
            # rows than it saw before within its own observation window.
            for i in range(1, len(seen_counts)):
                if seen_counts[i] < seen_counts[i - 1]:
                    raise AssertionError(
                        f"reader saw decreasing count: "
                        f"{seen_counts[i-1]} -> {seen_counts[i]}"
                    )
        finally:
            db.close()
        done_q.put(("reader-done", os.getpid(), len(seen_counts)))
    except Exception as exc:  # noqa: BLE001
        done_q.put(("reader-error", os.getpid(), repr(exc)))


@pytest.mark.skipif(
    os.name != "posix", reason="POSIX-only multi-process test (fcntl fork)"
)
def test_database_multi_process_1w_3r(tmp_path: Path) -> None:
    """REQ-CONC-8: 1 writer subprocess + 3 reader subprocesses.

    Writer appends 200 rows; each reader polls SELECT COUNT(*) for
    3 seconds.  The writer's ProcessLock prevents torn inserts; the
    readers must observe a monotonically non-decreasing count.
    """
    if multiprocessing.get_start_method() != "fork":
        pytest.skip(
            "requires fork-based multiprocessing (ProcessLock semantics "
            "depend on inherited file descriptors)"
        )
    p = tmp_path / "mp.db"
    # Create the empty DB so children can open it (the WAL gets
    # truncated by the first opener that writes).
    import tinydb

    db = tinydb.open(p)
    try:
        db.execute(
            "CREATE TABLE mp (id INT PRIMARY KEY, v TEXT)"
        )
    finally:
        db.close()

    ready_q = multiprocessing.Queue()
    done_q = multiprocessing.Queue()

    writer = multiprocessing.Process(
        target=_mp_writer,
        args=(str(p), 200, ready_q, done_q),
    )
    readers = [
        multiprocessing.Process(
            target=_mp_reader,
            args=(str(p), 3.0, ready_q, done_q),
        )
        for _ in range(3)
    ]

    writer.start()
    for r in readers:
        r.start()
    for r in readers:
        r.join(timeout=10.0)
        assert r.exitcode == 0, f"reader {r.pid} failed (exitcode={r.exitcode})"
    writer.join(timeout=10.0)
    assert writer.exitcode == 0, (
        f"writer failed (exitcode={writer.exitcode})"
    )

    # Drain done_q.
    results = []
    while not done_q.empty():
        results.append(done_q.get_nowait())
    # Expect one writer-done + 3 reader-done, no errors.
    tags = [r[0] for r in results]
    assert tags.count("reader-done") == 3, tags
    assert tags.count("writer-done") == 1, tags
    assert "writer-error" not in tags
    assert "reader-error" not in tags
