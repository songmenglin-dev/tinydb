"""tinydb CLI — Read-Eval-Print Loop (T-8.3) + meta-commands (T-8.4).

The REPL is intentionally injected (``input_fn``, ``output``) so tests
can run it without touching real stdin/stdout.

Meta-commands (prefixed with ``.``) are dispatched before the SQL
parse path; supported commands in v0.1 are:

* ``.exit`` / ``.quit`` — leave the REPL with exit code 0.
* ``.help``             — print a short summary of every meta-command.
* ``.tables``           — list every table in the catalog.
* ``.schema``           — dump a reconstructed ``CREATE TABLE``
                          statement for every table.
* ``.anything-else``    — print "unknown command" and continue.
"""
from __future__ import annotations

from typing import Callable, List

from tinydb.api import Database
from tinydb.cli.format import format_rows
from tinydb.errors import ParseError, TinydbError
from tinydb.executor.ops import result_columns
from tinydb.executor.planner import plan as _plan
from tinydb.sql.ast import CreateTable, DropTable
from tinydb.sql.parser import parse
from tinydb.types.system import Column, TypeTag


# Type aliases — make the injected callables self-documenting in
# signatures and docstrings.
InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


def _default_output(line: str) -> None:
    """Resolve ``print`` lazily so capture-mode pytest doesn't break us.

    Binding ``output = print`` at module import captures whatever
    ``print`` was at that instant — fine for normal use, but pytest's
    stdout-capture wraps ``sys.stdout`` and breaks calls to the
    captured reference.  Resolving through ``builtins.print`` each call
    lets pytest's wrapper install/uninstall freely.
    """
    import builtins

    builtins.print(line, flush=True)


def _default_input(prompt: str) -> str:
    """Resolve ``input`` lazily so monkeypatched builtins.input is honoured.

    Same rationale as :func:`_default_output`: pytest wraps stdin and
    tests may monkeypatch ``builtins.input``.  Binding ``input`` at
    module import would freeze a reference that ignores both.
    """
    import builtins

    return builtins.input(prompt)


# --- .schema support: rebuild CREATE TABLE from catalog Column objects.
#
# The original CREATE TABLE source is not stored on disk; we reconstruct
# it from the Column metadata at dump time.  Type tags map to a single
# canonical SQL name; constraint order (PRIMARY KEY, UNIQUE, NOT NULL)
# is fixed so dumps are stable.
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


# --- meta-command dispatch ---------------------------------------------
#
# Tri-state return:
#   False           — not a meta-command, caller falls through to SQL.
#   True            — meta-command handled, REPL keeps reading.
#   "exit"          — meta-command requested shutdown, REPL returns 0.


_HELP_TEXT: str = (
    ".exit  / .quit    leave the REPL\n"
    ".help             show this help\n"
    ".tables           list every table in the catalog\n"
    ".schema           dump CREATE TABLE for every table"
)


def dispatch_meta(line: str, db: Database, output: OutputFn):
    """Dispatch a single REPL line.

    Returns ``False`` if the line is not a meta-command (caller
    continues with the SQL path); ``True`` if it was handled and the
    REPL should continue; the string ``"exit"`` if the REPL should
    terminate with exit code 0.
    """
    stripped = line.strip()
    if not stripped.startswith("."):
        return False
    cmd = stripped.split(None, 1)[0].lower()
    if cmd in {".exit", ".quit"}:
        output("bye.")
        return "exit"
    if cmd == ".help":
        output(_HELP_TEXT)
        return True
    if cmd == ".tables":
        names = db.catalog.list_tables()
        if names:
            output("\n".join(names))
        else:
            output("(no tables)")
        return True
    if cmd == ".schema":
        any_table = False
        for name in db.catalog.list_tables():
            meta = db.catalog.get_table(name)
            output(_build_create_table_sql(name, meta.columns))
            any_table = True
        if not any_table:
            output("(no tables)")
        return True
    output(f"unknown command {stripped!r}; type .help for the list")
    return True


def run_repl(
    db: Database,
    *,
    input_fn: InputFn = _default_input,
    output: OutputFn = _default_output,
) -> int:
    """Drive the REPL.  Returns the process exit code (0 normally).

    ``output`` defaults to a lazy wrapper around :func:`print` so the
    REPL keeps working under pytest's stdout-capture fixture.
    """
    output("tinydb v0.1 REPL — enter SQL, or '.help' for commands")
    while True:
        try:
            line = input_fn("tinydb> ")
        except EOFError:
            return 0
        line = line.strip()
        if not line:
            continue
        handled = dispatch_meta(line, db, output)
        if handled == "exit":
            return 0
        if handled:
            continue
        # T-POLISH: parse first so we can detect DDL and grab column
        # metadata for SELECT formatting before dispatching.  DDL prints
        # "OK"; SELECTs get real column names from the plan tree.
        try:
            stmt = parse(line)
        except ParseError as exc:
            output(f"ParseError: {exc.msg} (line {exc.line}, col {exc.col})")
            continue
        if isinstance(stmt, (CreateTable, DropTable)):
            try:
                db.execute(line)
            except TinydbError as exc:
                output(f"Error: {exc}")
                continue
            output("OK")
            continue
        # DML / SELECT: plan to get column labels, then execute.
        try:
            columns = result_columns(
                _plan(stmt, db.catalog, db.executor.indexer)
            )
        except TinydbError:
            columns = None
        try:
            rows = db.execute(line)
        except TinydbError as exc:
            output(f"Error: {exc}")
            continue
        if not rows:
            continue  # SELECT-with-no-match is silent.
        if columns is None:
            # DML affected-count row: print plainly, not as a column table.
            output(f"{rows[0][0]} row(s)")
            continue
        output(format_rows(rows, columns=columns))
    return 0


__all__ = [
    "InputFn",
    "OutputFn",
    "dispatch_meta",
    "run_repl",
]