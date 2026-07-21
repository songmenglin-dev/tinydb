"""tinydb CLI — REPL (v0.2).

v0.1 used :mod:`cmd`.  v0.2 adds a ``prompt_toolkit``-backed REPL
when the optional dependency is installed and falls back to ``cmd``
otherwise.  Meta-commands live in :func:`dispatch_meta` so both REPL
flavours route through the same SQL path.

The injected ``input_fn`` / ``output`` (legacy) interface still works
for unit tests; the prompt_toolkit path is reached when the caller does
NOT inject ``input_fn``.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from typing import Callable, List, Optional

from tinydb.api import Database
from tinydb.cli.format import (
    ColumnMeta,
    format_line_mode,
    format_table,
    format_timing,
    infer_columns_from_rows,
)
from tinydb.errors import ParseError, TinydbError
from tinydb.executor.ops import result_columns
from tinydb.executor.planner import plan as _plan
from tinydb.sql.ast import CreateTable, DropTable, Select
from tinydb.sql.parser import parse
from tinydb.types.system import TypeTag

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]

# Optional dep probe (REQ-CLI-9 / D-7).
_HAS_PT: bool = importlib.util.find_spec("prompt_toolkit") is not None


def _default_output(line: str) -> None:
    import builtins
    builtins.print(line, flush=True)


def _default_input(prompt: str) -> str:
    import builtins
    return builtins.input(prompt)


# --- meta-command dispatch (REQ-CLI-6..10) ------------------------------


_HELP_TEXT: str = (
    ".exit  / .quit    leave the REPL\n"
    ".help             show this help\n"
    ".tables           list every table in the catalog\n"
    ".schema <table>   dump CREATE TABLE for the given table\n"
    ".explain <SQL>    print the logical / physical plan as a tree\n"
    ".history          show the in-session command history\n"
    ".mode line|table  toggle result output format (default: table)"
)


def dispatch_meta(line: str, db: Database, output: OutputFn, *, mode: Optional[List[str]] = None) -> Optional[str]:
    """Dispatch a single REPL line as a meta-command.

    Returns ``None`` if the line is not a meta-command (caller continues
    with the SQL path); ``"exit"`` if the REPL should terminate;
    ``"handled"`` otherwise.
    """
    stripped = line.strip()
    if not stripped.startswith("."):
        return None
    parts = stripped.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in {".exit", ".quit"}:
        output("bye.")
        return "exit"
    if cmd == ".help":
        output(_HELP_TEXT)
        return "handled"
    if cmd == ".tables":
        names = db.list_tables()
        meta = [ColumnMeta(name="Tables_in_" + db._path.stem, type_name="TEXT")]
        if names:
            table = format_table([(n,) for n in names], meta)
        else:
            table = format_table([], meta)
        output(table)
        return "handled"
    if cmd == ".schema":
        if not arg:
            # v0.1 behavior: dump every table (no argument required).
            names = db.list_tables()
            if not names:
                output("(no tables)")
                return "handled"
            for name in names:
                ddl = db.get_schema(name)
                meta = [ColumnMeta(name="DDL", type_name="TEXT")]
                output(format_table([(ddl,)], meta))
            return "handled"
        table_name = arg.split()[0]
        try:
            ddl = db.get_schema(table_name)
        except KeyError:
            output(f"table '{table_name}' does not exist")
            return "handled"
        meta = [ColumnMeta(name="DDL", type_name="TEXT")]
        output(format_table([(ddl,)], meta))
        return "handled"
    if cmd == ".explain":
        if not arg:
            output("Usage: .explain <SQL>  or  .explain --table <SQL>")
            return "handled"
        if arg.startswith("--table"):
            arg = arg[len("--table"):].strip()
            try:
                rows = db.execute(arg)
            except TinydbError as exc:
                output(f"Error: {exc}")
                return "handled"
            cols = infer_columns_from_rows(rows)
            output(format_table(rows, cols))
            return "handled"
        try:
            output(db.explain(arg))
        except ParseError as exc:
            output(f"ParseError: {exc.msg} (line {exc.line}, col {exc.col})")
        except TinydbError as exc:
            output(f"Error: {exc}")
        return "handled"
    if cmd == ".history":
        history = getattr(db, "_tinydb_history", None)
        if history is None:
            output("(no history)")
            return "handled"
        entries = list(history.entries())
        for i, entry in enumerate(entries, 1):
            output(f"  {i:>3}  {entry}")
        return "handled"
    if cmd == ".mode":
        if not arg:
            output(f"current mode: {mode[0] if mode else 'table'}")
            return "handled"
        target = arg.strip().lower()
        if target in ("table", "line") and mode is not None:
            mode[0] = target
            output(f"mode set to {target}")
        else:
            output(f"unknown mode {target!r}; expected 'table' or 'line'")
        return "handled"
    output(f"unknown command {stripped!r}; type .help for the list")
    return "handled"


# --- continuation detection (REQ-CLI-1/2) --------------------------------


def _is_continuation(buffer: str) -> bool:
    """True when ``buffer`` ends with `\\` or contains unclosed quotes."""
    if buffer.endswith("\\"):
        return True
    # Naive quote tracker: count single and double quotes that are NOT
    # escaped.  Doubled quotes inside a string ('') are an SQL-standard
    # escape, but they still count as TWO opens from the perspective of
    # raw byte counting; we therefore only treat an odd count of `'` as
    # an open string (so '' -> '' -> even -> closed).  Since SQL doubles
    # quotes inside a single literal, an even count means we are
    # balanced.
    if buffer.count("'") % 2 == 1:
        return True
    if buffer.count('"') % 2 == 1:
        return True
    return False


# --- result rendering (REQ-CLI-12..16) ----------------------------------


def _render_select(
    rows: List,
    columns: List[str],
    types: List[str],
    mode: str,
    *,
    elapsed: float,
) -> str:
    metas = [ColumnMeta(name=n, type_name=t) for n, t in zip(columns, types)]
    if mode == "line":
        body = format_line_mode(rows, metas)
        if not rows:
            return format_timing(0, elapsed)
        return (body + "\n" + format_timing(len(rows), elapsed)) if body else format_timing(0, elapsed)
    body = format_table(rows, metas)
    return body + "\n" + format_timing(len(rows), elapsed)


def _column_types_for_select(stmt: Select, db: Database) -> List[str]:
    meta = db.catalog.get_table(stmt.table)
    name_to_type = {c.name: c.tag.name for c in meta.columns}
    out: List[str] = []
    from tinydb.sql.ast import Star
    for col in stmt.columns:
        if isinstance(col, Star):
            for c in meta.columns:
                out.append(c.tag.name)
            continue
        name = getattr(col, "name", None)
        if name is None:
            out.append("TEXT")
        else:
            out.append(name_to_type.get(name, "TEXT"))
    return out


# --- core SQL execution helper (shared by both REPL flavours) ----------


def _execute_sql(
    line: str,
    db: Database,
    output: OutputFn,
    *,
    mode: str,
    history_sink: Optional[Callable[[str], None]] = None,
) -> None:
    try:
        stmt = parse(line)
    except ParseError as exc:
        output(f"ParseError: {exc.msg} (line {exc.line}, col {exc.col})")
        return
    if history_sink is not None:
        history_sink(line)
    if isinstance(stmt, (CreateTable, DropTable)):
        try:
            db.execute(line)
        except TinydbError as exc:
            output(f"Error: {exc}")
            return
        output("OK")
        return
    is_select = isinstance(stmt, Select)
    try:
        columns: Optional[List[str]] = None
        types: List[str] = []
        if is_select:
            try:
                columns = result_columns(_plan(stmt, db.catalog, db.executor.indexer))
            except TinydbError:
                columns = None
            if columns:
                types = _column_types_for_select(stmt, db)
    except TinydbError:
        columns = None
    t0 = time.perf_counter()
    try:
        rows = db.execute(line)
    except TinydbError as exc:
        output(f"Error: {exc}")
        return
    elapsed = time.perf_counter() - t0
    if not rows:
        if columns is not None and is_select:
            output(_render_select(rows, columns, types, mode, elapsed=elapsed))
        else:
            output("(0 rows)")
        return
    if columns is None or not is_select:
        output(f"{rows[0][0]} row(s)")
        return
    output(_render_select(rows, columns, types, mode, elapsed=elapsed))


# --- prompt_toolkit REPL -------------------------------------------------


def _build_prompt_session(history=None, lexer=None):  # pragma: no cover — interactive
    from prompt_toolkit import PromptSession
    kwargs = {"multiline": True}
    if history is not None:
        kwargs["history"] = history
    if lexer is not None:
        kwargs["lexer"] = lexer
    return PromptSession(**kwargs)


def _run_prompt_toolkit_repl(db: Database) -> int:  # pragma: no cover — interactive
    from prompt_toolkit.history import FileHistory as _PTFileHistory
    from tinydb.cli.highlight import make_prompt_toolkit_lexer
    from pathlib import Path

    sys.stdout.write("tinydb v0.1 REPL — enter SQL, or '.help' for commands\n")
    sys.stdout.flush()

    history_path = Path.home() / ".tinydb_history"
    history = _PTFileHistory(str(history_path))
    lexer = make_prompt_toolkit_lexer()
    session = _build_prompt_session(history=history, lexer=lexer)
    mode = ["table"]

    buffer = ""
    while True:
        try:
            if buffer:
                text = session.prompt("    ...> ")
            else:
                text = session.prompt("tinydb> ")
        except KeyboardInterrupt:
            buffer = ""
            continue
        except EOFError:
            return 0
        if not text:
            if buffer:
                # Empty continuation line submits what we have.
                line = buffer.rstrip()
                buffer = ""
                if not line:
                    continue
                handled = dispatch_meta(line, db, _default_output, mode=mode)
                if handled == "exit":
                    return 0
                if handled == "handled":
                    continue
                _execute_sql(line, db, _default_output, mode=mode)
            continue
        if buffer:
            buffer = buffer[:-1] if buffer.endswith("\\") else buffer
            buffer = buffer + " " + text
        else:
            buffer = text
        if not _is_continuation(buffer):
            line = buffer.rstrip()
            buffer = ""
            if not line:
                continue
            handled = dispatch_meta(line, db, _default_output, mode=mode)
            if handled == "exit":
                return 0
            if handled == "handled":
                continue
            _execute_sql(line, db, _default_output, mode=mode)


# --- cmd-fallback REPL (v0.1 path) --------------------------------------


def _run_cmd_fallback(db: Database) -> int:
    """v0.1-compatible REPL using :mod:`cmd` (no PT)."""
    sys.stdout.write("tinydb v0.2 REPL — enter SQL, or '.help' for commands\n")
    sys.stdout.flush()

    class _CmdShell:
        def __init__(self, db: Database, output: OutputFn) -> None:
            self.db = db
            self.output = output
            self.mode = "table"

        def _emit(self, line: str) -> None:
            self.output(line)

        def run(self) -> int:
            while True:
                sys.stdout.write("tinydb> ")
                sys.stdout.flush()
                try:
                    raw = _default_input("")
                except EOFError:
                    return 0
                line = raw.strip()
                if not line:
                    continue
                handled = dispatch_meta(line, self.db, self._emit, mode=[self.mode])
                if handled == "exit":
                    return 0
                if handled == "handled":
                    continue
                _execute_sql(line, self.db, self._emit, mode=self.mode)

    return _CmdShell(db, _default_output).run()


# --- public entry point -------------------------------------------------


def run_repl(
    db: Database,
    *,
    input_fn: InputFn = _default_input,
    output: OutputFn = _default_output,
) -> int:
    """Drive the REPL.  Returns the process exit code (0 normally).

    The legacy ``input_fn`` / ``output`` injection path runs the
    v0.1-compatible fallback so the existing 727 tests stay green even
    when prompt_toolkit is available.  When no ``input_fn`` is passed
    we use the prompt_toolkit session if installed, otherwise fall back
    to a ``cmd``-style REPL.
    """
    if input_fn is not _default_input:
        # Legacy test path: never go through prompt_toolkit.
        return _run_legacy(db, input_fn, output)

    if _HAS_PT:
        return _run_prompt_toolkit_repl(db)
    return _run_cmd_fallback(db)


def _run_legacy(db: Database, input_fn: InputFn, output: OutputFn) -> int:
    """Run the v0.1-style REPL loop with an injected ``input_fn``.

    Used by the test suite so we can replay canned input without
    touching real stdin/stdout.  Handles backslash / unclosed-quote
    continuation the same way the prompt_toolkit branch does so the
    same canned input scripts work in both modes.
    """
    output("tinydb v0.1 REPL — enter SQL, or '.help' for commands")
    mode_holder: list = ["table"]  # shared mutable so dispatch_meta can update
    buffer = ""
    while True:
        try:
            raw = input_fn("" if not buffer else "...> ")
        except (EOFError, KeyboardInterrupt):
            return 0
        if buffer:
            buffer = buffer[:-1] if buffer.endswith("\\") else buffer
            buffer = (buffer + " " + raw).strip() if raw else buffer
        else:
            buffer = raw.strip()
        if _is_continuation(buffer):
            continue
        line = buffer
        buffer = ""
        if not line:
            continue
        handled = dispatch_meta(line, db, output, mode=mode_holder)
        if handled == "exit":
            return 0
        if handled == "handled":
            continue
        _execute_sql(line, db, output, mode=mode_holder[0])


__all__ = [
    "InputFn",
    "OutputFn",
    "dispatch_meta",
    "run_repl",
    "_HAS_PT",
]