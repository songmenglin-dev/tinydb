"""Periodic checkpoint — record a WAL anchor.

A :class:`Checkpoint` flushes durable state to the WAL as a single
``RT_CKPT`` frame.  The payload carries the LSN that was
next-to-assign at the moment the checkpoint was taken — i.e. the LSN
of the checkpoint frame itself.

v0.1 simplification
-------------------
This implementation does NOT truncate the WAL on checkpoint.  WAL
truncation needs LSN-per-page tracking so that frames older than the
checkpoint's LSN can be safely removed without losing the redo
history of pages not yet flushed.  T-6.6 NIT-1 deferred that
infrastructure; the brief for T-6.7 confirms we just *stamp* the WAL.

``Recovery.replay()`` ignores unknown record types, so RT_CKPT frames
are inert during recovery — they cost one WAL slot and zero replay
work.  This means callers can call :meth:`run` as often as they like
without disturbing the B6 recovery gate.

Usage::

    cp = Checkpoint(pager, wal)
    cp.run()    # append exactly one RT_CKPT frame
"""
from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from tinydb.tx.wal import RT_CKPT

if TYPE_CHECKING:  # pragma: no cover
    from tinydb.storage.pager import Pager
    from tinydb.tx.wal import WAL


def _encode_lsn(lsn: int) -> bytes:
    """Encode an LSN as u64 BE for the RT_CKPT payload."""
    return struct.pack(">Q", lsn)


class Checkpoint:
    """Periodic checkpoint — flush + WAL anchor.

    Parameters
    ----------
    pager:
        The :class:`tinydb.storage.pager.Pager` for the database.  The
        pager is accepted for API symmetry with the future
        page-flushing variant and is intentionally not used yet.
    wal:
        The :class:`tinydb.tx.WAL` the checkpoint frame is appended to.
    """

    __slots__ = ("_pager", "_wal")

    def __init__(self, pager: "Pager", wal: "WAL") -> None:
        self._pager = pager
        self._wal = wal

    @property
    def pager(self) -> "Pager":
        """The pager this checkpoint is bound to (read-only)."""
        return self._pager

    @property
    def wal(self) -> "WAL":
        """The WAL this checkpoint appends to (read-only)."""
        return self._wal

    def run(self) -> int:
        """Append one RT_CKPT frame; return the LSN it consumed.

        The frame payload is the LSN that was next-to-assign at the
        moment the checkpoint began — which equals the LSN assigned to
        this very frame.  This anchor lets future versions truncate the
        WAL safely without losing redo history.
        """
        lsn = self._wal.next_lsn
        self._wal.append(RT_CKPT, _encode_lsn(lsn))
        return lsn


__all__ = ["Checkpoint"]