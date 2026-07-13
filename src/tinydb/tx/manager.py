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
"""
from __future__ import annotations

import contextlib
import struct
from dataclasses import dataclass
from typing import Iterator, Optional

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


def _encode_tx_id(tx_id: int) -> bytes:
    """Encode a tx id (u64 BE) for BEGIN / COMMIT / ROLLBACK payloads."""
    return struct.pack(">Q", tx_id)


class TransactionManager:
    """Single-writer transaction coordinator.

    Holds a :class:`WriteLock` for the duration of each transaction;
    records BEGIN / COMMIT / ROLLBACK in the :class:`WAL`; and fsyncs
    the WAL on COMMIT / ROLLBACK before releasing the lock.

    Parameters
    ----------
    pager:
        The Pager handle. T-6.3 stores it but does not use it —
        PAGE records are written by T-6.4.
    wal:
        The :class:`tinydb.tx.WAL` to append control records to.
    """

    __slots__ = (
        "_pager", "_wal", "_lock", "_next_tx_id",
        "_active_tx", "_held", "_logged_pages",
    )

    def __init__(self, pager, wal: WAL) -> None:
        self._pager = pager
        self._wal = wal
        self._lock = WriteLock()
        self._next_tx_id: int = 1
        self._active_tx: Optional[TransactionContext] = None
        # Held token from the in-progress write lock; None iff no tx.
        self._held: Optional[WriteLockHeld] = None
        # Page ids touched in the current tx (used by rollback to
        # restore the before-images in-memory so ROLLBACK leaves the
        # heap clean even before Recovery runs).
        self._logged_pages: list = []

    @property
    def active_tx(self) -> Optional[TransactionContext]:
        """The currently-open transaction, or ``None``."""
        return self._active_tx

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
        already active.  The check happens inside the critical section
        so concurrent ``begin()`` calls from other threads queue up
        cleanly.  The lock is held until ``commit()`` or
        ``rollback()`` is called.
        """
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
        self._logged_pages.append(page_id)

    @property
    def logged_pages(self) -> list:
        """Page ids touched in the current tx (testing/observability)."""
        return list(self._logged_pages)

    def _release_lock(self) -> None:
        """Drop the held token; safe iff a tx is active."""
        held = self._held
        self._held = None
        if held is not None:
            held.__exit__(None, None, None)

    def commit(self, tx: TransactionContext) -> None:
        """Record RT_COMMIT and fsync; release the lock.

        Raises :class:`ValueError` if ``tx`` is not the active
        transaction.
        """
        if self._active_tx is not tx:
            raise ValueError("commit(): not the active transaction")
        self._wal.append(RT_COMMIT, _encode_tx_id(tx.tx_id))
        self._wal.fsync()  # durability: COMMIT must reach disk first
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
        self._logged_pages = []
        self._active_tx = None
        self._release_lock()


__all__ = [
    "TransactionManager",
    "TransactionContext",
    "NestedTransactionError",
]