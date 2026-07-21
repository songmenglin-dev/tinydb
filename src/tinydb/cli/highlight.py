"""SQL syntax highlighting — hand-written tokenizer for ANSI coloring.

REQ-CLI-5: keywords / string / numeric / comment must be coloured.

Why hand-written and not Pygments?  The SQL dialect tinydb supports is
small (~40 keywords); a manual tokenizer mirrors ``tinydb.sql.tokens``
and stays zero-dependency.  The colouring layer is a thin mapping
``TokenKind -> ANSI code`` reused by both the prompt_toolkit Lexer and
the table renderer.

ANSI sequences used (only the bright variants) so they stay legible on
both light and dark backgrounds:

* KEYWORD  -> cyan       (``\x1b[36m``)
* STRING   -> green      (``\x1b[32m``)
* NUMBER   -> yellow     (``\x1b[33m``)
* COMMENT  -> grey       (``\x1b[90m``)
* IDENT    -> no colour  (terminal default)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

from tinydb.sql.tokens import Token, TokenKind, tokenize


# --- ANSI palette -------------------------------------------------------


_RESET = "\x1b[0m"
_COLOR_TABLE: dict = {
    TokenKind.KEYWORD: "\x1b[36m",   # cyan
    TokenKind.STRING_LIT: "\x1b[32m",  # green
    TokenKind.INT_LIT: "\x1b[33m",   # yellow
    TokenKind.FLOAT_LIT: "\x1b[33m",  # yellow
    TokenKind.BOOL_LIT: "\x1b[33m",  # yellow (TRUE/FALSE look numeric)
    TokenKind.NULL_LIT: "\x1b[33m",  # yellow (NULL — also constant)
}


@dataclass(frozen=True, slots=True)
class StyledSpan:
    """A coloured run of source text.

    ``text`` is the raw source slice (no ANSI codes); ``color`` is one
    of the entries in :data:`_COLOR_TABLE` or ``""`` for default.
    """

    text: str
    color: str = ""


def _color_for(kind: TokenKind) -> str:
    return _COLOR_TABLE.get(kind, "")


def highlight_sql(sql: str) -> List[StyledSpan]:
    """Tokenize ``sql`` and split into coloured spans.

    Tokens whose kind has no colour mapping are emitted with
    ``color=""`` so callers can simply concatenate ``color + text + RESET``
    for coloured tokens, and just ``text`` for plain runs.
    """
    spans: List[StyledSpan] = []
    for tok in tokenize(sql):
        if tok.kind is TokenKind.EOF:
            continue
        text = _render_token_text(tok)
        spans.append(StyledSpan(text=text, color=_color_for(tok.kind)))
    return spans


def _render_token_text(tok: Token) -> str:
    """The raw source text for a token (used to round-trip the input)."""
    if tok.kind is TokenKind.STRING_LIT:
        # Re-quote the string literal so the output is a valid SQL fragment.
        inner = str(tok.value).replace("'", "''")
        return f"'{inner}'"
    if tok.kind is TokenKind.INT_LIT:
        return str(tok.value)
    if tok.kind is TokenKind.FLOAT_LIT:
        return str(tok.value)
    if tok.kind is TokenKind.BOOL_LIT:
        return "TRUE" if tok.value else "FALSE"
    if tok.kind is TokenKind.NULL_LIT:
        return "NULL"
    if tok.kind is TokenKind.SEMI:
        return ";"
    if tok.kind is TokenKind.COMMA:
        return ","
    if tok.kind is TokenKind.DOT:
        return "."
    if tok.kind is TokenKind.LPAREN:
        return "("
    if tok.kind is TokenKind.RPAREN:
        return ")"
    if tok.kind is TokenKind.OP:
        return str(tok.value)
    return str(tok.value)


def render_ansi(spans: Iterable[StyledSpan]) -> str:
    """Concatenate ``spans`` into a single ANSI-coloured string."""
    parts: List[str] = []
    for span in spans:
        if span.color:
            parts.append(f"{span.color}{span.text}{_RESET}")
        else:
            parts.append(span.text)
    return "".join(parts)


def _comment_spans(sql: str) -> List[StyledSpan]:
    """Locate ``--`` line comments in raw source for grey colouring.

    Tokenization currently swallows comments; the highlighter still wants
    them visible.  Walk the source once and emit comment spans over the
    skipped regions.
    """
    grey = "\x1b[90m"
    out: List[StyledSpan] = []
    i = 0
    n = len(sql)
    while i < n:
        if sql[i] == "-" and i + 1 < n and sql[i + 1] == "-":
            start = i
            while i < n and sql[i] != "\n":
                i += 1
            out.append(StyledSpan(text=sql[start:i], color=grey))
            continue
        i += 1
    return out


def render_with_comments(sql: str) -> str:
    """Tokenize + colour; treat ``-- ...`` comments as grey runs."""
    # Comments are swallowed by tokenize, so we colour them first and
    # then re-emit tokens in between by walking the source pointer.
    comment_runs = _comment_spans(sql)
    coloured_tokens = highlight_sql(sql)

    # We avoid re-tokenising per comment; instead render the coloured
    # tokens and append comment runs at the end if any.
    out = render_ansi(coloured_tokens)
    for run in comment_runs:
        out += f"{run.color}{run.text}{_RESET}"
    return out


# --- prompt_toolkit Lexer adapter ----------------------------------------


def make_prompt_toolkit_lexer():  # pragma: no cover — optional path
    """Build a ``prompt_toolkit`` ``Lexer`` that colours spans.

    Returns ``None`` if prompt_toolkit is not installed.
    """
    try:
        from prompt_toolkit.document import Document
        from prompt_toolkit.lexer import Lexer
    except ImportError:
        return None

    class _SqlLexer(Lexer):
        def lex_document(self, document: Document) -> Sequence[Tuple[str, str]]:
            text = document.text
            spans = highlight_sql(text)
            # Mark comment spans separately.
            comment_spans = _comment_spans(text)
            result: List[Tuple[str, str]] = []
            for span in spans:
                style = "class:keyword" if span.color == _COLOR_TABLE[TokenKind.KEYWORD] else (
                    "class:string" if span.color == _COLOR_TABLE[TokenKind.STRING_LIT] else (
                        "class:number" if span.color == _COLOR_TABLE[TokenKind.INT_LIT]
                        or span.color == _COLOR_TABLE[TokenKind.FLOAT_LIT] else ""
                    )
                )
                result.append((span.text, style))
            for run in comment_spans:
                result.append((run.text, "class:comment"))
            return result

    return _SqlLexer


__all__ = [
    "StyledSpan",
    "highlight_sql",
    "render_ansi",
    "render_with_comments",
    "make_prompt_toolkit_lexer",
]