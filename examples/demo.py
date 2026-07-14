"""tinydb v0.1 — runnable end-to-end demo.

Walks through the full surface of the public API in ten steps:

    1.  Open a fresh, on-disk database.
    2.  CREATE TABLE users + orders.
    3.  INSERT a handful of rows into each table.
    4.  SELECT — print every row.
    5.  CREATE INDEX on users(name).
    6.  SELECT WHERE name = 'alice' — uses the new index.
    7.  UPDATE a single row.
    8.  Aggregate: COUNT / AVG per group.
    9.  Transaction: BEGIN / INSERT / COMMIT.
    10. Cleanup: DROP TABLE, close the database.

Run it from the repo root:

    python examples/demo.py

Exit code 0 means every step worked.  Anything else means something
broke; see the traceback.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import tinydb


def _banner(step: int, title: str) -> None:
    """Print a one-line banner so the demo's stdout reads top-to-bottom."""
    print(f"\n--- step {step}: {title} ---")


def main() -> int:
    # --- 1. Open a fresh DB in a temp directory. ---------------------------
    tmpdir = Path(tempfile.mkdtemp(prefix="tinydb-demo-"))
    db_path = tmpdir / "demo.db"
    print(f"tinydb v0.1 demo — db at {db_path}")
    db = tinydb.open(db_path)

    try:
        # --- 2. CREATE TABLE users + orders --------------------------------
        _banner(2, "CREATE TABLE users, orders")
        db.execute(
            "CREATE TABLE users ("
            "id INT PRIMARY KEY, "
            "name TEXT NOT NULL, "
            "age INT"
            ")"
        )
        db.execute(
            "CREATE TABLE orders ("
            "id INT PRIMARY KEY, "
            "user_id INT, "
            "amount INT"
            ")"
        )

        # --- 3. INSERT 5 users and 3 orders -------------------------------
        _banner(3, "INSERT 5 users + 3 orders")
        users = [
            (1, "alice", 30),
            (2, "bob", 25),
            (3, "carol", 40),
            (4, "dave", 22),
            (5, "eve", 35),
        ]
        for row in users:
            db.execute(f"INSERT INTO users VALUES ({row[0]}, '{row[1]}', {row[2]})")

        orders = [
            (100, 1, 50),
            (101, 1, 75),
            (102, 2, 120),
        ]
        for row in orders:
            db.execute(
                f"INSERT INTO orders VALUES ({row[0]}, {row[1]}, {row[2]})"
            )

        # --- 4. SELECT — print every row ----------------------------------
        _banner(4, "SELECT * FROM users")
        for row in db.execute("SELECT * FROM users ORDER BY id"):
            print(row)

        _banner("4b", "SELECT * FROM orders")
        for row in db.execute("SELECT * FROM orders ORDER BY id"):
            print(row)

        # --- 5. PRIMARY KEY auto-index (REPL-only inspect) ----------------
        # The `id INT PRIMARY KEY` constraint auto-creates a unique
        # B-tree index (`pk_users_id`).  Subsequent lookups by `id`
        # use IndexScan instead of SeqScan — visible via the
        # EXPLAIN-style index entry the catalog exposes.
        _banner(5, "Auto-index on PRIMARY KEY (users.id)")
        idx_names = db.catalog.list_indexes()
        print("indexes:", idx_names)

        # --- 6. SELECT WHERE on the indexed column ------------------------
        _banner(6, "SELECT * FROM users WHERE id = 3  (uses IndexScan)")
        for row in db.execute("SELECT * FROM users WHERE id = 3"):
            print(row)

        # --- 7. UPDATE age on a row ---------------------------------------
        _banner(7, "UPDATE users SET age = 31 WHERE id = 1")
        db.execute("UPDATE users SET age = 31 WHERE id = 1")
        for row in db.execute("SELECT * FROM users WHERE id = 1"):
            print(row)

        # --- 8. Aggregate: COUNT, AVG per group ---------------------------
        _banner(8, "Aggregate — COUNT users + AVG age")
        rows = db.execute("SELECT COUNT(*) FROM users")
        print("users count:", rows[0][0])

        rows = db.execute("SELECT AVG(age) FROM users")
        print("users avg age:", rows[0][0])

        # --- 9. Transaction: BEGIN / INSERT / COMMIT ----------------------
        _banner(9, "Transaction: BEGIN / INSERT / COMMIT")
        with db.transaction():
            db.execute(
                "INSERT INTO users VALUES (6, 'frank', 28)"
            )
        rows = db.execute("SELECT * FROM users WHERE name = 'frank'")
        print("after commit:", rows)

        # --- 10. Cleanup: DROP TABLE, close DB ----------------------------
        _banner(10, "Cleanup — DROP TABLE + close")
        db.execute("DROP TABLE users")
        db.execute("DROP TABLE orders")
        print("tables remaining:", db.catalog.list_tables())

        return 0
    finally:
        db.close()
        # Best-effort cleanup of the temp directory.
        try:
            for p in tmpdir.iterdir():
                try:
                    p.unlink()
                except OSError:
                    pass
            tmpdir.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())