"""Tests for SQL parser error reporting (REQ-SQL-7).

T-3.7 RED phase.  Verifies that :class:`ParseError`:

* carries accurate 1-indexed ``line`` / ``col`` of the offending token
* exposes a ``snippet(sql)`` helper that returns the offending line
  plus a caret pointer for human-friendly error messages
* is reachable via a single top-level ``parse(sql) -> Statement`` that
  auto-dispatches to DDL / DML based on the leading keyword

Also covers the lex-time error path (unclosed string quote) and the
parse-time error path (missing keyword) via the public wrapper.
"""

from __future__ import annotations

import pytest

from tinydb.errors import ParseError
from tinydb.sql.parser import parse, parse_ddl_string, parse_dml_string
from tinydb.sql.tokens import tokenize


# --- top-level parse(sql) dispatch -------------------------------------


@pytest.mark.unit
def test_parse_dispatches_to_ddl_create():
    stmt = parse("CREATE TABLE t (id INT)")
    assert stmt.name == "t"


@pytest.mark.unit
def test_parse_dispatches_to_ddl_drop():
    stmt = parse("DROP TABLE t")
    assert stmt.name == "t"


@pytest.mark.unit
def test_parse_dispatches_to_dml_insert():
    stmt = parse("INSERT INTO t VALUES (1)")
    assert stmt.table == "t"


@pytest.mark.unit
def test_parse_dispatches_to_dml_select():
    stmt = parse("SELECT * FROM t")
    assert stmt.table == "t"


@pytest.mark.unit
def test_parse_dispatches_to_dml_update():
    stmt = parse("UPDATE t SET a = 1")
    assert stmt.table == "t"


@pytest.mark.unit
def test_parse_dispatches_to_dml_delete():
    stmt = parse("DELETE FROM t")
    assert stmt.table == "t"


@pytest.mark.unit
def test_parse_ddl_string_wrapper_tokenizes_and_parses():
    stmt = parse_ddl_string("CREATE TABLE users (id INT PRIMARY KEY)")
    assert stmt.columns[0].primary_key is True


@pytest.mark.unit
def test_parse_dml_string_wrapper_tokenizes_and_parses():
    stmt = parse_dml_string("SELECT id FROM users WHERE id = 1")
    assert stmt.table == "users"


# --- error position: line / col accuracy --------------------------------


@pytest.mark.unit
def test_parse_error_reports_correct_line_for_multiline_sql():
    """The parser must point at the actual line of the offender, not
    always line 1.  The bad token (``WHERE`` typo on line 3) is
    reported on line 3."""
    sql = (
        "SELECT *\n"
        "FROM t\n"
        "WHER id = 1\n"
    )
    with pytest.raises(ParseError) as excinfo:
        parse(sql)
    err = excinfo.value
    assert err.line == 3


@pytest.mark.unit
def test_parse_error_reports_column_of_missing_keyword():
    """``SELECT * users`` — missing FROM at col 10."""
    with pytest.raises(ParseError) as excinfo:
        parse("SELECT * users")
    err = excinfo.value
    assert err.line == 1
    assert err.col == 10
    assert "users" in err.msg


@pytest.mark.unit
def test_parse_error_reports_column_of_bad_type():
    """``CREATE TABLE t (x FOO)`` — bad type name at col 19."""
    with pytest.raises(ParseError) as excinfo:
        parse("CREATE TABLE t (x FOO)")
    err = excinfo.value
    assert err.line == 1
    assert err.col == 19


@pytest.mark.unit
def test_parse_rejects_trailing_garbage_after_valid_statement():
    """v0.1 is single-statement: extra tokens after the parsed
    statement are reported as a trailing-token error."""
    with pytest.raises(ParseError) as excinfo:
        parse("SELECT * FROM t WHER id = 1")
    err = excinfo.value
    # WHER is at col 17; error reports its position.
    assert err.col == 17
    assert "WHER" in str(excinfo.value)


# --- lex-time error: unclosed string quote (REQ-SQL-7) -----------------


@pytest.mark.unit
def test_unclosed_string_quote_raises_parse_error():
    """``INSERT INTO t VALUES ('abc)`` — lexer must raise."""
    with pytest.raises(ParseError) as excinfo:
        parse("INSERT INTO t VALUES ('abc)")
    err = excinfo.value
    assert err.line == 1
    assert "string" in err.msg.lower() or "unterminated" in err.msg.lower()


# --- snippet: source context with caret pointer -----------------------


@pytest.mark.unit
def test_parse_error_snippet_returns_offending_line_and_caret():
    sql = "SELECT * users"
    with pytest.raises(ParseError) as excinfo:
        parse(sql)
    snippet = excinfo.value.snippet(sql)
    # Line of source + a marker line with caret at the right column.
    assert "SELECT * users" in snippet
    assert "^" in snippet


@pytest.mark.unit
def test_parse_error_snippet_truncates_long_lines():
    """Long lines must not explode the snippet; the caret position is
    what matters for the user."""
    sql = "SELECT * " + "x" * 200 + " users"
    with pytest.raises(ParseError):
        parse(sql)
    snippet = ""
    try:
        parse(sql)
    except ParseError as err:
        snippet = err.snippet(sql)
    # The caret line must remain anchored near the start (the error is
    # near col 200, but the snippet must stay readable).
    assert "^" in snippet
    # Length bound: source line may be capped.
    assert len(snippet) < 500


# --- error message quality ----------------------------------------------


@pytest.mark.unit
def test_parse_error_message_includes_offending_token_value():
    """Error messages must quote the bad token to help users locate it.
    Trailing-token errors surface the offending lexeme."""
    with pytest.raises(ParseError) as excinfo:
        parse("SELECT * FROM t LIMOT 10")  # LIMOT instead of LIMIT
    assert "LIMOT" in str(excinfo.value)


@pytest.mark.unit
def test_parse_error_message_includes_expected_kind():
    with pytest.raises(ParseError) as excinfo:
        parse("CREATE TABLE t (id)")
    assert "type" in str(excinfo.value).lower()


# --- explicit dispatcher failures ---------------------------------------


@pytest.mark.unit
def test_parse_ddl_rejects_dml_statement():
    """``parse_ddl_string`` is DDL-only; an INSERT must be rejected."""
    with pytest.raises(ParseError):
        parse_ddl_string("INSERT INTO t VALUES (1)")


@pytest.mark.unit
def test_parse_dml_rejects_ddl_statement():
    """``parse_dml_string`` is DML-only; a CREATE must be rejected."""
    with pytest.raises(ParseError):
        parse_dml_string("CREATE TABLE t (id INT)")


@pytest.mark.unit
def test_parse_rejects_unknown_leading_keyword():
    with pytest.raises(ParseError):
        parse("ALTER TABLE t ADD COLUMN x INT")