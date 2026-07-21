"""tinydb v0.2 — runnable end-to-end demo.

Walks the v0.2 surface in seven steps:

    1.  Open a fresh, on-disk database (pool_size=8).
    2.  CREATE TABLE users / orders.
    3.  INSERT a handful of rows into each table.
    4.  INNER JOIN users + orders; print the result.
    5.  Launch 8 concurrent writer threads; verify no rows lost.
    6.  Run a SELECT from 4 reader threads against the same writer.
    7.  .explain — print the ASCII plan tree for a JOIN+WHERE query.

Exit code 0 means every step worked.  Anything else means something
broke; see the traceback.

Run it from the repo root:

    PYTHONPATH=src python examples/demo_v0_2.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import tinydb


def _open_demo_db(path: Path) -> tinydb.Database:
    """Open v0.2 with pool_size=8; pool_size>1 opts into the per-conn pool."""
    return tinydb.open(str(path), pool_size=8)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "demo_v0_2.db"
        db = _open_demo_db(db_path)
        try:
            print(f"[1/7] opened {db_path} (pool_size={db.pool_size})")

            # 2. CREATE TABLE
            db.execute(
                "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE orders (oid INT PRIMARY KEY, uid INT, total INT)"
            )
            print("[2/7] created tables: users, orders")

            # 3. INSERT
            db.execute(
                "INSERT INTO users VALUES (1, 'alice'), (2, 'bob'), (3, 'carol')"
            )
            db.execute(
                "INSERT INTO orders VALUES "
                "(10, 1, 100), (11, 1, 200), (12, 2, 50)"
            )
            print("[3/7] inserted 3 users, 3 orders")

            # 4. INNER JOIN
            rows = db.execute(
                "SELECT users.id, users.name, orders.total "
                "FROM users INNER JOIN orders ON users.id = orders.uid "
                "ORDER BY users.id, orders.total"
            )
            print(f"[4/7] INNER JOIN returned {len(rows)} rows:")
            for r in rows:
                print("        ", r)

            # 5. Concurrent writers — REQ-CONC-2..6
            db.execute("CREATE TABLE counters (id INT PRIMARY KEY, n INT)")
            n_threads, per_thread = 8, 25
            errors: list[BaseException] = []

            def writer(tid: int) -> None:
                try:
                    with db.connection() as conn:
                        for i in range(per_thread):
                            conn.execute(
                                f"INSERT INTO counters VALUES ({tid * 1000 + i}, 1)"
                            )
                except BaseException as e:  # pragma: no cover
                    errors.append(e)

            threads = [
                threading.Thread(target=writer, args=(t,))
                for t in range(n_threads)
            ]
            t0 = time.monotonic()
            for t in threads: t.start()
            for t in threads: t.join()
            elapsed = time.monotonic() - t0
            if errors:
                raise SystemExit(f"writer errors: {errors!r}")
            count = db.execute("SELECT COUNT(*) FROM counters")[0][0]
            assert count == n_threads * per_thread, (
                f"lost inserts: expected {n_threads * per_thread}, got {count}"
            )
            print(
                f"[5/7] {n_threads} writers x {per_thread} inserts = {count} rows "
                f"in {elapsed:.2f}s"
            )

            # 6. Multi-thread SELECT (REQ-CONC-7)
            n_readers, n_iterations = 4, 20
            reader_errors: list[BaseException] = []

            def reader() -> None:
                try:
                    for _ in range(n_iterations):
                        rows = db.execute("SELECT COUNT(*) FROM counters")
                        if rows[0][0] != count:
                            reader_errors.append(
                                AssertionError(f"reader saw {rows[0][0]}")
                            )
                except BaseException as e:  # pragma: no cover
                    reader_errors.append(e)

            def slow_writer() -> None:
                try:
                    for i in range(n_iterations):
                        db.execute(
                            f"UPDATE counters SET n = {i} WHERE id = 0"
                        )
                except BaseException as e:  # pragma: no cover
                    reader_errors.append(e)

            threads2 = [
                threading.Thread(target=reader) for _ in range(n_readers)
            ] + [threading.Thread(target=slow_writer)]
            t0 = time.monotonic()
            for t in threads2: t.start()
            for t in threads2: t.join()
            reader_elapsed = time.monotonic() - t0
            if reader_errors:
                raise SystemExit(f"reader errors: {reader_errors!r}")
            print(
                f"[6/7] {n_readers} readers x {n_iterations} SELECTs "
                f"alongside 1 writer in {reader_elapsed:.2f}s"
            )

            # 7. .explain (REQ-CLI-13)
            plan = db.explain(
                "SELECT users.name FROM users INNER JOIN orders "
                "ON users.id = orders.uid WHERE orders.total > 60"
            )
            print("[7/7] .explain output:")
            for line in plan.splitlines():
                print("        ", line)
        finally:
            db.close()

    print("OK — every step finished without error.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
