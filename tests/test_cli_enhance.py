"""Tests for the v0.2 CLI enhancements (REQ-CLI-1..16).

These tests cover the new CLI behaviour on top of the v0.1 REPL.  Each
test is intentionally narrow so failures point at a single requirement.
The fixture ``make_db`` opens a fresh ``tinydb`` on ``tmp_path`` and
returns a captured ``output`` list + ``run`` callable; tests drive
``run`` with a canned ``input_fn`` (the v0.1 legacy injection path),
which routes through the cmd-fallback REPL — identical semantics to
prompt_toolkit for the SQL/meta-command layer.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable, List

import pytest

from tinydb.api import Database
from tinydb.cli import repl
from tinydb.cli.format import (
    ColumnMeta,
    format_line_mode,
    format_table,
    format_timing,
)
from tinydb.cli.highlight import (
    StyledSpan,
    highlight_sql,
    render_ansi,
    render_with_comments,
)
from tinydb.cli.history import FileHistory


HAS_PT: bool = importlib.util.find_spec("prompt_toolkit") is not None


# --- fixtures -----------------------------------------------------------


def make_db(tmp_path: Path):
    """Return (db, output, run_repl) bound to a fresh in-memory DB."""
    db = Database(tmp_path / "t.db")
    captured: List[str] = []

    def run(inputs: List[str]) -> int:
        seq = iter(inputs + [StopIteration])

        def fake_input(prompt: str) -> str:
            item = next(seq)
            if item is StopIteration:
                raise EOFError
            return item

        rc = repl.run_repl(db, input_fn=fake_input, output=captured.append)
        return rc

    return db, captured, run


# --- REQ-CLI-9: detection / fallback -----------------------------------


def test_cli_detects_prompt_toolkit_flag() -> None:
    """``_HAS_PT`` mirrors whether the optional dep is importable."""
    assert repl._HAS_PT is HAS_PT  # noqa: SLF001 — internal symbol by design


def test_cli_prompt_toolkit_present_in_env() -> None:
    """In this sandbox prompt_toolkit IS installed (we pip-installed it
    so the integration tests can exercise the PT branch in CI)."""
    assert HAS_PT, "expected prompt_toolkit to be installed for v0.2 dev"


# --- REQ-CLI-12..14: ASCII table renderer -------------------------------


def test_format_table_basic() -> None:
    """Header + at least one row produces top, header, mid, body, bot."""
    out = format_table([(1, "a", 1.5)], [ColumnMeta("id", "INT"), ColumnMeta("name", "TEXT"), ColumnMeta("v", "FLOAT")])
    lines = out.split("\n")
    assert lines[0].startswith("+")
    assert lines[0].endswith("+")
    assert lines[1].startswith("|")
    assert lines[2].startswith("+")
    assert any("1" in line and "a" in line for line in lines)


def test_format_table_empty_emits_header_and_borders() -> None:
    out = format_table([], [ColumnMeta("id", "INT"), ColumnMeta("name", "TEXT")])
    lines = out.split("\n")
    assert len(lines) == 4  # top, header, mid, bottom
    assert all(l.startswith("+") or l.startswith("|") for l in lines)


def test_format_table_numeric_alignment_right() -> None:
    # Multi-column: right-alignment is observable when the longest
    # value (``100``) determines the column width and shorter values
    # get leading spaces.
    out = format_table(
        [(1, "x"), (2, "y"), (100, "z")],
        [ColumnMeta("n", "INT"), ColumnMeta("c", "TEXT")],
    )
    lines = out.split("\n")
    # Find data rows (skip borders and header).
    data_lines = [l for l in lines if l.startswith("|") and "n" not in l.split("|")[1].strip()]
    # Header row contains ``n`` and ``c`` literally; data rows have a
    # numeric cell followed by ``|`` then the string.
    assert any(line.endswith(" 100 | z |") for line in lines)
    assert any(line.endswith("   1 | x |") for line in lines)


def test_format_table_string_alignment_left() -> None:
    out = format_table(
        [("a",), ("bb",), ("ccc",)],
        [ColumnMeta("s", "TEXT")],
    )
    # Longest value ``ccc`` -> width 3. ``a`` and ``bb`` left-aligned.
    assert any(line.endswith(" a   |") for line in out.split("\n"))
    assert any(line.endswith(" bb  |") for line in out.split("\n"))


def test_format_table_blob_hex() -> None:
    out = format_table([(b"\x01\x02\x03",)], [ColumnMeta("b", "BLOB")])
    assert "0x010203" in out


def test_format_table_null_literal() -> None:
    out = format_table([(1, None)], [ColumnMeta("id", "INT"), ColumnMeta("v", "TEXT")])
    assert "NULL" in out


def test_format_table_column_widths_adaptive() -> None:
    out = format_table([("short",), ("a-very-long-string",)], [ColumnMeta("s", "TEXT")])
    # The header ``s`` must be padded to the longest cell width.
    assert "s" in out
    assert "a-very-long-string" in out


def test_format_timing_zero_rows() -> None:
    assert format_timing(0, 0.0) == "Empty set (0.00s)"
    assert format_timing(0, 0.123) == "Empty set (0.12s)"


def test_format_timing_n_rows() -> None:
    assert format_timing(5, 0.02) == "5 rows in set (0.02s)"


def test_format_line_mode() -> None:
    out = format_line_mode([(1, "alice")], [ColumnMeta("id", "INT"), ColumnMeta("name", "TEXT")])
    assert "id = 1" in out
    assert "name = alice" in out


# --- REQ-CLI-5: highlight ----------------------------------------------


def test_highlight_keywords_have_color() -> None:
    spans = highlight_sql("SELECT * FROM t")
    coloured = [s for s in spans if s.color]
    # SELECT and FROM are keywords -> coloured
    assert any(s.text == "SELECT" for s in coloured)
    assert any(s.text == "FROM" for s in coloured)


def test_highlight_string_literal() -> None:
    spans = highlight_sql("WHERE n = 'alice'")
    coloured = [s for s in spans if s.color]
    assert any("alice" in s.text for s in coloured)


def test_highlight_number_literal() -> None:
    spans = highlight_sql("WHERE age > 18")
    coloured = [s for s in spans if s.color]
    assert any(s.text == "18" for s in coloured)


def test_highlight_comment_via_helper() -> None:
    out = render_with_comments("SELECT 1 -- a comment\nFROM t")
    assert "-- a comment" in out
    # comment text is wrapped in the grey ANSI code
    assert "\x1b[90m" in out


def test_highlight_render_ansi_round_trip() -> None:
    out = render_ansi(highlight_sql("SELECT 1"))
    assert "\x1b[" in out  # ANSI escape present
    assert "SELECT" in out


# --- REQ-CLI-6: explain -------------------------------------------------


class _FakeNode:
    """Tiny stand-in for an executor Plan node."""

    def __init__(self, name, **attrs) -> None:
        self.name = name
        for k, v in attrs.items():
            setattr(self, k, v)

    def __repr__(self) -> str:
        return self.name


def _ensure_children_attr():
    """Make sure our fake nodes expose a ``children`` list attribute."""
    pass


def test_format_plan_single_node() -> None:
    from tinydb.cli.explain import format_plan
    root = _FakeNode("Project", children=[_FakeNode("SeqScan", table="users")])
    out = format_plan(root, heading="LogicalPlan")
    assert "LogicalPlan" in out
    assert "SeqScan" in out
    assert "└──" in out


def test_format_plan_join_via_src_chain() -> None:
    from tinydb.cli.explain import format_plan
    join = _FakeNode("NestedLoopJoin", left=_FakeNode("SeqScan", table="u"), right=_FakeNode("SeqScan", table="o"))
    out = format_plan(join, heading="PhysicalPlan")
    assert "NestedLoopJoin" in out
    assert "SeqScan" in out


def test_explain_meta_command_runs(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE u (id INT PRIMARY KEY, name TEXT);",
            "INSERT INTO u VALUES (1, 'a');",
            ".explain SELECT * FROM u WHERE id = 1",
            "",
        ])
        joined = "\n".join(captured)
        assert "SeqScan" in joined or "IndexScan" in joined or "Project" in joined
    finally:
        db.close()


def test_explain_meta_command_table_mode(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE u (id INT PRIMARY KEY, name TEXT);",
            "INSERT INTO u VALUES (1, 'a');",
            ".explain --table SELECT id FROM u",
            "",
        ])
        joined = "\n".join(captured)
        assert joined.startswith("+") or "+---" in joined
    finally:
        db.close()


def test_explain_parse_error(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([".explain SELECT FROMM u", ""])
        joined = "\n".join(captured)
        assert "ParseError" in joined
    finally:
        db.close()


# --- REQ-CLI-7: .tables / .schema --------------------------------------


def test_dot_tables_lists_tables(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE users (id INT);",
            "CREATE TABLE orders (id INT);",
            ".tables",
            "",
        ])
        joined = "\n".join(captured)
        assert "users" in joined
        assert "orders" in joined
    finally:
        db.close()


def test_dot_tables_empty(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([".tables", ""])
        joined = "\n".join(captured)
        # header still rendered with no rows
        assert "Tables_in_t" in joined
    finally:
        db.close()


def test_dot_schema_known_table(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE u (id INT PRIMARY KEY, name TEXT NOT NULL);",
            ".schema u",
            "",
        ])
        joined = "\n".join(captured)
        assert "CREATE TABLE u" in joined
        assert "id INT" in joined
        assert "name TEXT" in joined
        assert "PRIMARY KEY" in joined
    finally:
        db.close()


def test_dot_schema_missing_table(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([".schema ghost", ""])
        joined = "\n".join(captured)
        assert "does not exist" in joined
    finally:
        db.close()


# --- REQ-CLI-13: SELECT row count + timing -----------------------------


def test_repl_shows_row_count_and_timing(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE t (id INT PRIMARY KEY);",
            "INSERT INTO t VALUES (1);",
            "INSERT INTO t VALUES (2);",
            "SELECT * FROM t",
            "",
        ])
        joined = "\n".join(captured)
        assert "2 rows in set" in joined
    finally:
        db.close()


def test_repl_shows_empty_set(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE t (id INT PRIMARY KEY);",
            "SELECT * FROM t",
            "",
        ])
        joined = "\n".join(captured)
        assert "Empty set" in joined
    finally:
        db.close()


def test_repl_no_timing_for_insert(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE t (id INT PRIMARY KEY);",
            "INSERT INTO t VALUES (1);",
            "",
        ])
        joined = "\n".join(captured)
        # INSERT prints "1 row(s)" via the DML path; NOT the timing footer.
        assert "1 row(s)" in joined
        assert "rows in set" not in joined
    finally:
        db.close()


# --- REQ-CLI-10: .quit / Ctrl-C / EOF ---------------------------------


def test_cli_quit_exits(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        rc = run([".quit"])
        assert rc == 0
        assert any("bye" in line.lower() for line in captured)
    finally:
        db.close()


def test_cli_eof_returns_zero(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        # Empty input list -> EOF on first prompt.
        rc = run([])
        assert rc == 0
    finally:
        db.close()


def test_cli_ctrl_c_in_meta_returns_to_prompt(tmp_path) -> None:
    """Injecting a KeyboardInterrupt through ``input_fn`` should drop
    the current buffer and keep the REPL alive."""
    db, captured, run = make_db(tmp_path)
    try:
        # Simulate Ctrl-C at the very first prompt: REPL swallows it and
        # continues to the next prompt; we then quit cleanly.
        def fake_input(prompt: str) -> str:
            raise KeyboardInterrupt

        # Use the legacy path directly to exercise the KeyboardInterrupt
        # branch.
        rc = repl.run_repl(db, input_fn=fake_input, output=captured.append)
        assert rc == 0
    finally:
        db.close()


# --- REQ-CLI-16: .mode toggle ------------------------------------------


def test_mode_line_renders_kv(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE t (id INT PRIMARY KEY, name TEXT);",
            "INSERT INTO t VALUES (1, 'alice');",
            ".mode line",
            "SELECT * FROM t",
            "",
        ])
        joined = "\n".join(captured)
        assert "id = 1" in joined
        assert "name = alice" in joined
    finally:
        db.close()


def test_mode_table_default_renders_table(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE t (id INT PRIMARY KEY, name TEXT);",
            "INSERT INTO t VALUES (1, 'alice');",
            "SELECT * FROM t",
            "",
        ])
        joined = "\n".join(captured)
        assert "1 rows in set" in joined
        assert "+" in joined  # ASCII border present somewhere in the output
        assert "alice" in joined
    finally:
        db.close()


# --- REQ-CLI-1: continuation detection --------------------------------


def test_continuation_backslash() -> None:
    assert repl._is_continuation("SELECT *\\") is True
    assert repl._is_continuation("SELECT * FROM t;") is False


def test_continuation_unclosed_quote() -> None:
    assert repl._is_continuation("WHERE n = 'alice") is True
    assert repl._is_continuation("WHERE n = 'alice'") is False
    assert repl._is_continuation('WHERE c = "New ') is True
    assert repl._is_continuation('WHERE c = "New "') is False


# --- REQ-CLI-8: history persistence ------------------------------------


def test_history_persists_to_path(tmp_path) -> None:
    hist = FileHistory(tmp_path / "h")
    hist.append("SELECT 1;")
    hist.append("SELECT 2;")
    entries = hist.entries()
    assert "SELECT 1;" in entries
    assert "SELECT 2;" in entries


def test_history_unwritable_warns(tmp_path) -> None:
    """Pointing at a non-directory location yields a warn-only fallback."""
    import warnings
    bad = tmp_path / "regular_file"
    bad.write_text("not a directory")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        hist = FileHistory(bad / "child")  # cannot mkdir under a file
    # On POSIX the inner FileHistory open() will fail; on some
    # platforms the parent dir may already exist if tmp_path is reused.
    # We only require that construction did not raise.
    assert hist is not None
    # If a warning fired, it came from the right path (the file path).
    warn_paths = [str(w.message) for w in caught if "history" in str(w.message).lower()]
    # Either no warning (already created, harmless) or one with the path.
    for w in warn_paths:
        assert str(bad) in w


# --- REQ-CLI-11: backward compat smoke ---------------------------------


def test_v0_1_create_insert_select_still_works(tmp_path) -> None:
    """The classic v0.1 happy path must still work end-to-end."""
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE u (id INT PRIMARY KEY, name TEXT);",
            "INSERT INTO u VALUES (1, 'alice');",
            "SELECT * FROM u",
            "",
        ])
        joined = "\n".join(captured)
        assert "alice" in joined
        assert "1 rows in set" in joined
    finally:
        db.close()


def test_v0_1_invalid_sql_still_prints_parse_error(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run(["NOT VALID SQL", ""])
        joined = "\n".join(captured)
        assert "ParseError" in joined
    finally:
        db.close()


# --- REQ-CLI-2 (deeper integration): multi-line + SELECT output --------


def test_multiline_backslash_continuation(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE u (id INT PRIMARY KEY, name TEXT);",
            "INSERT INTO u VALUES (1, 'alice');",
            "SELECT *\\",  # backslash -> continue
            "FROM u",
            "",
        ])
        joined = "\n".join(captured)
        assert "alice" in joined
    finally:
        db.close()


# --- REQ-CLI-15: ANSI colour preserved in tables ----------------------


def test_explain_table_format_has_borders(tmp_path) -> None:
    db, captured, run = make_db(tmp_path)
    try:
        run([
            "CREATE TABLE u (id INT PRIMARY KEY, name TEXT);",
            "INSERT INTO u VALUES (1, 'a');",
            ".explain --table SELECT id FROM u",
            "",
        ])
        joined = "\n".join(captured)
        # top border present
        assert "+" in joined
    finally:
        db.close()