"""SQL tokenizer — turn a SQL source string into a list of Tokens.

REQ coverage
------------
* REQ-SQL-7 — every Token carries ``line`` / ``col`` (1-indexed) so the
  parser can raise :class:`~tinydb.errors.ParseError` at the right spot.
* REQ-SQL-8 — the literals in the WHERE / VALUES positions are typed
  (INT / FLOAT / STRING / BOOL / NULL) at lex time; the parser can then
  decide its coercion path without re-scanning.

Design
------
A single forward cursor walks the input.  Whitespace (space / tab /
newline) is skipped.  Line comments (``-- ... \n``) and block comments
(``/* ... */``) are also skipped.  Identifiers and keywords share the
same lexer state — a run of ``[A-Za-z_][A-Za-z0-9_]*`` is a KEYWORD
iff its uppercase form is in :data:`KEYWORDS`, otherwise IDENT.  This
matches SQL's case-insensitive keywords + case-sensitive identifiers.

String literals use single-quotes; an embedded single quote is doubled
(``'it''s'`` -> ``it's``) per the SQL standard.  Comments inside string
literals are not honoured — the lexer is greedy on ``'``.

A trailing EOF token marks the end of the stream so the parser can stop
without an extra ``len(tokens) - 1`` check.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, List

from tinydb.errors import ParseError


# --- Token value types --------------------------------------------------


class TokenKind(Enum):
    """Classification of a single Token.

    Members are referenced by name on every parse / error path; the
    string values are not part of the wire format and may change.
    """

    KEYWORD = "KEYWORD"
    IDENT = "IDENT"
    INT_LIT = "INT_LIT"
    FLOAT_LIT = "FLOAT_LIT"
    STRING_LIT = "STRING_LIT"  # named to avoid shadowing builtin `str`
    BOOL_LIT = "BOOL_LIT"
    NULL_LIT = "NULL_LIT"
    OP = "OP"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    COMMA = "COMMA"
    SEMI = "SEMI"
    DOT = "DOT"
    EOF = "EOF"


@dataclass(frozen=True, slots=True)
class Token:
    """A single lexeme with its source position.

    Attributes
    ----------
    kind : TokenKind
    value : Any
        For literals the Python native value (int / float / str / bool /
        None).  For IDENT / KEYWORD / OP the canonical string.  For
        separators and EOF: ``None``.
    line, col : int
        1-indexed source position of the first character of the lexeme.
    """

    kind: TokenKind
    value: Any
    line: int
    col: int


# --- SQL keyword set ----------------------------------------------------
#
# All keywords recognised by the lexer.  The parser consults this set
# implicitly via token.kind == TokenKind.KEYWORD; the actual keyword
# name lives in ``token.value`` (always upper-case).

KEYWORDS: frozenset = frozenset({
    # DDL
    "CREATE", "TABLE", "DROP", "ALTER", "IF", "EXISTS",
    # DML
    "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE",
    "SELECT", "FROM", "WHERE", "ORDER", "BY", "GROUP", "HAVING",
    "LIMIT", "OFFSET", "ASC", "DESC", "AS", "ON",
    # Expressions
    "AND", "OR", "NOT", "IS", "NULL", "LIKE", "IN", "BETWEEN",
    "TRUE", "FALSE",
    # Joins (out of v0.1 scope but reserved for future)
    "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "FULL",
    # Type names (used in CREATE TABLE column defs)
    "INT", "INTEGER", "FLOAT", "DOUBLE", "REAL", "TEXT", "VARCHAR",
    "BOOL", "BOOLEAN", "DATE", "TIME", "DATETIME", "TIMESTAMP",
    "DECIMAL", "NUMERIC", "BLOB", "BYTEA", "JSON",
    # Constraints
    "PRIMARY", "KEY", "UNIQUE", "DEFAULT", "CHECK", "INDEX",
    # Aggregates
    "COUNT", "SUM", "AVG", "MIN", "MAX",
})


# --- multi-character operators (sorted longest-first) -----------------
_MULTI_CHAR_OPS: tuple = (">=", "<=", "!=")


# --- main entry point ---------------------------------------------------


def tokenize(sql: str) -> List[Token]:
    """Lex ``sql`` into a list of Tokens terminated by an EOF token.

    Raises :class:`~tinydb.errors.ParseError` for unterminated string
    literals or unrecognised characters.  Error messages include the
    line / column of the offending position.
    """
    tokens: list = []
    line = 1
    col = 1
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]

        # --- whitespace ---
        if ch in " \t\r":
            i += 1
            col += 1
            continue
        if ch == "\n":
            i += 1
            line += 1
            col = 1
            continue

        # --- line comment: -- ... \n ---
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue
        # --- block comment: /* ... */ ---
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            col += 2
            depth = 1
            while i < n and depth > 0:
                if sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
                    depth -= 1
                    i += 2
                    col += 2
                    continue
                if sql[i] == "/" and i + 1 < n and sql[i + 1] == "*":
                    # v0.1 does NOT support nested block comments; treat
                    # the inner /* as ordinary content.  This is
                    # deliberate — keeps the lexer linear and simple.
                    i += 2
                    col += 2
                    continue
                if sql[i] == "\n":
                    line += 1
                    col = 1
                else:
                    col += 1
                i += 1
            if depth > 0:
                raise ParseError(line, col, "unterminated block comment")
            continue

        token_line, token_col = line, col

        # --- string literal: '...' (SQL '' escape) ---
        if ch == "'":
            i += 1
            col += 1
            buf: list = []
            while i < n:
                if sql[i] == "'":
                    # SQL-standard escape: '' -> '.
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        col += 2
                        continue
                    # Otherwise, closing quote.
                    break
                if sql[i] == "\n":
                    line += 1
                    col = 1
                else:
                    col += 1
                buf.append(sql[i])
                i += 1
            if i >= n:
                raise ParseError(token_line, token_col, "unterminated string literal")
            # Consume closing quote.
            i += 1
            col += 1
            tokens.append(Token(TokenKind.STRING_LIT, "".join(buf), token_line, token_col))
            continue

        # --- identifier / keyword: [A-Za-z_][A-Za-z0-9_]* ---
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            col += 1
            while i < n and (sql[i].isalnum() or sql[i] == "_"):
                i += 1
                col += 1
            text = sql[start:i]
            upper = text.upper()
            if upper in KEYWORDS:
                if upper == "TRUE":
                    tokens.append(Token(TokenKind.BOOL_LIT, True, token_line, token_col))
                elif upper == "FALSE":
                    tokens.append(Token(TokenKind.BOOL_LIT, False, token_line, token_col))
                elif upper == "NULL":
                    tokens.append(Token(TokenKind.NULL_LIT, None, token_line, token_col))
                else:
                    tokens.append(Token(TokenKind.KEYWORD, upper, token_line, token_col))
            else:
                tokens.append(Token(TokenKind.IDENT, text, token_line, token_col))
            continue

        # --- number ---
        if ch.isdigit():
            start = i
            i += 1
            col += 1
            is_float = False
            while i < n and (sql[i].isdigit() or (sql[i] == "." and not is_float)):
                if sql[i] == ".":
                    is_float = True
                i += 1
                col += 1
            text = sql[start:i]
            if is_float:
                tokens.append(Token(TokenKind.FLOAT_LIT, float(text), token_line, token_col))
            else:
                tokens.append(Token(TokenKind.INT_LIT, int(text), token_line, token_col))
            continue

        # --- operators ---
        # Try multi-char first.
        matched = False
        for op in _MULTI_CHAR_OPS:
            if sql.startswith(op, i):
                tokens.append(Token(TokenKind.OP, op, token_line, token_col))
                i += len(op)
                col += len(op)
                matched = True
                break
        if matched:
            continue
        if ch in "+-*/<>=":
            tokens.append(Token(TokenKind.OP, ch, token_line, token_col))
            i += 1
            col += 1
            continue

        # --- separators ---
        if ch == "(":
            tokens.append(Token(TokenKind.LPAREN, "(", token_line, token_col))
            i += 1
            col += 1
            continue
        if ch == ")":
            tokens.append(Token(TokenKind.RPAREN, ")", token_line, token_col))
            i += 1
            col += 1
            continue
        if ch == ",":
            tokens.append(Token(TokenKind.COMMA, ",", token_line, token_col))
            i += 1
            col += 1
            continue
        if ch == ";":
            tokens.append(Token(TokenKind.SEMI, ";", token_line, token_col))
            i += 1
            col += 1
            continue
        if ch == ".":
            tokens.append(Token(TokenKind.DOT, ".", token_line, token_col))
            i += 1
            col += 1
            continue

        # --- unknown ---
        raise ParseError(line, col, f"unexpected character {ch!r}")

    tokens.append(Token(TokenKind.EOF, None, line, col))
    return tokens


__all__ = ["KEYWORDS", "Token", "TokenKind", "tokenize"]
