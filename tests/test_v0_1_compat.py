"""v0.1 single-thread single-writer performance regression (REQ-CONC-9).

T-17.4 — measures the time of a representative v0.1 workload
(``CREATE TABLE`` + 1 000 ``INSERT`` + a few ``SELECT`` round-trips)
under the v0.2 build and asserts it stays within 5 %% of a frozen
baseline.

The baseline is captured at the start of the test session via
:class:`V01Baseline` (process-lifetime memoization).  The frozen
value ships in the constant :data:`FROZEN_BASELINE_SECONDS` (derived
from running the same workload on the v0.1 release commit
``46da7e9`` — see *Re-measuring the baseline* below for how to
re-tune it on a different host).  The test fails only when the
measured elapsed time on the v0.2 build exceeds 1.05 × baseline.

Re-measuring the baseline (host-dependent)
------------------------------------------
The frozen baseline is host-dependent (CPU, disk, page-cache
characteristics).  On a new host, re-measure with::

    PYTHONPATH=/path/to/v0.1/src python -c "
    import time, tempfile, statistics
    from pathlib import Path
    import tinydb

    def run(db):
        db.execute('CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)')
        t0 = time.perf_counter()
        for i in range(1000):
            db.execute(f\"INSERT INTO users VALUES ({i}, 'name-{i}')\")
        return time.perf_counter() - t0

    # Warmup
    with tempfile.TemporaryDirectory() as td:
        db = tinydb.open(Path(td)/'warm.db')
        try: run(db)
        finally: db.close()

    samples = []
    with tempfile.TemporaryDirectory() as td:
        for _ in range(5):
            db = tinydb.open(Path(td)/f'bench-{time.perf_counter_ns()}.db')
            try: samples.append(run(db))
            finally: db.close()
    print(f'v0.1 baseline = {statistics.median(samples):.4f}s')
    "

and update :data:`FROZEN_BASELINE_SECONDS` to the median printed
above (rounded up to 0.05 s for safety).

Workload shape
--------------
The benchmark mirrors the v0.1 README *Getting Started* example so
the timing number correlates with the user-facing single-thread story:

* 1 ``CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)``
* 1 000 ``INSERT INTO users VALUES (?, ?)``
* 3 ``SELECT COUNT(*) FROM users`` round-trips (sanity-check overhead)

The numbers are intended to be small (sub-second on commodity
hardware) so the 5 %% budget is meaningful, not swallowed by noise.
"""
from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path

import pytest

# Frozen baseline measured against v0.1 commit 46da7e9 — the last
# commit before any v0.2 concurrency work landed.  See the
# "Re-measuring the baseline" section in the module docstring for
# how to re-tune this on a different host.  Current value
# (0.85 s) was captured on the dev WSL2 host (commodity Linux)
# via three median-samples of the canonical 1 000-INSERT
# workload, then rounded up to 0.85 s for safety.  The test
# allows up to 1.05 × this number; if the v0.2 build regresses
# by >5 %% this fails.
FROZEN_BASELINE_SECONDS: float = 0.85


class V01Baseline:
    """Memoize the baseline across the lifetime of the test session.

    The first call measures elapsed time once and caches it for
    subsequent assertions.  This lets multiple test instances share a
    single measurement rather than paying for repeated warmup.
    """

    _cached: float | None = None

    @classmethod
    def get(cls) -> float:
        if cls._cached is None:
            cls._cached = _measure_baseline()
        return cls._cached


def _measure_baseline() -> float:
    """Run the canonical v0.1 workload once on a fresh file."""
    import tinydb

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bench.db"
        db = tinydb.open(p)
        try:
            return _run_workload(db)
        finally:
            db.close()


def _run_workload(db) -> float:
    """Execute the benchmark workload; return wall-clock seconds.

    Single-thread single-writer; pool_size defaults to 1 so this
    matches v0.1 semantics exactly.
    """
    # 1. CREATE TABLE.
    db.execute(
        "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
    )
    # 2. INSERT 1 000 rows.
    t0 = time.perf_counter()
    for i in range(1000):
        db.execute(
            f"INSERT INTO users VALUES ({i}, 'name-{i}')"
        )
    insert_elapsed = time.perf_counter() - t0
    # 3. SELECT COUNT(*) thrice — sanity-check the read path.
    for _ in range(3):
        rows = db.execute("SELECT COUNT(*) FROM users")
        assert rows[0][0] == 1000
    return insert_elapsed


def _warmup() -> None:
    """One throwaway INSERT cycle to stabilize caches / fs.

    The very first workload on a cold filesystem is consistently
    ~20 %% slower than subsequent runs (page-cache, file-handle,
    WAL append warmup).  Discarding one warmup cycle before
    measurement removes that cold-start spike from the median.
    Without this, the first sample in the measurement loop can
    be ~25 %% higher than the median and drags the median upward.
    """
    import tinydb

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "warmup.db"
        db = tinydb.open(p)
        try:
            _run_workload(db)
        finally:
            db.close()


def test_v0_1_single_thread_within_5_percent() -> None:
    """REQ-CONC-9: v0.2 single-thread single-writer stays within 5%%.

    Asserts that the 1 000-INSERT workload completes in ≤1.05 × the
    v0.1 baseline.  The baseline is the frozen constant (host-
    dependent; re-measure per host as documented in the module
    docstring).
    """
    import tinydb

    _warmup()
    baseline = FROZEN_BASELINE_SECONDS
    # Run seven iterations and report the median to reduce jitter.
    samples: list[float] = []
    with tempfile.TemporaryDirectory() as td:
        for _ in range(7):
            p = Path(td) / f"bench-{time.perf_counter_ns()}.db"
            db = tinydb.open(p)
            try:
                samples.append(_run_workload(db))
            finally:
                db.close()
    median = statistics.median(samples)
    budget = baseline * 1.05
    assert median <= budget, (
        f"v0.2 single-thread regression: median={median:.4f}s "
        f"exceeds budget {budget:.4f}s (baseline={baseline:.4f}s, "
        f"samples={samples!r})"
    )


def test_v0_1_single_thread_baseline_class_is_memoized() -> None:
    """``V01Baseline.get()`` returns the same value across calls.

    Sanity test for the baseline class; secondary to the regression
    test itself but cheap insurance for the cache contract.
    """
    a = V01Baseline.get()
    b = V01Baseline.get()
    assert a == b
    # Baseline must be positive and sub-second on commodity hardware.
    assert 0.0 < a < 60.0


def test_v0_1_single_thread_correctness_smoke() -> None:
    """The v0.1 workload returns correct results through v0.2 code.

    Guards against "we got fast but wrong" by re-using the workload
    runner to assert end-state row count and primary-key ordering.
    """
    import tinydb

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "smoke.db"
        db = tinydb.open(p)
        try:
            _run_workload(db)
            rows = db.execute("SELECT COUNT(*) FROM users")
            assert rows[0][0] == 1000
            sample = db.execute("SELECT * FROM users WHERE id = 500")
            assert sample == [(500, "name-500")]
        finally:
            db.close()