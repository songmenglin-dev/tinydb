"""READ COMMITTED snapshots via WAL LSN.

v0.2 implements read-snapshot isolation by stamping the page header
with the LSN of the WAL frame that last modified the page, and
recording a snapshot LSN on every transaction's begin.  A page is
"visible" to a transaction iff its last-modified LSN is <= the
transaction's snapshot LSN — i.e. the page reflects a state that was
durably committed *before* this transaction began.

Why WAL LSN instead of a true MVCC chain?
-----------------------------------------
WAL LSN is a single 8-byte integer per page (already free in the
header layout after T-15.3 added the 4-byte ``last_lsn`` field).  It
gives us snapshot semantics for readers without a per-row version
chain, which would multiply every row's storage cost.  v0.2's
snapshot is *visibility*, not *value*: a writer still has to wait
for older readers to finish before overwriting a page, but the
common case (a reader holding the snapshot open while a writer
commits new pages) is satisfied by LSN comparison alone.

Limitations
-----------
* Only pages with ``last_lsn`` set by v0.2 are eligible; v0.1 files
  default to 0 and the snapshot treats all such pages as "ancient"
  (always visible) until a writer updates them.
* A single snapshot per transaction — there is no
  read-your-own-writes within a transaction because the snapshot
  LSN is fixed at begin() time.  v0.2 inherits this from v0.1.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A point-in-time visibility window anchored at a single LSN.

    A page whose ``last_lsn`` is <= ``lsn`` is considered visible.
    Pages with ``last_lsn`` > ``lsn`` were modified after this
    snapshot was taken and must be re-read from disk (or, for
    pages that no longer exist, treated as not yet present).
    """

    lsn: int

    def is_visible(self, page_lsn: int) -> bool:
        """Return ``True`` if ``page_lsn`` was committed at or before this snapshot."""
        return page_lsn <= self.lsn

    def is_newer(self, page_lsn: int) -> bool:
        """Return ``True`` if ``page_lsn`` was written after this snapshot."""
        return page_lsn > self.lsn


__all__ = ["Snapshot"]