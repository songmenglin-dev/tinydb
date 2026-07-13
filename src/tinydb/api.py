"""High-level Database facade.

This is the only public entry point a user of tinydb needs to know.
Hides the lower-level modules (Pager, BufferPool, Catalog, IndexManager,
WAL, TransactionManager, Executor) behind a small, ergonomic surface.

Usage:
    with tinydb.open("/tmp/test.db") as db:
        db.execute("CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)")
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        rows = db.execute("SELECT * FROM users WHERE id = 1")
        # rows == [(1, 'alice')]
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Iterator, Union

from tinydb.errors import ParseError
from tinydb.executor.executor import Executor
from tinydb.executor.planner import plan as _plan
from tinydb.index.manager import IndexManager
from tinydb.sql.ast import CreateTable, DropTable
from tinydb.sql.parser import parse
from tinydb.storage.buffer_pool import BufferPool
from tinydb.storage.catalog import Catalog
from tinydb.storage.pager import Pager
from tinydb.tx.manager import TransactionManager
from tinydb.tx.recovery import Recovery
from tinydb.tx.wal import WAL


class Database:
    """The user-facing database handle.

    Construct with a path; the database file is opened (or created).
    Call :meth:`execute` for DDL/DML; :meth:`transaction` for an
    explicit BEGIN/COMMIT/ROLLBACK block; :meth:`close` to release
    the file handle.  Use as a context manager for automatic close.
    """

    def __init__(self, path: Union[str, Path]) -> None:
        self._path: Path = Path(path)
        # 1. Pager — opens the .db file or creates it.
        self._pager = Pager.open(self._path)
        # 2. BufferPool — LRU cache in front of the Pager.
        self._buffer = BufferPool(self._pager)
        # 3. Catalog — loads schemas + indexes from reserved pages 1-2.
        self._catalog = Catalog(self._pager)
        # 4. WAL — open or create alongside the database.
        wal_path = self._path.with_suffix(self._path.suffix + ".wal")
        if not wal_path.exists():
            # Touch an empty WAL so the first open works without r+b
            # issues on a non-existent file.
            wal_path.write_bytes(b"")
        self._wal = WAL(wal_path)
        # 5. Recovery — run before any in-process use.
        Recovery(self._wal, self._pager).replay()
        # 6. IndexManager — load B-trees rooted in reserved pages.
        self._indexer = IndexManager(self._catalog, self._pager)
        # 7. TransactionManager — single-writer tx coordinator.
        self._txn = TransactionManager(self._pager, self._wal)
        # 8. Executor — drives Plan trees against the catalog.
        self._executor = Executor(
            catalog=self._catalog,
            pager=self._pager,
            indexer=self._indexer,
            mgr=self._txn,
        )
        self._closed: bool = False

    # -- introspection (brief T-7.1 NIT-3 / NIT-10 surfaces) -----------

    @property
    def pager(self) -> Pager:
        """Public handle to the underlying :class:`Pager`."""
        return self._pager

    @property
    def catalog(self) -> Catalog:
        """Public handle to the live :class:`Catalog`."""
        return self._catalog

    @property
    def executor(self) -> Executor:
        """Public handle to the live :class:`Executor`."""
        return self._executor

    # -- public API ----------------------------------------------------

    def execute(self, sql: str) -> list:
        """Run a single SQL statement.

        SELECT returns rows as ``list[tuple]``.  DML returns a single
        ``[(affected_count,)]`` row.  DDL returns ``[]``.  Raises
        :class:`~tinydb.errors.ParseError` on invalid SQL.
        """
        stmt = parse(sql)
        # DDL is handled here so the planner stays DML-only (T-5.1).
        if isinstance(stmt, CreateTable):
            self._catalog.create_table(stmt.name, stmt.columns)
            return []
        if isinstance(stmt, DropTable):
            if stmt.name in self._catalog.list_tables():
                self._catalog.drop_table(stmt.name)
            return []
        plan = _plan(stmt, self._catalog, indexer=self._indexer)
        return self._executor.execute(plan)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[object]:
        """Run a BEGIN/COMMIT/ROLLBACK block.

        Auto-COMMIT on clean exit; auto-ROLLBACK on exception.
        """
        with self._txn.transaction() as tx:
            yield tx

    def close(self) -> None:
        """Close the WAL and Pager.  Idempotent."""
        if self._closed:
            return
        try:
            self._wal.close()
        except Exception:
            pass
        try:
            self._pager.close()
        except Exception:
            pass
        self._closed = True

    # -- context manager sugar ----------------------------------------

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, et, ev, tb) -> bool:
        self.close()
        return False


# Module-level helper for convenience.
def open(path: Union[str, Path]) -> Database:
    """Open or create a database.  Equivalent to ``Database(path)``."""
    return Database(path)


__all__ = ["Database", "open"]
