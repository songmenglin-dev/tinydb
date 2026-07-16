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

import datetime
import json
from decimal import Decimal
from typing import List, Optional

from tinydb.errors import ParseError
from tinydb.sql.ast import (
    Aggregate,
    Assignment,
    BinaryOp,
    ColumnRef,
    CreateIndex,
    CreateTable,
    Delete,
    DropTable,
    Expr,
    Insert,
    Join,
    JoinKind,
    Literal,
    OrderBy,
    Select,
    Star,
    Statement,
    Table,
    TableRef,
    TypedLiteral,
    UnaryOp,
    Update,
)
from tinydb.sql.tokens import Token, TokenKind, tokenize
from tinydb.types.system import Column, TypeTag, parse_type_name


# Operator sets used by the expression precedence ladder.
_COMPARISON_OPS: frozenset = frozenset({"=", "!=", "<", "<=", ">", ">="})
_ADDITIVE_OPS: frozenset = frozenset({"+", "-"})
_MULTIPLICATIVE_OPS: frozenset = frozenset({"*", "/"})


# REQ-JOIN-5: JOIN nesting depth cap.  The first JOIN sets depth 1; each
# subsequent JOIN increments depth.  Wrapping it as a left-leaning tree
# means the parser emits at most ``depth`` Join nodes.
_JOIN_MAX_DEPTH: int = 5


# Mapping from typed-literal keyword → (TypeTag, parser).  Each parser
# takes the raw string content (without the surrounding quotes) and
# returns the corresponding Python native value, raising ParseError on
# malformed input.
_TYPED_LITERAL_PARSERS: dict = {
    "DATE": (TypeTag.Date, lambda s: datetime.date.fromisoformat(s)),
    "TIME": (TypeTag.Time, lambda s: datetime.time.fromisoformat(s)),
    "DATETIME": (
        TypeTag.Datetime,
        # datetime.fromisoformat accepts both 'YYYY-MM-DD' and
        # 'YYYY-MM-DDTHH:MM:SS[.ffffff]' but historically rejected the
        # space-separated form until 3.11; we normalise ' ' → 'T' so
        # both spellings parse on every supported Python version.
        lambda s: datetime.datetime.fromisoformat(s.replace(" ", "T")),
    ),
    "DECIMAL": (TypeTag.Decimal, lambda s: Decimal(s)),
    "BLOB": (TypeTag.Blob, lambda s: bytes.fromhex(s)),
    "JSON": (TypeTag.Json, lambda s: json.loads(s)),
}


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

    def position(self) -> int:
        """Current cursor index (number of tokens already consumed)."""
        return self._pos

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
            return self._parse_create_or_index()
        if tok.kind is TokenKind.KEYWORD and tok.value == "DROP":
            return self._parse_drop_table()
        raise ParseError(
            tok.line, tok.col,
            f"expected CREATE or DROP, got {tok.kind.name} {tok.value!r}",
        )

    def _parse_create_or_index(self) -> Statement:
        self._expect_keyword("CREATE")
        nxt = self._peek()
        if nxt.kind is TokenKind.KEYWORD and nxt.value == "TABLE":
            return self._parse_create_table()
        # Both ``CREATE INDEX`` and ``CREATE UNIQUE INDEX`` route here;
        # the inner parser consumes INDEX (and optional UNIQUE).
        if nxt.kind is TokenKind.KEYWORD and nxt.value in ("INDEX", "UNIQUE"):
            return self._parse_create_index()
        raise ParseError(
            nxt.line, nxt.col,
            f"expected TABLE or INDEX, got {nxt.kind.name} {nxt.value!r}",
        )

    def _parse_create_index(self) -> Statement:
        """``CREATE [UNIQUE] INDEX <name> ON <table> (<col>)``"""
        # The dispatch only peeked; here we consume the actual keyword
        # sequence.  For ``CREATE INDEX`` we see INDEX next; for
        # ``CREATE UNIQUE INDEX`` we see UNIQUE first.
        unique = False
        nxt = self._peek()
        if nxt.kind is TokenKind.KEYWORD and nxt.value == "UNIQUE":
            self._advance()
            unique = True
        self._expect_keyword("INDEX")
        name_tok = self._expect_ident()
        self._expect_keyword("ON")
        table_tok = self._expect_ident()
        self._expect_kind(TokenKind.LPAREN)
        col_tok = self._expect_ident()
        self._expect_kind(TokenKind.RPAREN)
        self._match_kind(TokenKind.SEMI)
        return CreateIndex(
            name=name_tok.value,
            table=table_tok.value,
            columns=(col_tok.value,),
            unique=unique,
        )

    # --- CREATE TABLE -------------------------------------------------

    def _parse_create_table(self) -> CreateTable:
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

    # --- DML dispatch (T-3.4b) -------------------------------------

    def parse_dml(self) -> Statement:
        """Dispatch on the leading keyword (INSERT/SELECT/UPDATE/DELETE)."""
        tok = self._peek()
        if tok.kind is TokenKind.KEYWORD:
            if tok.value == "INSERT":
                return self._parse_insert()
            if tok.value == "SELECT":
                return self._parse_select()
            if tok.value == "UPDATE":
                return self._parse_update()
            if tok.value == "DELETE":
                return self._parse_delete()
        raise ParseError(
            tok.line, tok.col,
            f"expected DML keyword (INSERT/SELECT/UPDATE/DELETE), "
            f"got {tok.kind.name} {tok.value!r}",
        )

    # --- INSERT -----------------------------------------------------

    def _parse_insert(self) -> Insert:
        self._expect_keyword("INSERT")
        self._expect_keyword("INTO")
        name_tok = self._expect_ident()
        # Optional column list — ``(col1, col2, ...)``.
        columns: Optional[tuple] = None
        if self._match_kind(TokenKind.LPAREN):
            cols = [self._expect_ident().value]
            while self._match_kind(TokenKind.COMMA):
                cols.append(self._expect_ident().value)
            self._expect_kind(TokenKind.RPAREN)
            columns = tuple(cols)
        self._expect_keyword("VALUES")
        # One or more comma-separated value tuples.
        values = [self._parse_value_tuple()]
        while self._match_kind(TokenKind.COMMA):
            values.append(self._parse_value_tuple())
        # Optional trailing semicolon.
        self._match_kind(TokenKind.SEMI)
        return Insert(table=name_tok.value, columns=columns, values=tuple(values))

    def _parse_value_tuple(self) -> tuple:
        """``(v1, v2, ...)`` — comma-separated literals for one row."""
        self._expect_kind(TokenKind.LPAREN)
        vals = [self._parse_value()]
        while self._match_kind(TokenKind.COMMA):
            vals.append(self._parse_value())
        self._expect_kind(TokenKind.RPAREN)
        return tuple(vals)

    def _parse_value(self):
        """A literal value in an INSERT VALUES list.

        Accepts plain :class:`Literal` (unwrapped to its Python value)
        AND type-prefixed :class:`TypedLiteral` (preserved as the AST
        node so the executor can dispatch on the declared target tag —
        REQ-TYP-9..14).  Arithmetic / column-ref expressions remain
        rejected.
        """
        node = self._parse_primary()
        if isinstance(node, TypedLiteral):
            return node  # keep tag + value; executor picks it up
        if isinstance(node, Literal):
            return node.value
        raise ParseError(
            node.__class__.__name__, 0,
            f"INSERT VALUES expects a literal, got expression node",
        )

    # --- SELECT -----------------------------------------------------

    # Aggregate function names that take a column or ``*`` argument.
    _AGGREGATE_FUNCS: frozenset = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX"})

    def _parse_select(self) -> Select:
        self._expect_keyword("SELECT")
        columns = self._parse_select_columns()
        self._expect_keyword("FROM")
        from_ref = self._parse_from_clause(depth=0)
        where: Optional[Expr] = None
        if self._match_keyword("WHERE"):
            where = self.parse_expr()
        # GROUP BY <cols>
        group_by: tuple = ()
        if self._match_keyword("GROUP"):
            self._expect_keyword("BY")
            group_by = self._parse_ident_list()
        # ORDER BY <col> [ASC|DESC] [, ...]
        order_by: tuple = ()
        if self._match_keyword("ORDER"):
            self._expect_keyword("BY")
            order_by = self._parse_order_by_list()
        # LIMIT n [OFFSET m]
        limit: Optional[int] = None
        offset: Optional[int] = None
        if self._match_keyword("LIMIT"):
            limit = self._expect_kind(TokenKind.INT_LIT).value
            if self._match_keyword("OFFSET"):
                offset = self._expect_kind(TokenKind.INT_LIT).value
        # Optional trailing semicolon.
        self._match_kind(TokenKind.SEMI)
        return Select(
            columns=columns,
            from_=from_ref,
            where=where,
            order_by=order_by,
            limit=limit,
            offset=offset,
            group_by=group_by,
        )

    # --- FROM / JOIN (T-10.2..10.4) ----------------------------------

    def _parse_from_clause(self, depth: int) -> TableRef:
        """Parse a single-table or joined FROM clause.

        ``depth`` is the number of Join wrappers already built around
        ``left`` (0 for a bare table).  REQ-JOIN-5 caps it at
        :data:`_JOIN_MAX_DEPTH`; the 6th Join would create a 6-level
        nesting tree and triggers the error.
        """
        left = self._parse_table_ref()
        while self._peek_is_join_start():
            # The new Join will wrap ``left`` and become the new
            # left; its depth is ``depth + 1``.  Reject before parsing.
            if depth + 1 > _JOIN_MAX_DEPTH:
                tok = self._peek()
                raise ParseError(
                    tok.line, tok.col,
                    "JOIN nesting depth exceeds 5",
                )
            join = self._parse_one_join(left, depth=depth)
            left = join
            depth += 1
        return left

    def _peek_is_join_start(self) -> bool:
        tok = self._peek()
        if tok.kind is not TokenKind.KEYWORD:
            return False
        # Recognise ``[INNER|LEFT [OUTER]]? JOIN`` but NOT ``INNER``
        # by itself or other keywords that merely happen to share the
        # spelling.  We require the next non-trivia token to be JOIN.
        if tok.value in ("INNER", "JOIN", "LEFT", "CROSS"):
            return True
        return False

    def _parse_one_join(self, left: TableRef, depth: int) -> Join:
        """Consume one ``[INNER|LEFT [OUTER]]? JOIN ...`` chunk.

        ``depth`` is the depth at which this Join will sit; left-leaning
        construction means the parent sees ``(left ⋈ right)`` as its
        own left operand.  Caller increments depth after this returns.
        """
        # Optional JOIN-kind modifiers.  Order: [INNER|LEFT] OUTER? JOIN.
        # We support the three forms called out in REQ-JOIN-1/2:
        #   INNER JOIN | JOIN | LEFT JOIN | LEFT OUTER JOIN
        kind = JoinKind.INNER  # default
        if self._match_keyword("INNER"):
            kind = JoinKind.INNER
        elif self._match_keyword("LEFT"):
            kind = JoinKind.LEFT
            self._match_keyword("OUTER")  # optional
        elif self._match_keyword("RIGHT"):
            tok = self._peek()
            raise ParseError(
                tok.line, tok.col,
                "RIGHT JOIN is not supported in v0.2",
            )
        elif self._match_keyword("FULL"):
            tok = self._peek()
            raise ParseError(
                tok.line, tok.col,
                "FULL JOIN is not supported in v0.2",
            )
        elif self._match_keyword("CROSS"):
            tok = self._peek()
            raise ParseError(
                tok.line, tok.col,
                "CROSS JOIN is not supported in v0.2",
            )
        # JOIN keyword is required.
        self._expect_keyword("JOIN")
        right = self._parse_table_ref()
        on_expr, using_cols = self._parse_join_condition()
        return Join(
            left=left,
            right=right,
            kind=kind,
            on_expr=on_expr,
            using=using_cols,
            nullable_right=(kind == JoinKind.LEFT),
        )

    def _parse_table_ref(self) -> TableRef:
        """One ``[schema.]table [alias]`` reference — no JOIN clauses."""
        name_tok = self._expect_ident()
        alias: Optional[str] = None
        # Accept optional AS keyword between name and alias: ``t AS u``.
        self._match_keyword("AS")
        nxt = self._peek()
        if nxt.kind is TokenKind.IDENT and self._is_alias_position():
            alias = self._advance().value
        return Table(name=name_tok.value, alias=alias)

    def _is_alias_position(self) -> bool:
        """Heuristic: the next IDENT is an alias iff it's not a keyword.

        This avoids stealing the keyword in ``WHERE`` / ``GROUP`` / etc.;
        we peek one more token to see whether the IDENT is followed by
        another clause-starting keyword (``AS``, ``ON``, ``USING``,
        ``WHERE``, ``GROUP``, ``ORDER``, ``LIMIT``, ``SEMI``, ``EOF``).
        """
        # If the next token isn't an IDENT this is irrelevant.
        if self._peek().kind is not TokenKind.IDENT:
            return False
        # Look one token ahead without consuming.
        if self._pos + 1 >= len(self._toks):
            return True
        nxt = self._toks[self._pos + 1]
        if nxt.kind is TokenKind.KEYWORD and nxt.value in (
            "AS", "ON", "USING", "WHERE", "GROUP", "ORDER",
            "LIMIT", "LEFT", "INNER", "JOIN", "RIGHT", "FULL",
            "CROSS", "OUTER",
        ):
            return True
        if nxt.kind is TokenKind.SEMI or nxt.kind is TokenKind.EOF:
            return True
        # Comma / RPAREN — end of FROM list or subexpr; not an alias.
        return False

    def _parse_join_condition(self) -> tuple:
        """``ON <expr>`` or ``USING (col, col, ...)`` — exactly one.

        Returns ``(on_expr, using_tuple)`` — exactly one is set; the
        other is ``None`` / ``()``.  Missing both raises ParseError
        (REQ-JOIN-1).
        """
        if self._match_keyword("ON"):
            return (self.parse_expr(), ())
        if self._match_keyword("USING"):
            self._expect_kind(TokenKind.LPAREN)
            cols = [self._expect_ident().value]
            while self._match_kind(TokenKind.COMMA):
                cols.append(self._expect_ident().value)
            self._expect_kind(TokenKind.RPAREN)
            return (None, tuple(cols))
        tok = self._peek()
        raise ParseError(
            tok.line, tok.col,
            "JOIN requires ON or USING clause",
        )

    def _parse_select_columns(self) -> tuple:
        """Either ``*`` (Star sentinel) or one-or-more comma-separated items."""
        tok = self._peek()
        if tok.kind is TokenKind.OP and tok.value == "*":
            self._advance()
            return (Star(),)
        cols = [self._parse_select_item()]
        while self._match_kind(TokenKind.COMMA):
            cols.append(self._parse_select_item())
        return tuple(cols)

    def _parse_select_item(self) -> Expr:
        """One column-list entry: aggregate function or arbitrary expr."""
        tok = self._peek()
        if (
            tok.kind is TokenKind.KEYWORD
            and tok.value in self._AGGREGATE_FUNCS
        ):
            return self._parse_aggregate()
        return self.parse_expr()

    def _parse_aggregate(self) -> Aggregate:
        """``FUNC '(' ( '*' | IDENT ) ')'`` — e.g. ``COUNT(*)``, ``SUM(amount)``."""
        func_tok = self._expect_keyword_one_of(self._AGGREGATE_FUNCS)
        self._expect_kind(TokenKind.LPAREN)
        arg_tok = self._peek()
        if arg_tok.kind is TokenKind.OP and arg_tok.value == "*":
            self._advance()
            column = "*"
        elif arg_tok.kind is TokenKind.IDENT:
            self._advance()
            column = arg_tok.value
        else:
            raise ParseError(
                arg_tok.line, arg_tok.col,
                f"expected column name or '*' inside aggregate, got "
                f"{arg_tok.kind.name} {arg_tok.value!r}",
            )
        self._expect_kind(TokenKind.RPAREN)
        return Aggregate(func=func_tok.value, column=column)

    def _parse_order_by_list(self) -> tuple:
        items = [self._parse_order_by_item()]
        while self._match_kind(TokenKind.COMMA):
            items.append(self._parse_order_by_item())
        return tuple(items)

    def _parse_order_by_item(self) -> OrderBy:
        col_tok = self._expect_ident()
        descending = False
        if self._match_keyword("DESC"):
            descending = True
        elif self._match_keyword("ASC"):
            descending = False  # explicit ASC; default already False
        return OrderBy(column=col_tok.value, descending=descending)

    def _parse_ident_list(self) -> tuple:
        """Comma-separated IDENT list — used by GROUP BY and similar."""
        cols = [self._expect_ident().value]
        while self._match_kind(TokenKind.COMMA):
            cols.append(self._expect_ident().value)
        return tuple(cols)

    def _expect_keyword_one_of(self, choices: frozenset) -> Token:
        """Consume a KEYWORD whose value is in ``choices``; raise otherwise."""
        tok = self._peek()
        if tok.kind is not TokenKind.KEYWORD or tok.value not in choices:
            raise ParseError(
                tok.line, tok.col,
                f"expected one of {sorted(choices)}, got "
                f"{tok.kind.name} {tok.value!r}",
            )
        return self._advance()

    # --- UPDATE -----------------------------------------------------

    def _parse_update(self) -> Update:
        self._expect_keyword("UPDATE")
        table_tok = self._expect_ident()
        self._expect_keyword("SET")
        set_clauses = [self._parse_assignment()]
        while self._match_kind(TokenKind.COMMA):
            set_clauses.append(self._parse_assignment())
        where: Optional[Expr] = None
        if self._match_keyword("WHERE"):
            where = self.parse_expr()
        self._match_kind(TokenKind.SEMI)
        return Update(
            table=table_tok.value, set_clauses=tuple(set_clauses), where=where,
        )

    def _parse_assignment(self) -> Assignment:
        col_tok = self._expect_ident()
        self._expect_kind(TokenKind.OP)  # '='
        value = self.parse_expr()
        return Assignment(column=col_tok.value, value=value)

    # --- DELETE -----------------------------------------------------

    def _parse_delete(self) -> Delete:
        self._expect_keyword("DELETE")
        self._expect_keyword("FROM")
        table_tok = self._expect_ident()
        where: Optional[Expr] = None
        if self._match_keyword("WHERE"):
            where = self.parse_expr()
        self._match_kind(TokenKind.SEMI)
        return Delete(table=table_tok.value, where=where)

    # --- expression parser (T-3.4a) --------------------------------
    #
    # Precedence ladder, lowest → highest:
    #   OR  >  AND  >  NOT  >  comparison / IS [NOT] NULL  >
    #   additive  >  multiplicative  >  unary-minus  >  primary
    #
    # Each level consumes one tighter level on the left/right and
    # left-folds repeated same-precedence operators.

    def parse_expr(self) -> Expr:
        """Parse a full expression starting at the cursor."""
        return self._parse_or()

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._match_keyword("OR"):
            right = self._parse_and()
            left = BinaryOp(op="OR", left=left, right=right)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_not()
        while self._match_keyword("AND"):
            right = self._parse_not()
            left = BinaryOp(op="AND", left=left, right=right)
        return left

    def _parse_not(self) -> Expr:
        if self._match_keyword("NOT"):
            operand = self._parse_not()  # NOT is right-associative
            return UnaryOp(op="NOT", operand=operand)
        return self._parse_comparison()

    def _parse_comparison(self) -> Expr:
        left = self._parse_additive()
        # IS [NOT] NULL — unary form, lives at the comparison level.
        if self._match_keyword("IS"):
            negated = self._match_keyword("NOT")
            if not self._match_null():
                tok = self._peek()
                raise ParseError(
                    tok.line, tok.col,
                    f"expected NULL after IS, got {tok.kind.name} {tok.value!r}",
                )
            return UnaryOp(
                op="IS NOT NULL" if negated else "IS NULL",
                operand=left,
            )
        # Standard comparison operators (left-assoc within the level).
        op = self._match_op_in(_COMPARISON_OPS)
        if op is not None:
            right = self._parse_additive()
            return BinaryOp(op=op, left=left, right=right)
        return left

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while True:
            op = self._match_op_in(_ADDITIVE_OPS)
            if op is None:
                break
            right = self._parse_multiplicative()
            left = BinaryOp(op=op, left=left, right=right)
        return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while True:
            op = self._match_op_in(_MULTIPLICATIVE_OPS)
            if op is None:
                break
            right = self._parse_unary()
            left = BinaryOp(op=op, left=left, right=right)
        return left

    def _parse_unary(self) -> Expr:
        # Unary minus is right-recursive so ``--x`` and ``-(a + b)`` work.
        tok = self._peek()
        if tok.kind is TokenKind.OP and tok.value == "-":
            self._advance()
            operand = self._parse_unary()
            return UnaryOp(op="-", operand=operand)
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        tok = self._peek()
        # Type-prefixed literals (DATE '...', DECIMAL '...', ...) — must
        # be tried before the bare-literal branch because the leading
        # token is a KEYWORD, not a *_LIT kind.
        if tok.kind is TokenKind.KEYWORD and tok.value in _TYPED_LITERAL_PARSERS:
            return self._parse_typed_literal(tok.value)
        # Literals — value already typed by the lexer.
        if tok.kind in (
            TokenKind.INT_LIT, TokenKind.FLOAT_LIT, TokenKind.STRING_LIT,
            TokenKind.BOOL_LIT, TokenKind.NULL_LIT,
        ):
            return self._parse_literal()
        # Parenthesised sub-expression.
        if tok.kind is TokenKind.LPAREN:
            self._advance()
            inner = self.parse_expr()
            self._expect_kind(TokenKind.RPAREN)
            return inner
        # IDENT — bare column or qualified ``t.col``.
        if tok.kind is TokenKind.IDENT:
            self._advance()
            if self._match_kind(TokenKind.DOT):
                col_tok = self._peek()
                if col_tok.kind is not TokenKind.IDENT:
                    raise ParseError(
                        col_tok.line, col_tok.col,
                        f"expected column name after '.', got "
                        f"{col_tok.kind.name} {col_tok.value!r}",
                    )
                self._advance()
                return ColumnRef(name=col_tok.value, table=tok.value)
            return ColumnRef(name=tok.value)
        raise ParseError(
            tok.line, tok.col,
            f"expected expression, got {tok.kind.name} {tok.value!r}",
        )

    def _parse_typed_literal(self, keyword: str) -> TypedLiteral:
        """Parse ``DATE '...'`` / ``DECIMAL '...'`` / etc. into a TypedLiteral.

        The leading keyword has already been peeked; consume it, then
        expect a single STRING_LIT, validate its content via the
        keyword-specific parser in :data:`_TYPED_LITERAL_PARSERS`, and
        return the wrapped node.  A missing string or a validation
        failure raises ParseError at the offending token.
        """
        kw_tok = self._advance()
        tag, value_parser = _TYPED_LITERAL_PARSERS[keyword]
        str_tok = self._peek()
        if str_tok.kind is not TokenKind.STRING_LIT:
            raise ParseError(
                str_tok.line, str_tok.col,
                f"expected string literal after {keyword}, got "
                f"{str_tok.kind.name} {str_tok.value!r}",
            )
        self._advance()
        try:
            value = value_parser(str_tok.value)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ParseError(
                str_tok.line, str_tok.col,
                f"invalid {keyword} literal {str_tok.value!r}: {exc}",
            ) from exc
        return TypedLiteral(tag=tag, value=value)

    def _parse_literal(self) -> Literal:
        """Consume one literal token and wrap it in a Literal AST node."""
        tok = self._peek()
        if tok.kind in (
            TokenKind.INT_LIT, TokenKind.FLOAT_LIT, TokenKind.STRING_LIT,
            TokenKind.BOOL_LIT, TokenKind.NULL_LIT,
        ):
            self._advance()
            value = None if tok.kind is TokenKind.NULL_LIT else tok.value
            return Literal(value=value)
        raise ParseError(
            tok.line, tok.col,
            f"expected literal, got {tok.kind.name} {tok.value!r}",
        )

    # --- helpers ----------------------------------------------------

    def _match_op_in(self, op_set: frozenset) -> Optional[str]:
        """Consume and return a single-char/multi-char OP whose value is in op_set."""
        tok = self._peek()
        if tok.kind is TokenKind.OP and tok.value in op_set:
            self._advance()
            return tok.value
        return None


# --- public entry point -------------------------------------------------
#
# Three layers, each tested independently:
#
# 1. ``parse_ddl(tokens)`` / ``parse_dml(tokens)`` — token-list entry
#    points used by callers that already ran the lexer themselves.
# 2. ``parse_ddl_string(sql)`` / ``parse_dml_string(sql)`` — string
#    wrappers around (1) for callers that want a one-shot API.
# 3. ``parse(sql)`` — top-level dispatcher that lexes once and routes
#    on the leading keyword to either ``parse_ddl_string`` or
#    ``parse_dml_string``.
#
# All three layers raise :class:`ParseError` with the offending
# token's 1-indexed line / column (REQ-SQL-7).


def parse_ddl(tokens: List[Token]) -> Statement:
    """Parse a token stream as a DDL statement.

    Returns a :class:`~tinydb.sql.ast.CreateTable` or
    :class:`~tinydb.sql.ast.DropTable`.  Raises
    :class:`~tinydb.errors.ParseError` with the offending token's line
    and column on any syntactic error.
    """
    return _Parser(tokens).parse_ddl()


def parse_dml(tokens: List[Token]) -> Statement:
    """Parse a token stream as a DML statement (INSERT/SELECT/UPDATE/DELETE).

    Returns an :class:`Insert`, :class:`Select`, :class:`Update`, or
    :class:`Delete` AST node.  Raises :class:`ParseError` with the
    offending token's line / column on any syntactic error.
    """
    return _Parser(tokens).parse_dml()


def parse_expr(tokens: List[Token]) -> Expr:
    """Parse a token stream as a single expression.

    Consumes tokens up to (but not including) the trailing EOF.  Any
    leftover non-EOF token raises :class:`ParseError` so callers can't
    silently ignore trailing garbage.  The expression precedence ladder
    is documented on :meth:`_Parser.parse_expr`.
    """
    parser = _Parser(tokens)
    expr = parser.parse_expr()
    if not parser._at_end():
        tok = parser._peek()
        raise ParseError(
            tok.line, tok.col,
            f"unexpected trailing token {tok.kind.name} {tok.value!r}",
        )
    return expr


# Leading keywords that mark a statement as DDL — used by ``parse()``
# to auto-dispatch.  Kept as a module-level frozenset so the dispatch
# is a single set membership check rather than a chain of ``==``.
_DDL_LEAD_KEYWORDS: frozenset = frozenset({"CREATE", "DROP"})


def parse_ddl_string(sql: str) -> Statement:
    """Lex + parse a raw SQL string as a DDL statement.

    Thin wrapper around :func:`tokenize` + :func:`parse_ddl` for callers
    that already hold the raw source.  All parse errors still carry the
    original 1-indexed line / column of the offending token (REQ-SQL-7).
    """
    return parse_ddl(tokenize(sql))


def parse_dml_string(sql: str) -> Statement:
    """Lex + parse a raw SQL string as a DML statement.

    Thin wrapper around :func:`tokenize` + :func:`parse_dml`.
    """
    return parse_dml(tokenize(sql))


def parse(sql: str) -> Statement:
    """Lex + parse a raw SQL string, auto-dispatching DDL vs DML.

    Reads the leading keyword to pick the right grammar:

    * ``CREATE`` / ``DROP``   → DDL parser
    * ``INSERT`` / ``SELECT`` / ``UPDATE`` / ``DELETE`` → DML parser

    Anything else raises :class:`~tinydb.errors.ParseError` with the
    offending position.  This is the public entry point most callers
    should use — only reach for :func:`parse_ddl_string` /
    :func:`parse_dml_string` directly when you already know the
    statement kind (or want to reject the other kind up front).

    v0.1 accepts a single statement per call; any non-EOF token after
    the parsed statement is reported as a parse error so callers can
    spot typos like ``SELECT * FROM t LIMOT 10`` (missing keyword
    would otherwise be silently swallowed by SELECT's permissive
    clause-omission logic).
    """
    tokens = tokenize(sql)
    first = tokens[0]
    if first.kind is TokenKind.KEYWORD and first.value in _DDL_LEAD_KEYWORDS:
        parser = _Parser(tokens)
        stmt = parser.parse_ddl()
    else:
        parser = _Parser(tokens)
        stmt = parser.parse_dml()
    # After the dispatched parser returns, the cursor sits just before
    # any trailing tokens (if the source contained more than one
    # statement or trailing garbage).  Position is 1-based in the error
    # path — token at parser.position() is the first un-consumed.
    if parser.position() < len(tokens) - 1:
        tok = tokens[parser.position()]
        raise ParseError(
            tok.line, tok.col,
            f"unexpected trailing token {tok.kind.name} {tok.value!r}",
        )
    return stmt


__all__ = [
    "parse",
    "parse_ddl",
    "parse_dml",
    "parse_expr",
    "parse_ddl_string",
    "parse_dml_string",
]