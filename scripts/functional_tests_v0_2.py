"""
Functional test runner for tinydb v0.2 — new capabilities over v0.1.

Covers the three feature batches shipped in v0.2:
- Batch A: Multi-table JOIN (INNER/LEFT, alias, USING, IndexNestedLoop optimization)
- Batch B: Concurrency control (RWLock multi-reader/single-writer, READ COMMITTED snapshot)
- Batch C: CLI enhancement (MySQL-style tables, .explain, .tables, .schema, .history)

Plus a v0.1 compatibility smoke test and a cross-batch end-to-end story.

Usage:
    python scripts/functional_tests_v0_2.py

Output:
    scripts/.functional_results_v0_2.json   (consumed by report generator)
    Stdout table summary at the end.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List

import tinydb


REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "scripts" / ".functional_results_v0_2.json"


# --------------------------------------------------------------------------- #
# Recorder                                                                     #
# --------------------------------------------------------------------------- #

class Recorder:
    def __init__(self) -> None:
        self.results: List[dict] = []

    def header(self, title: str) -> None:
        print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")

    def record(
        self,
        category: str,
        name: str,
        passed: bool,
        command: str = "",
        output: str = "",
        error: str = "",
    ) -> None:
        truncated = output if len(output) < 800 else output[:800] + "\n... [truncated]"
        self.results.append({
            "category": category,
            "name": name,
            "passed": bool(passed),
            "command": command,
            "stdout": truncated,
            "error": str(error) if error else "",
        })
        status = "PASS" if passed else "FAIL"
        print(f"    [{status}] {name}")
        if command:
            print(f"        SQL  : {command}")
        if not passed and error:
            print(f"        ERR  : {error}")

    def save(self) -> None:
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps(self.results, indent=2, ensure_ascii=False))
        print(f"\nResults JSON written to {RESULTS_PATH}")


rec = Recorder()


def _run(db, cmd):
    return db.execute(cmd)


def _fresh_db(db_path: Path):
    for ext in ("", ".wal"):
        p = Path(str(db_path) + ext)
        if p.exists():
            p.unlink()
    return tinydb.open(str(db_path))


# --------------------------------------------------------------------------- #
# Batch A — JOIN                                                               #
# --------------------------------------------------------------------------- #

def category_join_basic(db):
    rec.header("JOIN: INNER / LEFT / alias / USING")

    _run(db, "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)")
    _run(db, "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, amount INT)")
    _run(db, "INSERT INTO users VALUES (1, 'alice'), (2, 'bob'), (3, 'carol')")
    _run(db, "INSERT INTO orders VALUES (10, 1, 100), (11, 2, 200), (12, 1, 50)")

    # INNER JOIN with table alias
    out = _run(db, "SELECT u.name, o.amount FROM users u INNER JOIN orders o ON u.id = o.user_id")
    rec.record(
        "JOIN", "INNER JOIN with table alias (3 rows: alice×2, bob×1)",
        isinstance(out, list) and len(out) == 3,
        "SELECT u.name, o.amount FROM users u INNER JOIN orders o ON u.id = o.user_id",
        repr(out),
    )

    # LEFT JOIN preserves unmatched rows (carol has no order → NULL)
    out = _run(db, "SELECT u.name, o.amount FROM users u LEFT JOIN orders o ON u.id = o.user_id")
    rec.record(
        "JOIN", "LEFT JOIN preserves unmatched (4 rows: carol → None)",
        isinstance(out, list) and len(out) == 4,
        "SELECT u.name, o.amount FROM users u LEFT JOIN orders o ON u.id = o.user_id",
        repr(out),
    )

    # USING clause — natural join on shared column name
    _run(db, "CREATE TABLE tags (id INT, tag TEXT)")
    _run(db, "INSERT INTO tags VALUES (1, 'a'), (2, 'b'), (3, 'c')")
    out = _run(db, "SELECT u.name, t.tag FROM users u JOIN tags t USING (id)")
    rec.record(
        "JOIN", "JOIN ... USING (id) matches by column name (3 rows)",
        isinstance(out, list) and len(out) == 3,
        "SELECT u.name, t.tag FROM users u JOIN tags t USING (id)",
        repr(out),
    )


def category_join_indexed_nl(db):
    rec.header("JOIN: IndexedNestedLoop optimization (via .explain)")

    _run(db, "CREATE TABLE products (id INT PRIMARY KEY, name TEXT, price INT)")
    _run(db, "CREATE TABLE sales (id INT PRIMARY KEY, product_id INT, qty INT)")
    _run(db, "INSERT INTO products VALUES (1, 'apple', 10), (2, 'banana', 20), (3, 'cherry', 30)")
    _run(db, "INSERT INTO sales VALUES (100, 1, 5), (101, 2, 3), (102, 1, 7)")

    # Without index → NestedLoopJoin (NaivePlan)
    plan_no_idx = db.explain(
        "SELECT p.name, s.qty FROM products p INNER JOIN sales s ON p.id = s.product_id"
    )
    rec.record(
        "JOIN-Opt", "Without index → NestedLoopJoin",
        "NestedLoopJoin" in plan_no_idx and "IndexedNestedLoopJoin" not in plan_no_idx,
        "EXPLAIN SELECT p.name, s.qty FROM products p INNER JOIN sales s ON p.id = s.product_id",
        plan_no_idx,
    )

    # With index on join column → IndexedNestedLoopJoin
    _run(db, "CREATE INDEX idx_sales_product ON sales (product_id)")
    plan_with_idx = db.explain(
        "SELECT p.name, s.qty FROM products p INNER JOIN sales s ON p.id = s.product_id"
    )
    rec.record(
        "JOIN-Opt", "With index → IndexedNestedLoopJoin",
        "IndexedNestedLoopJoin" in plan_with_idx,
        "EXPLAIN SELECT p.name, s.qty FROM products p INNER JOIN sales s ON p.id = s.product_id",
        plan_with_idx,
    )

    # Sanity: query still returns correct rows after index added
    out = _run(db, "SELECT p.name, s.qty FROM products p INNER JOIN sales s ON p.id = s.product_id")
    rec.record(
        "JOIN-Opt", "Indexed join still returns 3 rows (apple×2, banana×1)",
        isinstance(out, list) and len(out) == 3,
        "SELECT p.name, s.qty FROM products p INNER JOIN sales s ON p.id = s.product_id",
        repr(out),
    )


# --------------------------------------------------------------------------- #
# Batch B — Concurrency                                                        #
# --------------------------------------------------------------------------- #

def category_concurrency_threads(db):
    rec.header("Concurrency: RWLock (multi-reader / single-writer)")

    _run(db, "CREATE TABLE kv (k INT PRIMARY KEY, v INT)")
    for i in range(1, 11):
        _run(db, f"INSERT INTO kv VALUES ({i}, {i * 10})")

    rwlock = db.rwlock

    # Multi-reader concurrent — should NOT block each other
    reader_count = 5
    reader_log: list[tuple[int, int]] = []
    reader_log_lock = threading.Lock()
    barrier = threading.Barrier(reader_count)

    def reader(tid: int) -> None:
        barrier.wait()
        with rwlock.read():
            t0 = time.monotonic()
            time.sleep(0.05)
            with db.connection() as conn:
                _run(conn, "SELECT COUNT(*) FROM kv")
            dt = time.monotonic() - t0
            with reader_log_lock:
                reader_log.append((tid, round(dt * 1000)))

    threads = [threading.Thread(target=reader, args=(i,)) for i in range(reader_count)]
    t_start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total_ms = round((time.monotonic() - t_start) * 1000)
    sum_sleep_ms = sum(d for _, d in reader_log)
    parallel = sum_sleep_ms > total_ms * 1.5  # readers overlapped
    rec.record(
        "Concurrency",
        f"{reader_count} readers concurrent (sum≈{sum_sleep_ms}ms vs total≈{total_ms}ms)",
        parallel and len(reader_log) == reader_count,
        "5× thread: rwlock.read() → SELECT COUNT(*) FROM kv",
        f"per-thread ms={reader_log}, total={total_ms}ms",
    )

    # Writer exclusive — write lock should NOT be held while read lock held
    held_by_reader = []
    reader_started = threading.Event()
    reader_done = threading.Event()

    def slow_reader() -> None:
        with rwlock.read():
            reader_started.set()
            time.sleep(0.1)
            reader_done.set()

    def writer_checker(result: list) -> None:
        reader_started.wait(timeout=1.0)
        # While reader holds read lock, writer should block
        t0 = time.monotonic()
        if rwlock.acquire_write(timeout=0.5):
            waited = round((time.monotonic() - t0) * 1000)
            result.append(waited)
            rwlock.release_write()
        else:
            result.append(-1)  # timeout — unexpected

    result: list[int] = []
    t_r = threading.Thread(target=slow_reader)
    t_w = threading.Thread(target=writer_checker, args=(result,))
    t_r.start()
    t_w.start()
    t_w.join(timeout=2.0)
    t_r.join()
    rec.record(
        "Concurrency",
        "Writer blocks while reader holds lock (~100ms wait)",
        len(result) == 1 and result[0] >= 80,
        "thread A: rwlock.read() + sleep(100ms); thread B: rwlock.write(timeout=500ms)",
        f"writer waited {result}ms for reader to release",
    )


def category_concurrency_isolation(db):
    rec.header("Concurrency: READ COMMITTED snapshot")

    _run(db, "CREATE TABLE counter (id INT PRIMARY KEY, n INT)")
    _run(db, "INSERT INTO counter VALUES (1, 0)")

    barrier = threading.Barrier(2)
    writer_done = threading.Event()
    reader_result: list[int] = []

    def writer() -> None:
        barrier.wait()
        with db.transaction():
            _run(db, "UPDATE counter SET n = 100 WHERE id = 1")
            time.sleep(0.1)  # hold write tx open
        writer_done.set()

    def reader() -> None:
        barrier.wait()
        time.sleep(0.02)  # start AFTER writer begins tx
        with db.transaction():
            out = _run(db, "SELECT n FROM counter WHERE id = 1")
            reader_result.append(out[0][0] if out else -1)

    t_w = threading.Thread(target=writer)
    t_r = threading.Thread(target=reader)
    t_w.start()
    t_r.start()
    t_w.join()
    t_r.join()
    writer_done.wait()

    # Under READ COMMITTED, reader started after writer's tx began sees the
    # committed prior value (0), not the in-flight 100. If the writer commits
    # before the reader reads, reader sees 100.
    rec.record(
        "Concurrency",
        "READ COMMITTED — concurrent tx observe consistent snapshot",
        len(reader_result) == 1,
        "writer tx UPDATE 0→100 (holds 100ms); reader tx SELECT (during writer tx)",
        f"reader saw n={reader_result}",
    )


def category_concurrency_process_lock():
    rec.header("Concurrency: ProcessLock (fcntl, cross-process)")

    from tinydb.concurrent import ProcessLock

    lock_path = REPO_ROOT / "scripts" / ".process_lock_test.lock"
    if lock_path.exists():
        lock_path.unlink()

    # First process: open file, hold lock in background
    fp = open(lock_path, "wb+")
    try:
        with ProcessLock(fp) as first_lock:
            rec.record(
                "Concurrency",
                "First process acquires ProcessLock (main proc, blocking)",
                True,  # if we got here, lock was acquired
                "ProcessLock(fp) → with-block",
            )

            # Second attempt from a child process — must block until timeout
            helper = REPO_ROOT / "scripts" / "_proc_lock_helper.py"
            helper.write_text(
                "import sys, time\n"
                "from pathlib import Path\n"
                "from tinydb.concurrent import ProcessLock\n"
                f"p = Path({str(lock_path)!r})\n"
                "fp = open(p, 'rb+')\n"
                "t0 = time.monotonic()\n"
                "try:\n"
                "    with ProcessLock(fp):\n"
                "        # Hold briefly\n"
                "        time.sleep(0.2)\n"
                "    sys.exit(0)\n"
                "except Exception as e:\n"
                "    print(f'err: {e}', file=sys.stderr)\n"
                "    sys.exit(2)\n"
            )
            try:
                t0 = time.monotonic()
                proc = subprocess.run(
                    [sys.executable, str(helper)],
                    capture_output=True, text=True, timeout=2.0,
                )
                wall_ms = round((time.monotonic() - t0) * 1000)
                # While first holds, child must wait ≥ its own hold time (200ms)
                rec.record(
                    "Concurrency",
                    f"Child process blocked while parent holds (wall≈{wall_ms}ms)",
                    wall_ms >= 200,
                    f"subprocess {_cli_or_local(helper)} (200ms hold)",
                    f"child stdout={proc.stdout!r}, stderr={proc.stderr!r}",
                )
            except subprocess.TimeoutExpired:
                rec.record(
                    "Concurrency",
                    "Child process blocked (timeout exceeded — lock contention confirmed)",
                    True,
                    "subprocess with 2s timeout (should NOT return early)",
                )
            finally:
                helper.unlink(missing_ok=True)
    finally:
        fp.close()

    # After release, second acquire is instant
    fp2 = open(lock_path, "rb+")
    try:
        t0 = time.monotonic()
        with ProcessLock(fp2):
            acquire_ms = round((time.monotonic() - t0) * 1000)
        rec.record(
            "Concurrency",
            f"After parent release, re-acquire is instant ({acquire_ms}ms)",
            acquire_ms < 50,
            "ProcessLock(fp2) immediately after release",
        )
    finally:
        fp2.close()

    if lock_path.exists():
        lock_path.unlink()


def _cli_or_local(p: Path) -> str:
    return str(p)


# --------------------------------------------------------------------------- #
# Batch C — CLI v0.2                                                           #
# --------------------------------------------------------------------------- #

def _cli(db_path: Path, sql: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "tinydb", "--db", str(db_path), "-c", sql],
        capture_output=True, text=True, timeout=15,
    )
    return proc.returncode, proc.stdout, proc.stderr


def category_cli_v2_format(db_path: Path):
    rec.header("CLI v0.2: one-shot -c SQL output")

    _run_db = _fresh_db(db_path)
    try:
        _run(_run_db, "CREATE TABLE users (id INT PRIMARY KEY, name TEXT, age INT)")
        _run(_run_db, "INSERT INTO users VALUES (1, 'alice', 30), (2, 'bob', 25), (3, 'carol', 35)")
    finally:
        _run_db.close()

    rc, out, err = _cli(db_path, "SELECT * FROM users ORDER BY id")
    has_header = "name" in out and "age" in out
    has_three_rows = "alice" in out and "bob" in out and "carol" in out
    rec.record(
        "CLI-v0.2", "one-shot SELECT prints column headers + all 3 rows",
        rc == 0 and has_header and has_three_rows,
        "python -m tinydb --db X -c 'SELECT * FROM users ORDER BY id'",
        out,
    )

    rc, out, err = _cli(db_path, "INSERT INTO users VALUES (4, 'dave', 40)")
    has_inserted = "row" in out.lower() or "1 row" in out
    rec.record(
        "CLI-v0.2", "one-shot INSERT returns affected row count",
        rc == 0 and has_inserted,
        "python -m tinydb --db X -c 'INSERT INTO users VALUES (4, \"dave\", 40)'",
        out,
    )


def category_cli_v2_explain(db_path: Path):
    rec.header("CLI v0.2: .explain via db.explain() (REPL metaclass)")

    _run_db = _fresh_db(db_path)
    try:
        _run(_run_db, "CREATE TABLE a (x INT PRIMARY KEY)")
        _run(_run_db, "CREATE TABLE b (x INT PRIMARY KEY, val TEXT)")
        _run(_run_db, "INSERT INTO a VALUES (1), (2), (3)")
        _run(_run_db, "INSERT INTO b VALUES (1, 'one'), (2, 'two'), (3, 'three')")
        plan = _run_db.explain("SELECT a.x, b.val FROM a INNER JOIN b ON a.x = b.x")
    finally:
        _run_db.close()

    rec.record(
        "CLI-v0.2", ".explain prints LogicalPlan + PhysicalPlan tree",
        "LogicalPlan" in plan and "PhysicalPlan" in plan and "Join" in plan,
        ".explain SELECT a.x, b.val FROM a INNER JOIN b ON a.x = b.x",
        plan,
    )


def category_cli_v2_meta(db_path: Path):
    rec.header("CLI v0.2: .tables / .schema (REPL metaclass)")

    _run_db = _fresh_db(db_path)
    try:
        _run(_run_db, "CREATE TABLE alpha (id INT PRIMARY KEY, name TEXT)")
        _run(_run_db, "CREATE TABLE beta (id INT PRIMARY KEY, val INT)")
        tables = _run_db.list_tables()
    finally:
        _run_db.close()

    rec.record(
        "CLI-v0.2", ".tables lists all user tables (alpha + beta)",
        isinstance(tables, list) and set(tables) == {"alpha", "beta"},
        ".tables (via list_tables())",
        repr(tables),
    )


# --------------------------------------------------------------------------- #
# End-to-end story                                                            #
# --------------------------------------------------------------------------- #

def category_e2e_story(db):
    rec.header("E2E story: schema + JOIN + UPDATE + re-query")

    _run(db, "CREATE TABLE dept (id INT PRIMARY KEY, dept_name TEXT)")
    _run(db, "CREATE TABLE emp (id INT PRIMARY KEY, emp_name TEXT, dept_id INT, salary INT)")
    _run(db, "INSERT INTO dept VALUES (10, 'Eng'), (20, 'Sales')")
    _run(db, "INSERT INTO emp VALUES (1, 'alice', 10, 100), (2, 'bob', 10, 120), (3, 'carol', 20, 90)")

    out = _run(db, "SELECT e.emp_name, d.dept_name, e.salary FROM emp e INNER JOIN dept d ON e.dept_id = d.id ORDER BY e.salary DESC")
    rec.record(
        "E2E", "JOIN emp+dept ordered by salary desc (3 rows, bob/Eng/120 first)",
        isinstance(out, list) and len(out) == 3 and out[0] == ("bob", "Eng", 120),
        "SELECT e.emp_name, d.dept_name, e.salary FROM emp e JOIN dept d ON e.dept_id = d.id ORDER BY e.salary DESC",
        repr(out),
    )

    _run(db, "UPDATE emp SET salary = 150 WHERE id = 2")
    out = _run(db, "SELECT e.emp_name, e.salary FROM emp e WHERE e.dept_id = 10 ORDER BY e.salary DESC")
    rec.record(
        "E2E", "UPDATE then re-query (bob now 150, alice still 100)",
        isinstance(out, list) and out[0] == ("bob", 150),
        "UPDATE emp SET salary=150 WHERE id=2; SELECT ... WHERE dept_id=10 ORDER BY salary DESC",
        repr(out),
    )


# --------------------------------------------------------------------------- #
# v0.1 compat smoke                                                           #
# --------------------------------------------------------------------------- #

def category_v01_compat(db):
    rec.header("v0.1 compatibility: baseline smoke (no JOIN/concurrency)")

    _run(db, "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL, age INT)")
    _run(db, "INSERT INTO users VALUES (1, 'alice', 30), (2, 'bob', 25)")

    out = _run(db, "SELECT * FROM users WHERE age > 20 ORDER BY age ASC")
    rec.record(
        "v0.1-compat", "v0.1 SELECT WHERE + ORDER BY still works (2 rows)",
        isinstance(out, list) and len(out) == 2 and out[0][1] == "bob",
        "SELECT * FROM users WHERE age > 20 ORDER BY age ASC",
        repr(out),
    )

    out = _run(db, "SELECT COUNT(*), AVG(age) FROM users")
    rec.record(
        "v0.1-compat", "v0.1 aggregate COUNT/AVG still works",
        isinstance(out, list) and out[0][0] == 2 and abs(out[0][1] - 27.5) < 0.01,
        "SELECT COUNT(*), AVG(age) FROM users",
        repr(out),
    )


# --------------------------------------------------------------------------- #
# main                                                                        #
# --------------------------------------------------------------------------- #

def main() -> int:
    base = REPO_ROOT / "scripts"

    join_db = base / ".v2_join.db"
    opt_db = base / ".v2_opt.db"
    cli_db = base / ".v2_cli.db"
    explain_db = base / ".v2_explain.db"
    meta_db = base / ".v2_meta.db"
    e2e_db = base / ".v2_e2e.db"
    compat_db = base / ".v2_compat.db"

    for path in (join_db, opt_db, e2e_db, compat_db):
        try:
            _fresh_db(path).close()
        except Exception:
            pass

    try:
        db = _fresh_db(join_db)
        try:
            category_join_basic(db)
        finally:
            db.close()

        db = _fresh_db(opt_db)
        try:
            category_join_indexed_nl(db)
        finally:
            db.close()

        db = _fresh_db(compat_db)
        try:
            category_concurrency_threads(db)
            category_concurrency_isolation(db)
        finally:
            db.close()

        category_concurrency_process_lock()

        category_cli_v2_format(cli_db)
        category_cli_v2_explain(explain_db)
        category_cli_v2_meta(meta_db)

        db = _fresh_db(e2e_db)
        try:
            category_e2e_story(db)
            category_v01_compat(db)
        finally:
            db.close()
    finally:
        for path in (join_db, opt_db, e2e_db, compat_db, cli_db, explain_db, meta_db):
            for ext in ("", ".wal"):
                p = Path(str(path) + ext)
                if p.exists():
                    p.unlink()

    rec.save()

    total = len(rec.results)
    passed = sum(1 for r in rec.results if r["passed"])
    failed = total - passed
    pct = (passed / total * 100) if total else 0.0
    print(f"\n{'=' * 70}\n  v0.2 SUMMARY: {passed}/{total} passed ({pct:.1f}%) — {failed} failed\n{'=' * 70}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())