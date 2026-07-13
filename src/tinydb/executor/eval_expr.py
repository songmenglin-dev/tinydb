"""Evaluate parser :class:`Expr` nodes against an in-memory row tuple.

T-5.2 supports:

* :class:`Literal` / :class:`TypedLiteral`  → return the stored value
* :class:`ColumnRef`                        → look up by name
* :class:`BinaryOp`                         → comparison / arithmetic /
                                               short-circuit AND / OR
* :class:`UnaryOp`                          → NOT / IS NULL / IS NOT NULL
* :class:`Aggregate`                        → raises (T-5.6 owns this)

The evaluator is a single recursive descent.  Predicates are bools
(true = keep row); arithmetic / projection expressions return the
computed value.
"""

from __future__ import annotations

from typing import Any, Sequence

from tinydb.executor.planner import UnknownColumnError
from tinydb.sql.ast import (
    Aggregate,
    BinaryOp,
    ColumnRef,
    Expr,
    Literal,
    TypedLiteral,
    UnaryOp,
)
from tinydb.types.system import TypeTag


# Truthy check that treats None as falsy and the rest by ``bool()``.
def _truthy(v: Any) -> bool:
    return bool(v)


def eval_expr(
    expr: Expr,
    row: tuple,
    name_to_idx: dict,
) -> Any:
    """Evaluate ``expr`` against the decoded ``row``.

    ``name_to_idx`` maps column name → row position.  Unknown column
    references raise :class:`UnknownColumnError` (the planner also
    checks this at plan time; the executor's check is the safety net
    in case a :class:`Plan` was hand-built in a test).
    """
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, TypedLiteral):
        return expr.value
    if isinstance(expr, ColumnRef):
        try:
            return row[name_to_idx[expr.name]]
        except KeyError as exc:
            raise UnknownColumnError(expr.name) from exc
    if isinstance(expr, BinaryOp):
        return _eval_binary(expr, row, name_to_idx)
    if isinstance(expr, UnaryOp):
        return _eval_unary(expr, row, name_to_idx)
    if isinstance(expr, Aggregate):
        raise NotImplementedError(
            f"aggregate {expr.func} is not implemented in T-5.2"
        )
    raise NotImplementedError(
        f"eval_expr: unsupported Expr node {type(expr).__name__}"
    )


def _eval_binary(expr: BinaryOp, row: tuple, name_to_idx: dict) -> Any:
    op = expr.op
    # Short-circuit AND / OR — left side decides.
    if op == "AND":
        left = eval_expr(expr.left, row, name_to_idx)
        if not _truthy(left):
            return left
        return eval_expr(expr.right, row, name_to_idx)
    if op == "OR":
        left = eval_expr(expr.left, row, name_to_idx)
        if _truthy(left):
            return left
        return eval_expr(expr.right, row, name_to_idx)

    left = eval_expr(expr.left, row, name_to_idx)
    right = eval_expr(expr.right, row, name_to_idx)
    if op == "=":
        return _eq(left, right)
    if op == "!=":
        return not _eq(left, right)
    # SQL three-valued logic: any comparison involving NULL is NULL
    # (treated as false by WHERE).  Returning None here makes the
    # Filter op drop the row.
    if left is None or right is None:
        return None
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        return left / right
    raise NotImplementedError(f"unsupported binary op: {op!r}")


def _eq(a: Any, b: Any) -> bool:
    """Equality that treats ``Decimal``/``int``/``str`` pairs naturally."""
    if a is None or b is None:
        return a is b
    if type(a) is type(b):
        return a == b
    # Allow int vs float to compare as numbers (e.g. age=18 vs age=18.0).
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return a == b


def _eval_unary(expr: UnaryOp, row: tuple, name_to_idx: dict) -> Any:
    op = expr.op
    if op == "IS NULL":
        v = eval_expr(expr.operand, row, name_to_idx)
        return v is None
    if op == "IS NOT NULL":
        v = eval_expr(expr.operand, row, name_to_idx)
        return v is not None
    if op == "NOT":
        v = eval_expr(expr.operand, row, name_to_idx)
        return not _truthy(v)
    raise NotImplementedError(f"unsupported unary op: {op!r}")


__all__ = ["eval_expr"]
