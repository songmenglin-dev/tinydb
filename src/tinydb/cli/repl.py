"""tinydb CLI — Read-Eval-Print Loop (T-8.3, meta-commands in T-8.4).

The REPL is intentionally injected (``input_fn``, ``output``) so tests
can run it without touching real stdin/stdout.  Meta-commands (``.exit``
/ ``.quit`` / ``.help`` / ``.tables`` / ``.schema``) are dispatched
before the SQL parse path; that logic lands in T-8.4 — for now we
expose :func:`dispatch_meta` as a stub that returns ``False`` so the
REPL falls through to SQL.
"""
from __future__ import annotations

from typing import Callable, List

from tinydb.api import Database
from tinydb.cli.format import format_rows
from tinydb.errors import ParseError, TinydbError


# Type aliases — make the injected callables self-documenting in
# signatures and docstrings.
InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


def dispatch_meta(line: str, db: Database, output: OutputFn) -> bool:
    """Hook for ``.<cmd>`` handlers (T-8.4 will fill this in).

    Returns True if ``line`` was a meta-command and was handled, False
    if the caller should continue with the SQL path.  v0.3 always
    returns False; T-8.4 expands it to dispatch ``.exit`` / ``.quit``
    / ``.help`` / ``.tables`` / ``.schema``.
    """
    return False


def run_repl(
    db: Database,
    *,
    input_fn: InputFn = input,
    output: OutputFn = print,
) -> int:
    """Drive the REPL.  Returns the process exit code (0 normally).

    The loop:
    1. Reads one line at a time via ``input_fn``.
    2. Strips whitespace; empty lines are no-ops.
    3. Tries :func:`dispatch_meta` first (T-8.4).  Falls through to
       :meth:`Database.execute` on False.
    4. Renders SELECT results via :func:`format_rows`; DML rows
       (``[(affected_count,)]``) are rendered the same way so the user
       sees ``1`` after an INSERT.
    5. Catches :class:`ParseError` and :class:`TinydbError` and prints
       a short error message; the loop never exits on user input.
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
        # Meta-command hook (T-8.4 wires .exit / .quit / .help / etc.).
        if dispatch_meta(line, db, output):
            continue
        try:
            rows = db.execute(line)
        except ParseError as exc:
            output(f"ParseError: {exc.msg} (line {exc.line}, col {exc.col})")
            continue
        except TinydbError as exc:
            output(f"Error: {exc}")
            continue
        # SELECT returns rows; DML returns [(affected,)]; DDL returns [].
        if rows:
            output(format_rows(rows))
    return 0


__all__ = ["InputFn", "OutputFn", "dispatch_meta", "run_repl"]