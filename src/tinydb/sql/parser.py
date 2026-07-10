"""SQL parser — DDL subset.

REQ coverage
------------
* REQ-SQL-1 — ``CREATE TABLE name (col TYPE [constraints], ...)`` and
  ``DROP TABLE [IF EXISTS] name``.
* REQ-SQL-7 — every malformed input raises :class:`ParseError` carrying
  the offending token's line / column.

Design
------
A single :class:`_Parser` walks the token stream with explicit ``peek``
/ ``advance`` / ``expect`` / ``match`` primitives.  ``expect_*`` raises
on the wrong token so the recursion never returns a half-built node.
The grammar is small enough that one class with private methods is
clearer than a forest of free functions.

Supported CREATE TABLE constraints (any order, repeatable):
    NOT NULL  |  PRIMARY KEY  |  UNIQUE

Size suffixes (``VARCHAR(50)``) are accepted and ignored — v0.1 stores
all TEXT as a length-prefixed blob and does not enforce a max length.

The DML subset (``INSERT`` / ``SELECT`` / ``UPDATE`` / ``DELETE``) lives
in later tasks (T-3.4 onwards); :func:`parse_ddl` will raise on a DML
head token so the caller can dispatch to a sibling parser.
"""

from __future__ import annotations

from typing import List

from tinydb.errors import ParseError
from tinydb.sql.ast import CreateTable, DropTable, Statement
from tinydb.sql.tokens import Token, TokenKind
from tinydb.types.system import Column, parse_type_name


# --- cursor -------------------------------------------------------------


class _Parser:
    """Recursive-descent cursor over a pre-tokenised SQL stream.

    A single ``_pos`` index walks the token list; the stream is always
    terminated by an :data:`TokenKind.EOF` token, so :meth:`_peek` and
    :meth:`_advance` are total.
    """

    def __init__(self, tokens: List[Token]) -> None:
        self._toks = tokens
        self._pos = 0

    # --- primitive cursor ops ----------------------------------------

    def _peek(self) -> Token:
        return self._toks[self._pos]

    def _advance(self) -> Token:
        tok = self._toks[self._pos]
        self._pos += 1
        return tok

    def _at_end(self) -> bool:
        return self._peek().kind is TokenKind.EOF

    # --- expect / match (raise on mismatch) --------------------------

    def _expect_kind(self, kind: TokenKind) -> Token:
        tok = self._peek()
        if tok.kind is not kind:
            raise ParseError(
                tok.line, tok.col,
                f"expected {kind.name}, got {tok.kind.name} {tok.value!r}",
            )
        return self._advance()

    def _expect_keyword(self, kw: str) -> Token:
        tok = self._peek()
        if tok.kind is not TokenKind.KEYWORD or tok.value != kw:
            raise ParseError(
                tok.line, tok.col,
                f"expected keyword {kw}, got {tok.kind.name} {tok.value!r}",
            )
        return self._advance()

    def _expect_ident(self) -> Token:
        tok = self._peek()
        if tok.kind is not TokenKind.IDENT:
            raise ParseError(
                tok.line, tok.col,
                f"expected identifier, got {tok.kind.name} {tok.value!r}",
            )
        return self._advance()

    def _match_kind(self, kind: TokenKind) -> bool:
        if self._peek().kind is kind:
            self._advance()
            return True
        return False

    def _match_keyword(self, kw: str) -> bool:
        tok = self._peek()
        if tok.kind is TokenKind.KEYWORD and tok.value == kw:
            self._advance()
            return True
        return False

    def _match_null(self) -> bool:
        """Match ``NULL`` whether the lexer emitted it as KEYWORD or NULL_LIT.

        Both spell the same SQL token and both carry the value ``None``;
        the parser must accept either form so user input round-trips.
        """
        tok = self._peek()
        if tok.kind is TokenKind.NULL_LIT:
            self._advance()
            return True
        if tok.kind is TokenKind.KEYWORD and tok.value == "NULL":
            self._advance()
            return True
        return False

    # --- DDL dispatch -------------------------------------------------

    def parse_ddl(self) -> Statement:
        """Dispatch on the leading keyword (CREATE / DROP)."""
        tok = self._peek()
        if tok.kind is TokenKind.KEYWORD and tok.value == "CREATE":
            return self._parse_create_table()
        if tok.kind is TokenKind.KEYWORD and tok.value == "DROP":
            return self._parse_drop_table()
        raise ParseError(
            tok.line, tok.col,
            f"expected CREATE or DROP, got {tok.kind.name} {tok.value!r}",
        )

    # --- CREATE TABLE -------------------------------------------------

    def _parse_create_table(self) -> CreateTable:
        self._expect_keyword("CREATE")
        self._expect_keyword("TABLE")
        name_tok = self._expect_ident()
        self._expect_kind(TokenKind.LPAREN)
        # At least one column is required; subsequent columns are comma-separated.
        cols = [self._parse_column_def()]
        while self._match_kind(TokenKind.COMMA):
            cols.append(self._parse_column_def())
        self._expect_kind(TokenKind.RPAREN)
        # Optional trailing semicolon.
        self._match_kind(TokenKind.SEMI)
        return CreateTable(name=name_tok.value, columns=tuple(cols))

    def _parse_column_def(self) -> Column:
        name_tok = self._expect_ident()
        type_tok = self._advance()
        if type_tok.kind is not TokenKind.KEYWORD:
            raise ParseError(
                type_tok.line, type_tok.col,
                f"expected type name, got {type_tok.kind.name} {type_tok.value!r}",
            )
        try:
            tag = parse_type_name(type_tok.value)
        except ValueError as exc:
            raise ParseError(type_tok.line, type_tok.col, str(exc)) from exc

        # Optional size suffix like ``VARCHAR(50)`` — accept & ignore.
        if self._match_kind(TokenKind.LPAREN):
            depth = 1
            while depth > 0 and not self._at_end():
                tok = self._advance()
                if tok.kind is TokenKind.LPAREN:
                    depth += 1
                elif tok.kind is TokenKind.RPAREN:
                    depth -= 1

        # Constraints in any order; loop until next token is not a known constraint.
        not_null = False
        primary_key = False
        unique = False
        while True:
            tok = self._peek()
            if tok.kind is not TokenKind.KEYWORD:
                break
            if tok.value == "NOT":
                self._advance()
                if not self._match_null():
                    nxt = self._peek()
                    raise ParseError(
                        nxt.line, nxt.col,
                        f"expected NULL after NOT, got {nxt.kind.name} {nxt.value!r}",
                    )
                not_null = True
                continue
            if tok.value == "PRIMARY":
                self._advance()
                self._expect_keyword("KEY")
                primary_key = True
                continue
            if tok.value == "UNIQUE":
                self._advance()
                unique = True
                continue
            break

        return Column(
            name=name_tok.value,
            tag=tag,
            not_null=not_null,
            primary_key=primary_key,
            unique=unique,
        )

    # --- DROP TABLE ---------------------------------------------------

    def _parse_drop_table(self) -> DropTable:
        self._expect_keyword("DROP")
        self._expect_keyword("TABLE")
        if_exists = False
        if self._match_keyword("IF"):
            self._expect_keyword("EXISTS")
            if_exists = True
        name_tok = self._expect_ident()
        # Optional trailing semicolon.
        self._match_kind(TokenKind.SEMI)
        return DropTable(name=name_tok.value, if_exists=if_exists)


# --- public entry point -------------------------------------------------


def parse_ddl(tokens: List[Token]) -> Statement:
    """Parse a token stream as a DDL statement.

    Returns a :class:`~tinydb.sql.ast.CreateTable` or
    :class:`~tinydb.sql.ast.DropTable`.  Raises
    :class:`~tinydb.errors.ParseError` with the offending token's line
    and column on any syntactic error.
    """
    return _Parser(tokens).parse_ddl()


__all__ = ["parse_ddl"]