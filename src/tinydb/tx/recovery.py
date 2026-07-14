"""Crash recovery — replay WAL on startup.

Three phases
------------
1. ANALYSIS: scan the WAL once, partition PAGE records by (tx_id, page_id)
   and remember the *latest* before/after images per page.  Track the
   commit state of each tx id: ``COMMITTED`` (saw ``RT_COMMIT``),
   ``ROLLED_BACK`` (saw ``RT_ROLLBACK``), or ``UNKNOWN`` (saw ``RT_BEGIN``
   but no terminal record).  UNKNOWN tx's are treated as aborted — that
   is the ARIES rule for "tx began but never reached a decision".

2. REDO: for each page that was touched by a COMMITTED tx, apply the
   latest after-image of that page.  Pages touched only by UNKNOWN or
   ROLLED_BACK tx's are skipped.

3. UNDO: for each page touched by an UNKNOWN tx, apply the latest
   before-image.  If a page was touched by both a committed and an
   uncommitted tx, REDO wins (committed-after overrides before-image),
   which is the correct ARIES-style outcome.

This is a v0.1 simplification: no LSN-per-page tracking, no
Compensation Log Records (CLRs), no fuzzy checkpoint support.  T-6.7
adds checkpointing; T-6.6 just proves the gate — durability +
atomicity + consistency across crashes — with the smallest viable
log shape (whole-page before/after images).

Recovery is idempotent: running :meth:`replay` twice in a row leaves
the database in the same state as a single :meth:`replay`.
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tinydb.storage.pager import PAGE_SIZE, Pager
from tinydb.tx.wal import (
    RT_BEGIN,
    RT_COMMIT,
    RT_PAGE,
    RT_ROLLBACK,
    WAL,
)

log = logging.getLogger(__name__)


# --- RT_PAGE payload layout ---------------------------------------------
#
# u64 BE tx_id
# u32 BE page_id
# u32 BE before_len      (must equal PAGE_SIZE)
# u32 BE after_len       (must equal PAGE_SIZE)
# before_bytes (PAGE_SIZE bytes)
# after_bytes  (PAGE_SIZE bytes)
#
# Both images are full PAGE_SIZE (4 KB) so we can ``pager.write_page``
# the result directly without any allocation.  Whole-page logging is
# intentionally wasteful — T-6.7 / v0.2 introduce finer-grained
# records.

_PAGE_RECORD_FMT = ">QIII"
_PAGE_RECORD_HEADER = struct.calcsize(_PAGE_RECORD_FMT)  # 20 bytes


class PageRecordDecodeError(Exception):
    """Raised when an RT_PAGE frame is malformed."""


@dataclass
class _PageTouch:
    """One PAGE record's contribution to a single (tx_id, page_id) slot."""

    tx_id: int
    page_id: int
    before: bytes
    after: bytes


@dataclass
class _RecoveryStats:
    """Counters surfaced to the caller via :meth:`Recovery.replay`."""

    records_scanned: int = 0
    page_records: int = 0
    redo: int = 0
    undo: int = 0
    committed: List[int] = field(default_factory=list)
    uncommitted: List[int] = field(default_factory=list)


def _decode_page_record(payload: bytes) -> _PageTouch:
    """Parse an RT_PAGE payload into ``_PageTouch``.

    Raises :class:`PageRecordDecodeError` on a malformed frame so the
    recovery loop can stop cleanly rather than corrupt the page table.
    """
    if len(payload) < _PAGE_RECORD_HEADER:
        raise PageRecordDecodeError(
            f"RT_PAGE payload too short: {len(payload)} bytes"
        )
    tx_id, page_id, before_len, after_len = struct.unpack(
        _PAGE_RECORD_FMT, payload[:_PAGE_RECORD_HEADER]
    )
    expected_total = _PAGE_RECORD_HEADER + before_len + after_len
    if expected_total != len(payload):
        raise PageRecordDecodeError(
            f"RT_PAGE length mismatch: header says {expected_total}, "
            f"got {len(payload)}"
        )
    if before_len != PAGE_SIZE or after_len != PAGE_SIZE:
        raise PageRecordDecodeError(
            f"RT_PAGE image sizes must be {PAGE_SIZE}, "
            f"got before={before_len} after={after_len}"
        )
    before = bytes(payload[
        _PAGE_RECORD_HEADER : _PAGE_RECORD_HEADER + before_len
    ])
    after = bytes(payload[
        _PAGE_RECORD_HEADER + before_len :
        _PAGE_RECORD_HEADER + before_len + after_len
    ])
    return _PageTouch(tx_id=tx_id, page_id=page_id, before=before, after=after)


def _encode_page_record(
    tx_id: int, page_id: int, before: bytes, after: bytes
) -> bytes:
    """Pack an RT_PAGE payload (used by the manager when logging writes)."""
    if len(before) != PAGE_SIZE or len(after) != PAGE_SIZE:
        raise ValueError(
            f"page images must be {PAGE_SIZE} bytes, "
            f"got before={len(before)} after={len(after)}"
        )
    return (
        struct.pack(_PAGE_RECORD_FMT, tx_id, page_id, PAGE_SIZE, PAGE_SIZE)
        + before
        + after
    )


class Recovery:
    """Crash-recovery facade.

    Constructed with the :class:`WAL` and :class:`Pager` of the database
    being recovered.  The caller is responsible for *closing* both
    handles (this class does not own their lifetime).

    The three phases run inside :meth:`replay`; the public method
    returns a small statistics dict so callers (tests, the upcoming
    T-6.7 checkpoint) can observe what happened.
    """

    __slots__ = ("_wal", "_pager")

    def __init__(self, wal: WAL, pager: Pager) -> None:
        self._wal = wal
        self._pager = pager

    def replay(self) -> dict:
        """Run ANALYSIS + REDO + UNDO and return stats.

        Returns ``{records_scanned, page_records, redo, undo, committed,
        uncommitted}``.  The committed / uncommitted lists are the tx
        ids Recovery saw in the log (committed = ``RT_COMMIT`` seen;
        uncommitted = ``RT_BEGIN`` without a matching ``RT_COMMIT`` /
        ``RT_ROLLBACK``).
        """
        stats = _RecoveryStats()
        # ---- ANALYSIS ---------------------------------------------------
        # Map (tx_id, page_id) -> _PageTouch (later writes win).
        page_touches: Dict[Tuple[int, int], _PageTouch] = {}
        # Map page_id -> set of tx_ids that touched it (preserves the
        # last-writer-wins image so we can pick before/after correctly
        # in REDO/UNDO even when a single page was touched by several
        # tx's).
        page_last_writer: Dict[int, Tuple[int, bytes, bytes]] = {}
        # tx_id -> "COMMITTED" | "ROLLED_BACK" | "UNKNOWN"
        tx_state: Dict[int, str] = {}

        for record in self._wal.iter_from(1):
            stats.records_scanned += 1
            if record.type == RT_BEGIN:
                # Payload is the tx id (u64 BE).
                (tx_id,) = struct.unpack(">Q", record.payload)
                tx_state.setdefault(tx_id, "UNKNOWN")
            elif record.type == RT_COMMIT:
                (tx_id,) = struct.unpack(">Q", record.payload)
                tx_state[tx_id] = "COMMITTED"
            elif record.type == RT_ROLLBACK:
                (tx_id,) = struct.unpack(">Q", record.payload)
                tx_state[tx_id] = "ROLLED_BACK"
            elif record.type == RT_PAGE:
                stats.page_records += 1
                touch = _decode_page_record(record.payload)
                page_touches[(touch.tx_id, touch.page_id)] = touch
                page_last_writer[touch.page_id] = (
                    touch.tx_id, touch.before, touch.after
                )
            # Unknown types are ignored (forward compatibility).

        committed = sorted(
            tx for tx, st in tx_state.items() if st == "COMMITTED"
        )
        uncommitted = sorted(
            tx for tx, st in tx_state.items() if st == "UNKNOWN"
        )
        stats.committed = committed
        stats.uncommitted = uncommitted

        # ---- REDO / UNDO -----------------------------------------------
        # Walk per (tx_id, page_id) touches.  Whole-page images are
        # stored for each PAGE record, so "latest write by a COMMITTED
        # tx" wins for REDO and "earliest write by an UNKNOWN tx" wins
        # for UNDO before any committed write landed.
        #
        # Track per-page:
        #   committed_after[page_id]  -> latest after-image by any committed tx
        #   unknown_before[page_id]   -> earliest before-image by any uncommitted tx
        #                                (this is the pre-tx state; REDO wins if
        #                                committed_after exists)
        committed_after: Dict[int, bytes] = {}
        unknown_before: Dict[int, bytes] = {}
        for (tx_id, page_id), touch in page_touches.items():
            state = tx_state.get(tx_id, "UNKNOWN")
            if state == "COMMITTED" or tx_id == 0:
                # tx_id 0 is the AUTOCOMMIT sentinel: the manager logged
                # a page write without an explicit BEGIN/COMMIT pair
                # (T-6.6 fuzzy-test convenience).  Treat as already
                # committed — REDO the after-image.
                committed_after[page_id] = touch.after
                committed_after[page_id] = touch.after
            else:
                # First-seen uncommitted write wins (so we capture the
                # original pre-tx state, not some intermediate).
                unknown_before.setdefault(page_id, touch.before)

        # REDO phase: every page with a committed after-image gets it.
        for page_id, after in sorted(committed_after.items()):
            self._pager.write_page(page_id, after)
            stats.redo += 1

        # UNDO phase: pages never touched by a committed tx get the
        # latest uncommitted before-image restored.  This is what makes
        # ``INSERT (committed) + UPDATE (crashed) → INSERT survives``
        # work: the UPDATE's before-image is NOT applied because the
        # page already had a committed after-image.
        for page_id, before in sorted(unknown_before.items()):
            if page_id in committed_after:
                continue  # REDO already wrote the committed state
            self._pager.write_page(page_id, before)
            stats.undo += 1

        return {
            "records_scanned": stats.records_scanned,
            "page_records": stats.page_records,
            "redo": stats.redo,
            "undo": stats.undo,
            "committed": list(stats.committed),
            "uncommitted": list(stats.uncommitted),
        }


# Re-export the encoder so the manager can log without re-deriving the
# format.
encode_page_record = _encode_page_record


__all__ = ["Recovery", "PageRecordDecodeError", "encode_page_record"]