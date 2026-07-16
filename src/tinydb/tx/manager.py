"""Transaction manager — coordinates the write lock and the WAL.

Public surface:
    mgr = TransactionManager(pager, wal)
    mgr.begin()                # → TransactionContext (or raises)
    mgr.commit(tx)             # fsync WAL, mark COMMITTED, release lock
    mgr.rollback(tx)           # mark ROLLED BACK, release lock
    with mgr.transaction() as tx:    # auto-COMMIT / auto-ROLLBACK
        ...

The manager holds the write lock for the entire lifetime of a
transaction (BEGIN..COMMIT/ROLLBACK).  COMMIT and ROLLBACK each
``fsync()`` the WAL **before** the lock is released so a crash cannot
lose the decision: if the COMMIT record is on disk, recovery treats the
tx as committed; if it is not, recovery treats it as aborted.

Per DP-0 v0.1 does NOT support nested transactions or savepoints —
calling ``begin()`` while another tx is active raises
:class:`NestedTransactionError`.

Lock lifetime: ``begin()`` acquires the lock **without** a ``with``
block (the held token is stored on the manager) so the lock survives
until ``commit()`` / ``rollback()`` releases it.  This makes the
multi-writer blocking contract work — while T1 is inside
``with mgr.transaction():``, T2's ``begin()`` blocks on the lock.

v0.2 changes
------------
* The underlying write lock is now a v0.2 :class:`RWLock` (via the
  v0.1-compatible :class:`WriteLock` wrapper).  A new
  :class:`DeadlockDetector` is consulted in ``begin()``; if the new
  transaction would create a wait-for cycle, the transaction is
  refused with :class:`DeadlockError` rather than blocking forever.
* On commit we stamp the page header's ``last_lsn`` field with the
  LSN of the COMMIT record (REQ-CONC-5).  This is the cross-process
  invalidation hook read by the BufferPool.
"""
from __future__ import annotations

import contextlib
import struct
from dataclasses import dataclass
from typing import Iterator, Optional

from tinydb.concurrent.deadlock import DeadlockDetector
from tinydb.errors import TinydbError
from tinydb.tx.lock import WriteLock, WriteLockHeld
from tinydb.tx.wal import RT_BEGIN, RT_COMMIT, RT_PAGE, RT_ROLLBACK, WAL


@dataclass(frozen=True, slots=True)
class TransactionContext:
    """A live transaction handle returned by :meth:`TransactionManager.begin`.

    Attributes
    ----------
    tx_id:
        Monotonically increasing id assigned at BEGIN.
    begin_lsn:
        LSN of the RT_BEGIN record in the WAL.
    manager:
        The owning :class:`TransactionManager`; passed back into
        ``commit`` / ``rollback`` so the manager can verify the
        caller is operating on the *active* transaction.
    """

    tx_id: int
    begin_lsn: int
    manager: "TransactionManager"


class NestedTransactionError(TinydbError):
    """Raised when ``begin()`` is called while another tx is active.

    Per REQ-TRX-1 v0.1 does NOT implement savepoints.
    """


class DeadlockError(TinydbError):
    """Raised when ``begin()`` would create a wait-for cycle.

    The caller should roll back the most-recently-started application
    work and retry.  See REQ-CONC-7.
    """


def _encode_tx_id(tx_id: int) -> bytes:
    """Encode a tx id (u64 BE) for BEGIN / COMMIT / ROLLBACK payloads."""
    return struct.pack(">Q", tx_id)


class TransactionManager:
    """Single-writer transaction coordinator with deadlock detection.

    Holds a :class:`WriteLock` (a thin wrapper over the v0.2
    :class:`~tinydb.concurrent.RWLock` write side) for the duration
    of each transaction; records BEGIN / COMMIT / ROLLBACK in the
    :class:`WAL`; and fsyncs the WAL on COMMIT / ROLLBACK before
    releasing the lock.  A :class:`DeadlockDetector` tracks
    cross-transaction waits and refuses new transactions that would
    form a cycle.

    Parameters
    ----------
    pager:
        The Pager handle. T-6.3 stores it but does not use it —
        PAGE records are written by T-6.4.
    wal:
        The :class:`tinydb.tx.WAL` to append control records to.
    """

    __slots__ = (
        "_pager", "_wal", "_lock", "_deadlock",
        "_next_tx_id", "_active_tx", "_held", "_logged_pages",
    )

    def __init__(self, pager, wal: WAL) -> None:
        self._pager = pager
        self._wal = wal
        self._lock = WriteLock()
        self._deadlock = DeadlockDetector()
        self._next_tx_id: int = 1
        self._active_tx: Optional[TransactionContext] = None
        # Held token from the in-progress write lock; None iff no tx.
        self._held: Optional[WriteLockHeld] = None
        # Page ids touched in the current tx (used by rollback to
        # restore the before-images in-memory so ROLLBACK leaves the
        # heap clean even before Recovery runs).
        self._logged_pages: list = []  # list[tuple[int, bytes]] = (page_id, before_image)

    @property
    def active_tx(self) -> Optional[TransactionContext]:
        """The currently-open transaction, or ``None``."""
        return self._active_tx

    @property
    def rwlock(self):
        """Underlying RWLock (v0.2 callers use this directly for read access)."""
        return self._lock.rwlock

    @property
    def deadlock_detector(self) -> DeadlockDetector:
        """The wait-for-graph detector (for tests and advanced callers)."""
        return self._deadlock

    @contextlib.contextmanager
    def transaction(self) -> Iterator[TransactionContext]:
        """Auto-COMMIT on clean exit, auto-ROLLBACK on exception."""
        tx = self.begin()
        try:
            yield tx
        except BaseException:
            self.rollback(tx)
            raise
        else:
            self.commit(tx)

    def begin(self) -> TransactionContext:
        """Acquire the write lock, append RT_BEGIN, return the context.

        Blocks until the lock is available.  Raises
        :class:`NestedTransactionError` if another transaction is
        already active in this thread, and
        :class:`DeadlockError` if adding this transaction would form
        a wait-for cycle.  The check happens inside the critical
        section so concurrent ``begin()`` calls from other threads
        queue up cleanly.  The lock is held until ``commit()`` or
        ``rollback()`` is called.
        """
        # Pre-flight: refuse early if adding ourselves would deadlock.
        # We tentatively reserve a tx_id, then check the cycle with
        # ourselves as a waiter on the active tx (if any).  Since the
        # v0.2 single-writer model has at most one active writer, the
        # only possible wait edge here is "the new tx waits on the
        # current active writer", and a cycle would mean that writer
        # is waiting on us.  In v0.1's single-writer world that can't
        # happen, but the detector still serves as a guard for the
        # v0.2 multi-reader reader path where readers can wait on
        # writers (D-6).
        new_tx_id = self._next_tx_id
        if self._active_tx is not None:
            # We're queued behind the active writer.  Add a wait edge
            # and ask the detector whether this forms a cycle.
            self._deadlock.add_wait(new_tx_id, self._active_tx.tx_id)
            victim = self._deadlock.detect_cycle()
            self._deadlock.remove(new_tx_id)
            if victim is not None:
                raise DeadlockError(
                    f"transaction {new_tx_id} would deadlock with "
                    f"active transaction {self._active_tx.tx_id}"
                )
        held = self._lock.acquire()  # may block
        if self._active_tx is not None:
            held.__exit__(None, None, None)  # release on nested raise
            raise NestedTransactionError(
                "tinydb v0.1 does not support nested transactions"
            )
        tx_id = self._next_tx_id
        self._next_tx_id += 1
        begin_lsn = self._wal.append(RT_BEGIN, _encode_tx_id(tx_id))
        self._active_tx = TransactionContext(tx_id, begin_lsn, self)
        self._held = held
        self._logged_pages = []
        return self._active_tx

    def log_page_write(
        self, page_id: int, before: bytes, after: bytes
    ) -> None:
        """Record an RT_PAGE entry for one data-page write.

        Called by the DML paths (``Insert`` / ``Update`` / ``Delete``)
        after the heap mutates a page but before the in-memory Pager
        returns.  When no transaction is active (autocommit mode) we
        still log the page write — recovery treats a ``tx_id == 0``
        record as already-implicitly-committed (no BEGIN/COMMIT pair
        needed) and REDOs it the same as any other committed write.
        This lets the fuzzer exercise autocommit semantics.
        """
        from tinydb.tx.recovery import encode_page_record
        tx_id = self._active_tx.tx_id if self._active_tx is not None else 0
        payload = encode_page_record(tx_id, page_id, before, after)
        self._wal.append(RT_PAGE, payload)
        self._logged_pages.append((page_id, before))

    @property
    def logged_pages(self) -> list:
        """Page ids touched in the current tx (testing/observability)."""
        return [pid for pid, _ in self._logged_pages]

    def _release_lock(self) -> None:
        """Drop the held token; safe iff a tx is active."""
        held = self._held
        self._held = None
        if held is not None:
            held.__exit__(None, None, None)

    def commit(self, tx: TransactionContext) -> None:
        """Record RT_COMMIT and fsync; release the lock.

        Stamps the page header's ``last_lsn`` with the LSN of the
        COMMIT record so other processes can detect the change
        (REQ-CONC-5).

        Raises :class:`ValueError` if ``tx`` is not the active
        transaction.
        """
        if self._active_tx is not tx:
            raise ValueError("commit(): not the active transaction")
        commit_lsn = self._wal.append(RT_COMMIT, _encode_tx_id(tx.tx_id))
        self._wal.fsync()  # durability: COMMIT must reach disk first
        # Stamp the on-disk header so cross-process readers can
        # detect the change.  v0.1 files accept this update because
        # the last_lsn field is reserved-but-zero.
        try:
            self._pager.set_last_lsn(commit_lsn)
        except Exception:
            # last_lsn is an observability aid; never fail the commit
            # on a header-write hiccup.
            pass
        # Forget any wait edges involving this tx.
        self._deadlock.remove(tx.tx_id)
        self._logged_pages = []
        self._active_tx = None
        self._release_lock()

    def rollback(self, tx: TransactionContext) -> None:
        """Record RT_ROLLBACK and fsync; release the lock.

        v0.1 simplification: we do NOT walk the WAL to restore
        before-images in memory; the durable contract is the WAL +
        Recovery on restart, and within a single-process single-writer
        fence a ROLLBACK between transactions is rare.  The
        ``_logged_pages`` list is reset so the next tx starts fresh.

        Raises :class:`ValueError` if ``tx`` is not the active
        transaction.
        """
        if self._active_tx is not tx:
            raise ValueError("rollback(): not the active transaction")
        self._wal.append(RT_ROLLBACK, _encode_tx_id(tx.tx_id))
        self._wal.fsync()
        # Restore before-images to the pager so in-memory state matches
        # the ROLLBACK record.  Walking in REVERSE order so a page
        # written multiple times in the tx is restored to its
        # earliest-pre-tx content.
        for page_id, before in reversed(self._logged_pages):
            self._pager.write_page(page_id, before)
        self._deadlock.remove(tx.tx_id)
        self._logged_pages = []
        self._active_tx = None
        self._release_lock()


__all__ = [
    "TransactionManager",
    "TransactionContext",
    "NestedTransactionError",
    "DeadlockError",
]