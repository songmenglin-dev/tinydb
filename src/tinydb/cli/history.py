"""Command history persistence — wraps prompt_toolkit's FileHistory.

REQ-CLI-8: history lives at ``~/.tinydb_history``.  Loads on start,
appends on quit; falls back to a no-op history when the path is
unwritable so REPL keeps working in sandboxed environments.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import List, Protocol


class _HistoryLike(Protocol):
    """Minimal duck type we depend on for the REPL."""

    def append(self, entry: str) -> None: ...
    def load(self) -> None: ...
    def __iter__(self): ...


def default_history_path() -> Path:
    """``~/.tinydb_history`` — created lazily on first save."""
    return Path.home() / ".tinydb_history"


class _NullHistory:
    """In-memory history used when prompt_toolkit is unavailable."""

    def __init__(self) -> None:
        self._buf: List[str] = []

    def append(self, entry: str) -> None:
        if entry:
            self._buf.append(entry)

    def load(self) -> None:
        return None

    def __iter__(self):
        return iter(self._buf)


class FileHistory:
    """Persistent ``~/.tinydb_history``.

    Wraps :class:`prompt_toolkit.history.FileHistory` when available;
    if prompt_toolkit is missing we expose the same interface but the
    history only lives in-process.

    If the file cannot be opened for writing we issue a warning (REQ-CLI-8
    fallback) and silently degrade to the in-memory buffer.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path: Path = Path(path) if path else default_history_path()
        self._inner = _NullHistory()
        self._has_pt = False
        try:
            from prompt_toolkit.history import FileHistory as _PTFileHistory  # noqa: WPS433
            self._inner = _PTFileHistory(str(self._path))
            self._has_pt = True
        except ImportError:
            pass
        except OSError as exc:
            warnings.warn(
                f"[tinydb] cannot open history file {self._path}: {exc}; "
                "in-memory history only",
                RuntimeWarning,
                stacklevel=2,
            )

    @property
    def path(self) -> Path:
        return self._path

    @property
    def persistent(self) -> bool:
        """``True`` when backed by a real on-disk FileHistory."""
        return self._has_pt

    def append(self, entry: str) -> None:
        if not entry:
            return
        if self._has_pt:
            try:
                # prompt_toolkit's FileHistory exposes ``append_string``;
                # ``store_string`` also exists but only persists on close
                # which never fires in our long-running REPL.
                self._inner.append_string(entry)
            except OSError as exc:
                warnings.warn(
                    f"[tinydb] cannot append to history {self._path}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
            return
        try:
            self._inner.append(entry)
        except OSError as exc:
            warnings.warn(
                f"[tinydb] cannot append to history {self._path}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    def load(self) -> None:
        try:
            self._inner.load()
        except OSError:
            pass

    def entries(self) -> List[str]:
        if self._has_pt:
            try:
                return list(self._inner.load_history_strings())
            except Exception:
                return []
        try:
            return [str(s) for s in self._inner]
        except Exception:
            return []

    def __iter__(self):
        return iter(self.entries())


__all__ = ["FileHistory", "default_history_path"]