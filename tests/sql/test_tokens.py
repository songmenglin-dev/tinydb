"""Tests for the SQL tokenizer — turn text into a stream of Tokens.

T-3.1 RED phase.  Covers REQ-SQL-8 (literal classification), REQ-SQL-1/2
(identifiers and keywords for DDL/DML), and REQ-SQL-7 (position
tracking that the parser uses to raise ParseError at the right spot).
"""

from __future__ import annotations

import pytest

from tinydb.errors import ParseError
from tinydb.sql.tokens import Token, TokenKind, tokenize


def _kinds_values(tokens):
    return [(t.kind, t.value) for t in tokens if t.kind != TokenKind.EOF]


# --- keywords -----------------------------------------------------------


def test_single_keyword():
    toks = tokenize("SELECT")
    assert _kinds_values(toks) == [(TokenKind.KEYWORD, "SELECT")]
    assert toks[-1].kind == TokenKind.EOF


def test_keywords_are_case_insensitive_in_value():
    """`select`, `Select`, `SELECT` all produce KEYWORD with value 'SELECT'."""
    for src in ("select FROM where", "Select From Where", "SELECT FROM WHERE"):
        toks = tokenize(src)
        assert [t.value for t in toks if t.kind != TokenKind.EOF] == [
            "SELECT", "FROM", "WHERE"
        ]


def test_keywords_separated_by_whitespace():
    toks = tokenize("INSERT  INTO   VALUES")
    assert [t.value for t in toks if t.kind != TokenKind.EOF] == [
        "INSERT", "INTO", "VALUES"
    ]


# --- identifiers --------------------------------------------------------


def test_identifier_is_lowercase_in_value():
    toks = tokenize("users _temp_col x42")
    assert _kinds_values(toks) == [
        (TokenKind.IDENT, "users"),
        (TokenKind.IDENT, "_temp_col"),
        (TokenKind.IDENT, "x42"),
    ]


def test_identifier_does_not_collide_with_keyword_only_by_value():
    """`Select` and an unquoted ident `select` both produce a token — but
    keywords must be recognised case-insensitively, so 'Select' is
    KEYWORD while 'select' as a column name would still be a KEYWORD
    (the parser resolves via context).  This test enforces the
    tokenizer's case-insensitive keyword recognition."""
    toks = tokenize("Select")
    assert toks[0].kind == TokenKind.KEYWORD
    assert toks[0].value == "SELECT"


# --- literals (REQ-SQL-8) ----------------------------------------------


def test_int_literal():
    toks = tokenize("42")
    assert toks[0].kind == TokenKind.INT_LIT
    assert toks[0].value == 42
    assert isinstance(toks[0].value, int)


def test_float_literal():
    toks = tokenize("9.99 3.0")
    assert [t.value for t in toks if t.kind != TokenKind.EOF] == [9.99, 3.0]
    assert all(t.kind == TokenKind.FLOAT_LIT for t in toks if t.kind != TokenKind.EOF)


def test_string_literal_strips_quotes():
    toks = tokenize("'hello'")
    assert toks[0].kind == TokenKind.STRING_LIT  # STRING_LIT (not STR_LIT which shadows builtin)
    assert toks[0].value == "hello"


def test_string_literal_with_escaped_quote():
    """SQL doubles a single quote to embed one — '' inside the string."""
    toks = tokenize("'it''s'")
    assert toks[0].kind == TokenKind.STRING_LIT
    assert toks[0].value == "it's"


def test_bool_literals():
    assert tokenize("TRUE")[0].value is True
    assert tokenize("FALSE")[0].value is False
    for src in ("TRUE", "False", "true"):
        kind = tokenize(src)[0].kind
        assert kind == TokenKind.BOOL_LIT


def test_null_literal():
    toks = tokenize("NULL")
    assert toks[0].kind == TokenKind.NULL_LIT
    assert toks[0].value is None


# --- operators and separators ------------------------------------------


def test_comparison_operators():
    tokens = tokenize("= != < <= > >=")
    ops = [t.value for t in tokens if t.kind == TokenKind.OP]
    assert ops == ["=", "!=", "<", "<=", ">", ">="]


def test_arithmetic_operators():
    tokens = tokenize("+ - * /")
    ops = [t.value for t in tokens if t.kind == TokenKind.OP]
    assert ops == ["+", "-", "*", "/"]


def test_separators_have_own_kinds():
    tokens = tokenize("( , ) ; .")
    kinds = [t.kind for t in tokens if t.kind != TokenKind.EOF]
    assert kinds == [
        TokenKind.LPAREN,
        TokenKind.COMMA,
        TokenKind.RPAREN,
        TokenKind.SEMI,
        TokenKind.DOT,
    ]


# --- position tracking (REQ-SQL-7 basis) -------------------------------


def test_line_and_col_start_at_one():
    toks = tokenize("SELECT")
    assert (toks[0].line, toks[0].col) == (1, 1)


def test_newline_advances_line_resets_col():
    toks = tokenize("a\nb c")
    a, b, c = (t for t in toks if t.kind != TokenKind.EOF)
    assert (a.line, a.col) == (1, 1)
    assert (b.line, b.col) == (2, 1)
    assert (c.line, c.col) == (2, 3)


def test_tokens_carry_position_across_a_realistic_query():
    """End-to-end position tracking on a multi-line SQL fragment."""
    sql = "SELECT id\nFROM users"
    toks = tokenize(sql)
    select, ident, kw_from, table = (t for t in toks if t.kind != TokenKind.EOF)
    assert (select.line, select.col) == (1, 1)
    assert (ident.line, ident.col) == (1, 8)
    assert (kw_from.line, kw_from.col) == (2, 1)
    assert (table.line, table.col) == (2, 6)


# --- error reporting (REQ-SQL-7) ---------------------------------------


def test_unterminated_string_raises_parse_error():
    with pytest.raises(ParseError) as excinfo:
        tokenize("'hello")
    msg = str(excinfo.value)
    assert "line" in msg.lower() and "col" in msg.lower()


def test_unknown_character_raises_parse_error():
    with pytest.raises(ParseError):
        tokenize("@")  # '@' is not part of the v0.1 SQL alphabet


# --- end-to-end integration --------------------------------------------


def test_full_select_query_round_trip():
    sql = "SELECT id, name FROM users WHERE age >= 18;"
    toks = tokenize(sql)
    assert _kinds_values(toks) == [
        (TokenKind.KEYWORD, "SELECT"),
        (TokenKind.IDENT, "id"),
        (TokenKind.COMMA, ","),
        (TokenKind.IDENT, "name"),
        (TokenKind.KEYWORD, "FROM"),
        (TokenKind.IDENT, "users"),
        (TokenKind.KEYWORD, "WHERE"),
        (TokenKind.IDENT, "age"),
        (TokenKind.OP, ">="),
        (TokenKind.INT_LIT, 18),
        (TokenKind.SEMI, ";"),
    ]


def test_token_is_frozen():
    """Token is frozen — assignments raise FrozenInstanceError."""
    import dataclasses

    toks = tokenize("x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        toks[0].kind = TokenKind.IDENT  # type: ignore[misc]
