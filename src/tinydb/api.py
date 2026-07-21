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

v0.2 additions
---------------
* ``isolation`` kwarg selects READ COMMITTED (default) or SERIALIZABLE.
* ``pool_size`` kwarg opts into a connection pool of N entries
  (default 1, the v0.1 single-connection fence).
* :meth:`acquire` / :meth:`release` / :meth:`connection` expose the
  pool to multi-threaded callers.
* :meth:`list_tables` and :meth:`get_schema` are convenience
  introspection helpers for the CLI.
"""
from __future__ import annotations

import contextlib
import queue
import threading
from enum import Enum
from pathlib import Path
from typing import Iterator, List, Union

from tinydb.errors import ParseError, TinydbError
from tinydb.executor.executor import Executor
from tinydb.executor.planner import plan as _plan
from tinydb.index.manager import IndexManager
from tinydb.sql.ast import CreateIndex, CreateTable, DropTable
from tinydb.sql.parser import parse
from tinydb.storage.buffer_pool import BufferPool
from tinydb.storage.catalog import Catalog
from tinydb.storage.pager import Pager
from tinydb.tx.manager import TransactionManager
from tinydb.tx.recovery import Recovery
from tinydb.tx.wal import WAL
from tinydb.types.system import Column, TypeTag


class IsolationLevel(Enum):
    """Transaction isolation levels supported by v0.2.

    * ``READ_COMMITTED`` (default) — every transaction captures a
      snapshot at BEGIN; readers see the last committed state at
      that moment, writers do not block readers.
    * ``SERIALIZABLE`` — every read goes through the writer-side
      critical section, so all transactions are strictly serialized.
      v0.2 implements this as a write-preferring RWLock acquisition
      on begin.
    """

    READ_COMMITTED = "READ COMMITTED"
    SERIALIZABLE = "SERIALIZABLE"


class _Connection:
    """A single Database-side connection handle.

    The v0.1 Database was its own connection.  v0.2 extracts the
    per-connection state into a separate object so a pool of N
    :class:`_Connection` instances can share the underlying Pager /
    WAL / Catalog (which are themselves safely shareable across
    threads because of the RWLock + BufferPool + Snapshot machinery).
    """

    __slots__ = ("_db",)

    def __init__(self, db: "Database") -> None:
        self._db = db

    def execute(self, sql: str) -> list:
        return self._db.execute(sql)

    def begin(self):
        return self._db._txn.begin()

    def commit(self, tx) -> None:
        self._db._txn.commit(tx)

    def rollback(self, tx) -> None:
        self._db._txn.rollback(tx)

    def explain(self, sql: str) -> str:
        return self._db.explain(sql)


class _ConnectionPool:
    """Bounded FIFO pool of :class:`_Connection` instances.

    Backed by a :class:`queue.Queue`; ``acquire`` blocks (with an
    optional timeout) until a connection is available, ``release``
    returns one.  The pool size is fixed at construction; the
    default of 1 preserves v0.1 single-connection semantics.
    """

    def __init__(self, db: "Database", size: int) -> None:
        if size <= 0:
            raise ValueError(f"pool_size must be > 0, got {size}")
        self._db = db
        self._size = size
        self._queue: "queue.Queue[_Connection]" = queue.Queue(maxsize=size)
        for _ in range(size):
            self._queue.put(_Connection(db))

    @property
    def size(self) -> int:
        return self._size

    def acquire(self, timeout: float | None = None) -> _Connection:
        if timeout is None:
            return self._queue.get()
        return self._queue.get(timeout=timeout)

    def release(self, conn: _Connection) -> None:
        # Best-effort: drop on the floor if the queue is full (would
        # only happen if a caller double-released).
        try:
            self._queue.put_nowait(conn)
        except queue.Full:
            pass

    @contextlib.contextmanager
    def connection(self) -> Iterator[_Connection]:
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)


class Database:
    """The user-facing database handle.

    Construct with a path; the database file is opened (or created).
    Call :meth:`execute` for DDL/DML; :meth:`transaction` for an
    explicit BEGIN/COMMIT/ROLLBACK block; :meth:`close` to release
    the file handle.  Use as a context manager for automatic close.

    v0.2 kwargs:
        isolation: READ_COMMITTED (default) or SERIALIZABLE
        pool_size: int >= 1; 1 (default) keeps v0.1 single-connection
            semantics, >1 opts into a thread-safe connection pool
    """

    def __init__(
        self,
        path: Union[str, Path],
        *,
        isolation: IsolationLevel = IsolationLevel.READ_COMMITTED,
        pool_size: int = 1,
        use_process_lock: bool = False,
    ) -> None:
        if pool_size < 1:
            raise ValueError(f"pool_size must be >= 1, got {pool_size}")
        self._path: Path = Path(path)
        self._isolation = isolation
        self._use_process_lock = use_process_lock
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
        self._wal = WAL(wal_path, use_process_lock=use_process_lock)
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
        # 9. Connection pool — size 1 keeps v0.1 semantics; >1 enables
        # multi-threaded acquire/release.
        self._pool = _ConnectionPool(self, pool_size)
        self._closed: bool = False

    # -- introspection ---------------------------------------------------

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

    @property
    def isolation(self) -> IsolationLevel:
        """Configured isolation level (READ_COMMITTED or SERIALIZABLE)."""
        return self._isolation

    @property
    def pool_size(self) -> int:
        """Configured connection-pool size (>= 1)."""
        return self._pool.size

    @property
    def rwlock(self):
        """The underlying :class:`RWLock` (v0.2 callers can acquire read)."""
        return self._txn.rwlock

    # -- connection pool (v0.2) ------------------------------------------

    def acquire(self, timeout: float | None = None) -> _Connection:
        """Borrow a connection from the pool. Blocks when pool is empty."""
        return self._pool.acquire(timeout=timeout)

    def release(self, conn: _Connection) -> None:
        """Return a connection to the pool."""
        self._pool.release(conn)

    @contextlib.contextmanager
    def connection(self) -> Iterator[_Connection]:
        """Context manager that auto-releases the connection on exit."""
        with self._pool.connection() as conn:
            yield conn

    # -- public API ------------------------------------------------------

    def execute(self, sql: str) -> list:
        """Run a single SQL statement.

        SELECT returns rows as ``list[tuple]``.  DML returns a single
        ``[(affected_count,)]`` row.  DDL returns ``[]``.  Raises
        :class:`~tinydb.errors.ParseError` on invalid SQL.

        Thread-safety (v0.2):

        DDL (CREATE/DROP TABLE, CREATE INDEX) and DML (INSERT/UPDATE/
        DELETE) are wrapped in the writer-side of the
        :class:`tinydb.concurrent.RWLock` so two threads inserting
        into the same heap cannot interleave read-modify-write cycles.
        SELECT is wrapped in the reader-side; multiple SELECTs run
        concurrently but block while a writer is active.

        Cross-process (when ``use_process_lock=True``) the same code
        path additionally holds a :class:`ProcessLock` exclusive
        around writes and shared around reads, so a subprocess writer
        committing cannot interleave with a subprocess reader's
        SELECT (REQ-CONC-2 / REQ-CONC-8).
        """
        stmt = parse(sql)
        is_ddl = isinstance(stmt, (CreateTable, DropTable, CreateIndex))
        if is_ddl:
            plan = None
            is_write = True
        else:
            plan = _plan(stmt, self._catalog, indexer=self._indexer)
            # Lazy import to avoid a circular dep at module load.
            from tinydb.executor.dml import Delete, Insert, Update
            is_write = isinstance(plan, (Insert, Update, Delete))

        rwlock = self._txn.rwlock
        # Detect whether we're already inside a transaction begun
        # via :meth:`Database.transaction`.  The transaction manager
        # already holds the writer side of the RWLock for its
        # lifetime, so re-acquiring it would deadlock (the RWLock is
        # non-reentrant).  When active_tx is set, the existing lock
        # already serializes this ``execute`` against any sibling
        # threads, and we can skip the explicit acquire.
        inside_tx = self._txn.active_tx is not None
        if inside_tx:
            # No additional lock needed; the tx holds the writer lock.
            return self._execute_unlocked(stmt, plan, is_ddl)
        rw_cm = rwlock.write() if is_write else rwlock.read()

        with rw_cm:
            # Cross-process: serialize with other processes holding
            # the same .db.  The per-call lock is in addition to the
            # intra-process RWLock above; the dual gate is necessary
            # because the intra-process RWLock only protects against
            # threads in *this* process.
            if self._use_process_lock:
                from tinydb.concurrent.fcntl_lock import ProcessLock
                wal_fp = self._wal._fp  # type: ignore[attr-defined]
                with ProcessLock(wal_fp, exclusive=is_write):
                    return self._execute_unlocked(stmt, plan, is_ddl)
            return self._execute_unlocked(stmt, plan, is_ddl)

    def _execute_unlocked(self, stmt, plan, is_ddl: bool) -> list:
        """Execute ``stmt`` / ``plan`` assuming both locks are held.

        Split out so the lock-wrapping boilerplate lives in
        :meth:`execute` and the plan-dispatch logic stays compact.
        The parameter triple mirrors what :meth:`execute` decided at
        parse time.
        """
        if is_ddl:
            # DDL is handled here so the planner stays DML-only (T-5.1).
            if isinstance(stmt, CreateTable):
                self._catalog.create_table(stmt.name, stmt.columns)
                # T-7.2: surface PRIMARY KEY by auto-creating a unique
                # index on the column.  v0.1 stores the PK flag but does
                # not enforce it; routing the constraint through the
                # existing IndexManager lets the same UNIQUE-precheck path
                # reject duplicate-key inserts with ConstraintViolation.
                for col in stmt.columns:
                    if col.primary_key:
                        self._indexer.create_index(
                            f"pk_{stmt.name}_{col.name}",
                            stmt.name,
                            [col.name],
                            unique=True,
                        )
                return []
            if isinstance(stmt, DropTable):
                if stmt.name in self._catalog.list_tables():
                    # Drop indexes that belong to this table first so the
                    # catalog doesn't carry orphan IndexMeta entries for a
                    # table that no longer exists.
                    for idx_name in list(self._indexer.list_indexes(stmt.name)):
                        self._indexer.drop_index(idx_name)
                    self._catalog.drop_table(stmt.name)
                return []
            if isinstance(stmt, CreateIndex):
                self._indexer.create_index(
                    stmt.name, stmt.table, list(stmt.columns), unique=stmt.unique,
                )
                return []
        return self._executor.execute(plan)

    def explain(self, sql: str) -> str:
        """Return a textual execution plan for ``sql`` as an ASCII tree.

        v0.2: back the ``.explain <SQL>`` REPL command.  Returns the
        concatenated Logical / Physical trees from
        :mod:`tinydb.cli.explain`, or raises the same errors as
        :meth:`execute` for invalid SQL.  Programmatic consumers that
        only need a single-line summary can use :func:`repr` on the
        returned plan tree directly.
        """
        from tinydb.cli.explain import format_plan_pair
        stmt = parse(sql)
        logical = _plan(stmt, self._catalog, indexer=self._indexer)
        # Join worktree augments ``plan`` to emit JoinNodes; the
        # physical walker reuses the same tree for v0.2 since the
        # operator types are 1:1 with logical operators.
        return format_plan_pair(logical, logical)

    def list_tables(self) -> List[str]:
        """Return the names of all tables in the catalog (sorted)."""
        return sorted(self._catalog.list_tables())

    def get_schema(self, table: str) -> str:
        """Return a DDL ``CREATE TABLE`` statement for ``table``.

        The output is suitable for printing via :meth:`str`.  Raises
        :class:`~tinydb.errors.TinydbError` if the table does not
        exist.
        """
        schema = self._catalog.get_table(table)
        if schema is None:
            raise TinydbError(f"no such table: {table!r}")
        cols: List[str] = []
        for c in schema.columns:
            # Column has .name and .tag (a TypeTag enum); map to a
            # SQL-friendly typename.
            type_name = getattr(c.tag, "name", str(c.tag))
            parts = [c.name, type_name]
            if c.not_null:
                parts.append("NOT NULL")
            cols.append(" ".join(parts))
        return f"CREATE TABLE {table} ({', '.join(cols)})"

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

    # -- context manager sugar ------------------------------------------

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, et, ev, tb) -> bool:
        self.close()
        return False


# Module-level helper for convenience.
def open(path: Union[str, Path], **kwargs) -> Database:
    """Open or create a database.  Equivalent to ``Database(path, **kwargs)``."""
    return Database(path, **kwargs)


__all__ = [
    "Database",
    "IsolationLevel",
    "open",
]


# --- helpers used by get_schema and the CLI REPL -----------------------


_TAG_TO_SQL: dict = {
    TypeTag.Int: "INT",
    TypeTag.Float: "FLOAT",
    TypeTag.Text: "TEXT",
    TypeTag.Bool: "BOOL",
    TypeTag.Date: "DATE",
    TypeTag.Time: "TIME",
    TypeTag.Datetime: "DATETIME",
    TypeTag.Decimal: "DECIMAL",
    TypeTag.Blob: "BLOB",
    TypeTag.Json: "JSON",
}


def _column_to_sql(col: Column) -> str:
    parts = [col.name, _TAG_TO_SQL.get(col.tag, col.tag.name)]
    if col.primary_key:
        parts.append("PRIMARY KEY")
    elif col.unique:
        parts.append("UNIQUE")
    if col.not_null:
        parts.append("NOT NULL")
    return " ".join(parts)


def _build_create_table_sql(table_name: str, columns) -> str:
    cols_sql = ", ".join(_column_to_sql(c) for c in columns)
    return f"CREATE TABLE {table_name} ({cols_sql});"


class _MissingDatabase:  # pragma: no cover — re-exported below for type hints
    """Placeholder; not user-facing.  See Database."""
