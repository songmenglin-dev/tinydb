"""Cross-process file lock for the WAL append path.

REQ-CONC-2 specifies that the WAL must be guarded by an exclusive
cross-process lock so two Python processes writing to the same
``.db`` file cannot interleave WAL frames. On POSIX systems we use
:func:`fcntl.flock`. On Windows ``fcntl`` is not available so we fall
back to :mod:`msvcrt` ``locking`` (range lock on a file descriptor)
when the platform supports it; if neither is available the
constructor raises :class:`ProcessLockUnavailableError` immediately
rather than failing silently at lock-acquisition time.

Why we do NOT use :func:`fcntl.flock` exclusively
-----------------------------------------------
Some Windows test runners and CI containers do not have ``fcntl`` at
all (it's a Unix-only module). We refuse to install a Linux-only
dependency, so we attempt ``msvcrt`` first on Windows. If
``msvcrt`` ``import`` itself fails (e.g. running on a non-Windows
non-POSIX hybrid platform) we surface a clear error.

Scope of the lock
-----------------
Only the WAL is locked — readers do not need cross-process exclusion
because they go through the BufferPool and use the page-LSN snapshot
machinery for visibility (REQ-CONC-5).
"""
from __future__ import annotations

import os
import sys
from types import TracebackType
from typing import IO, Optional, Type


class ProcessLockUnavailableError(RuntimeError):
    """Raised when no cross-process locking primitive is available.

    This is *never* raised silently — callers can ``except`` it and
    decide whether to retry, degrade to single-process mode, or abort.
    """


class ProcessLock:
    """Exclusive cross-process file lock context manager.

    Parameters
    ----------
    fp:
        An open binary file handle (must support ``fileno()``).
    exclusive:
        ``True`` for an exclusive (writer) lock, ``False`` for a
        shared (reader) lock. tinydb only uses exclusive locks on the
        WAL so this is ``True`` by default.

    Notes
    -----
    The lock is released on ``__exit__``. Calling ``__exit__`` more
    times than ``__enter__`` is a no-op (idempotent).
    """

    __slots__ = ("_fp", "_exclusive", "_locked")

    def __init__(self, fp: IO[bytes], *, exclusive: bool = True) -> None:
        self._fp = fp
        self._exclusive = exclusive
        self._locked: bool = False
        # Probe availability eagerly so the caller fails at construction
        # rather than at first use (REQ-CONC-2: no silent failure).
        _ensure_locking_available()

    def __enter__(self) -> "ProcessLock":
        if self._locked:
            raise RuntimeError("ProcessLock re-entered without release")
        fd = self._fp.fileno()
        if os.name == "posix":
            import fcntl  # POSIX-only; raises ImportError on Windows.

            op = fcntl.LOCK_EX if self._exclusive else fcntl.LOCK_SH
            # Non-blocking would raise BlockingIOError immediately; we
            # want a blocking lock so concurrent writers serialize.
            fcntl.flock(fd, op)
            self._locked = True
            return self
        if os.name == "nt":
            import msvcrt  # type: ignore[import-not-found]

            mode = msvcrt.LK_NBLCK if self._exclusive else msvcrt.LK_NBRLCK
            # msvcrt.locking locks a *byte range*; for our purposes a
            # 1-byte range starting at the current position is
            # sufficient — concurrent appenders serialize on this
            # 1-byte critical section.
            try:
                msvcrt.locking(fd, mode, 1)
            except OSError:
                # Another process holds the lock — block until we get it.
                mode_block = (
                    msvcrt.LK_LOCK if self._exclusive else msvcrt.LK_RLCK
                )
                msvcrt.locking(fd, mode_block, 1)
            self._locked = True
            return self
        raise ProcessLockUnavailableError(
            f"unsupported platform os.name={os.name!r}; "
            "no cross-process lock available"
        )

    def __exit__(
        self,
        et: Optional[Type[BaseException]],
        ev: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> bool:
        if not self._locked:
            return False
        fd = self._fp.fileno()
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            elif os.name == "nt":
                import msvcrt  # type: ignore[import-not-found]

                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            self._locked = False
        return False


def _ensure_locking_available() -> None:
    """Eagerly verify that the current platform offers a lock primitive.

    Runs at ``ProcessLock.__init__`` so callers fail at construction
    time. On POSIX ``fcntl`` is always importable; on Windows we
    verify ``msvcrt`` is importable. We do NOT actually acquire a
    lock here — we only verify the import.
    """
    if os.name == "posix":
        try:
            import fcntl  # noqa: F401  (probe)
        except ImportError as exc:  # pragma: no cover - defensive
            raise ProcessLockUnavailableError(
                "fcntl is not importable on a POSIX platform"
            ) from exc
        return
    if os.name == "nt":
        try:
            import msvcrt  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            raise ProcessLockUnavailableError(
                "msvcrt is not available on this Windows host"
            ) from exc
        return
    raise ProcessLockUnavailableError(
        f"unsupported platform os.name={os.name!r}; sys.platform={sys.platform!r}"
    )


__all__ = ["ProcessLock", "ProcessLockUnavailableError"]