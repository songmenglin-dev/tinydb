"""REPL meta-commands for client/server mode (v0.3, T-4.7).

The dual-mode CLI lets users ``.connect`` to a remote server mid-session,
``.disconnect``, and inspect the current connection with ``.status`` /
``.server-info``.  These commands are only meaningful when the backend
can actually talk to a remote server — the file-backend ignores them.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from tinydb.cli.backend import Backend, BackendResult, FileBackend, RemoteBackend
from tinydb.client.errors import (
    ConnectionError as ClientConnectionError,
    ProtocolError,
)
from tinydb.client.sync import Client
from tinydb.cli.uri import parse_uri
from tinydb.cli.format import format_table, ColumnMeta

OutputFn = Callable[[str], None]


class _DisconnectedBackend(Backend):
    """Placeholder backend used after ``.disconnect`` from a remote."""

    def execute(self, sql: str) -> BackendResult:
        from tinydb.errors import TinydbError
        raise TinydbError("not connected to any backend (use .connect)")

    def close(self) -> None:
        return None


class ConnectionState:
    """Mutable bag holding the current backend + connection info.

    The REPL loop holds one of these; meta-commands mutate it via the
    ``cmd_*`` helpers below.  Keeping the state in one place avoids the
    need to plumb it through every helper signature.
    """

    def __init__(self, backend: Backend) -> None:
        self.backend: Backend = backend
        self.uri: Optional[str] = None  # set when backend is RemoteBackend
        self.server_version: Optional[str] = None
        self.starting_backend: Backend = backend  # for restore on disconnect


def _emit_table(rows: list, columns: list, output: OutputFn) -> None:
    metas = [ColumnMeta(name=n, type_name="TEXT") for n in columns]
    output(format_table(rows, metas))


def cmd_connect(state: ConnectionState, arg: str, output: OutputFn) -> str:
    """.connect <uri> — replace the current backend with a RemoteBackend.

    Returns ``"handled"`` so the REPL loop continues.
    """
    arg = arg.strip()
    if not arg:
        output("Usage: .connect tinydb://host:port/dbname")
        return "handled"
    try:
        parsed = parse_uri(arg)
    except ValueError as exc:
        output(f"Error: {exc}")
        return "handled"
    try:
        client = Client(
            parsed.host,
            parsed.port,
            database=parsed.database,
            connect_timeout=5.0,
        )
    except ClientConnectionError as exc:
        output(f"Error: cannot connect to {parsed.host}:{parsed.port}: {exc}")
        return "handled"
    # Close the previous backend so we don't leak sockets.
    try:
        state.backend.close()
    except Exception:
        pass
    state.backend = RemoteBackend(client)
    state.uri = arg
    state.server_version = client.version
    output(f"Connected to {arg} (server version {client.version})")
    return "handled"


def cmd_disconnect(state: ConnectionState, arg: str, output: OutputFn) -> str:
    """.disconnect — close the current backend (no-op for file mode)."""
    if isinstance(state.backend, FileBackend):
        output("Not connected (file mode).")
        return "handled"
    if isinstance(state.backend, _DisconnectedBackend):
        output("Already disconnected.")
        return "handled"
    try:
        state.backend.close()
    except Exception:
        pass
    output(f"Disconnected from {state.uri or 'server'}.")
    state.backend = _DisconnectedBackend()
    state.uri = None
    state.server_version = None
    return "handled"


def cmd_status(state: ConnectionState, arg: str, output: OutputFn) -> str:
    """.status — print one-line summary of the current backend."""
    if isinstance(state.backend, FileBackend):
        db = state.backend._db
        path = getattr(db, "_path", None)
        path_str = str(path) if path is not None else ":memory:"
        output(f"mode: file  path: {path_str}")
        return "handled"
    if isinstance(state.backend, RemoteBackend):
        output(f"mode: remote  uri: {state.uri or '(unknown)'}")
        return "handled"
    if isinstance(state.backend, _DisconnectedBackend):
        output("mode: disconnected")
        return "handled"
    output("mode: unknown")
    return "handled"


def cmd_server_info(state: ConnectionState, arg: str, output: OutputFn) -> str:
    """.server-info — server version + RTT (remote only)."""
    if not isinstance(state.backend, RemoteBackend):
        output("Not connected to a server.")
        return "handled"
    client = state.backend._client
    version = state.server_version or client.version or "(unknown)"
    try:
        rtt_ms = client.ping() * 1000.0
        rtt_str = f"{rtt_ms:.2f} ms"
    except (ClientConnectionError, ProtocolError, OSError) as exc:
        rtt_str = f"(unreachable: {exc})"
    rows = [
        ("uri", state.uri or "(unknown)"),
        ("version", version),
        ("rtt", rtt_str),
    ]
    _emit_table(rows, ["property", "value"], output)
    return "handled"


# ---------------------------------------------------------------------
# Dispatcher glue
# ---------------------------------------------------------------------


_META_HELP: str = (
    ".exit  / .quit          leave the REPL\n"
    ".help                   show this help\n"
    ".tables                 list every table in the catalog\n"
    ".schema <table>         dump CREATE TABLE for the given table\n"
    ".explain <SQL>          print the logical / physical plan as a tree\n"
    ".history                show the in-session command history\n"
    ".mode line|table        toggle result output format (default: table)\n"
    ".connect <uri>          (remote mode) connect to tinydb://host:port/db\n"
    ".disconnect             (remote mode) close the current server session\n"
    ".status                 print current backend / connection summary\n"
    ".server-info            (remote mode) print server version + RTT"
)


def dispatch_server_meta(
    line: str,
    state: ConnectionState,
    output: OutputFn,
) -> Optional[str]:
    """Dispatch ``.connect`` / ``.disconnect`` / ``.status`` / ``.server-info``.

    Returns ``None`` when the line is not a server meta-command (so the
    REPL can try the database-only meta commands next); ``"handled"``
    when we processed it; ``"exit"`` when ``.exit`` / ``.quit`` is
    recognised.  These three results are the same vocabulary used by
    :func:`tinydb.cli.repl.dispatch_meta`.
    """
    stripped = line.strip()
    if not stripped.startswith("."):
        return None
    parts = stripped.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == ".connect":
        return cmd_connect(state, arg, output)
    if cmd == ".disconnect":
        return cmd_disconnect(state, arg, output)
    if cmd == ".status":
        return cmd_status(state, arg, output)
    if cmd == ".server-info":
        return cmd_server_info(state, arg, output)
    if cmd in {".exit", ".quit"}:
        output("bye.")
        return "exit"
    if cmd == ".help":
        output(_META_HELP)
        return "handled"
    return None  # not ours; let the regular dispatcher try.


__all__ = [
    "ConnectionState",
    "dispatch_server_meta",
    "cmd_connect",
    "cmd_disconnect",
    "cmd_status",
    "cmd_server_info",
]