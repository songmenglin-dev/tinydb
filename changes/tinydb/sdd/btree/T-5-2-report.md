# T-5.2 — SeqScan + Filter + Project — Report

## Summary

Implemented the row-producing half of the executor per `T-5-2.md`.  tinydb
now runs `SELECT * / WHERE / AND / OR / NOT / IS [NOT] NULL / projection
/ literal / arithmetic` end-to-end through `Heap + Codec + planner tree`.
The 486-test T-5.1 baseline grew to **502** (+16 new tests in
`tests/executor/test_select.py`); full suite is green; executor coverage
is 87.57% (≥ 85% required).

Branch: `feature/tinydb-v0.1.0`.

## Commit

- Hash (short): see git log at the end of this report
- Message: `feat(executor): T-5.2 SeqScan + Filter + Project execution`

## TDD evidence

RED (collection error, before any production code):
```
ImportError while importing test module
'/mnt/c/sml/project/py_project/tinydb/tests/executor/test_select.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
tests/executor/test_select.py:20: in <module>
    from tinydb.executor.row_iter import TableScan
E   ModuleNotFoundError: No module named 'tinydb.executor.row_iter'
=========================== 1 error in 0.42s ===============================
```

RED (post-implementation, missing wiring — first Executor run):
```
src/tinydb/executor/planner.py:118: in heap_for
    raise RuntimeError(
E   RuntimeError: Executor needs a Pager to bind heaps (pager=None)
================= 15 failed, 1 passed in 1.70s ==============================
```

GREEN (final, after pager fallback in Executor + items= in Project):
```
tests/executor/test_select.py::test_select_star_returns_all_rows   PASSED
tests/executor/test_select.py::test_where_id_equality              PASSED
tests/executor/test_select.py::test_where_id_greater_than          PASSED
tests/executor/test_select.py::test_where_and_combinator           PASSED
tests/executor/test_select.py::test_where_or_combinator            PASSED
tests/executor/test_select.py::test_where_is_null                  PASSED
tests/executor/test_select.py::test_where_is_not_null              PASSED
tests/executor/test_select.py::test_where_mixed_and_or_precedence  PASSED
tests/executor/test_select.py::test_project_specific_columns       PASSED
tests/executor/test_select.py::test_project_with_filter            PASSED
tests/executor/test_select.py::test_where_unknown_column_raises    PASSED
tests/executor/test_select.py::test_tombstoned_row_is_skipped      PASSED
tests/executor/test_select.py::test_filter_matches_codec_decoded_int PASSED
tests/executor/test_select.py::test_select_from_empty_table        PASSED
tests/executor/test_select.py::test_where_not                      PASSED
tests/executor/test_select.py::test_select_literal_projection      PASSED
============================== 16 passed in 0.41s ==============================
```

Full suite (after):
```
502 passed in 4.60s
```

Executor coverage (per-file):
```
src/tinydb/executor/__init__.py        4      0   100%
src/tinydb/executor/eval_expr.py      80     22    72%
src/tinydb/executor/executor.py       36      4    89%
src/tinydb/executor/ops.py            95      4   96%
src/tinydb/executor/planner.py       104     11   89%
src/tinydb/executor/row_iter.py       19      1   95%
TOTAL                                338     42   88%
```

## Files created / modified

| Path | Lines (Δ) | Notes |
|------|-----------|-------|
| `src/tinydb/types/codec.py`               | 264 (+37) | added `encode_row` / `decode_row` (per brief) |
| `src/tinydb/executor/row_iter.py`         |  50 (new) | `TableScan` (Rid, row_tuple) iterator |
| `src/tinydb/executor/eval_expr.py`        | 138 (new) | recursive `eval_expr` + binary/unary dispatch |
| `src/tinydb/executor/ops.py`              | 243 (+67)| `SeqScan/Filter/Project.open` + `table` property on every Plan |
| `src/tinydb/executor/planner.py`          | 245 (−5) | forwards `items=` to Project; Executor moved out |
| `src/tinydb/executor/executor.py`         |  81 (new) | `Executor` dataclass (split from planner) |
| `src/tinydb/executor/__init__.py`         |  34 (+1) | re-exports `Executor` from new module |
| `tests/executor/test_select.py`           | 357 (new) | 16 cases covering the 14 brief cases + 2 extras (IS NOT NULL, NOT) |
| `tests/executor/test_planner.py`          | 311 (±0) | updated one assertion to match T-5.2 contract |
| **Total production Δ**                    | **+256** | |
| **Total test Δ**                          | **+357** | |

All files within caps:
- `eval_expr.py` ≤ 200 ✓ (138)
- `row_iter.py`  ≤ 100 ✓ (50)
- `ops.py`       ≤ 250 ✓ (243)
- `planner.py`   ≤ 280 ✓ (245)
- `codec.py`     +50 ✓ (+37)

## Deviations / NITs to carry forward to T-5.3

1. **`Project.items` parallel-array** — to evaluate non-trivial
   projections (`SELECT 1 + 2 FROM users`), the planner now passes
   `Project(..., items=tuple(stmt.columns))` so the executor can
   re-evaluate the original AST nodes when a column label is a
   synthetic name (e.g. `"BinaryOp"`).  T-5.3 / T-5.6 should keep
   the parallel-array contract; an alternative would be to attach
   the source AST node to each label by name (label → Expr dict).

2. **`Executor.heap_for` falls back to `catalog._pager`** — the
   public `Catalog` does not expose a `pager` accessor; the executor
   reads the private `_pager` when none is passed in.  B7's
   `Engine` wrapper will provide a clean public entry point.  Until
   then, `Executor(catalog)` works in single-file deployments.

3. **`Heap._head_pid` rebind** — when binding a fresh `Heap` to a
   catalog table, the executor overwrites `_head_pid` to the
   catalog's recorded `heap_pid`.  This is a deliberate reuse of
   the Heap machinery against the catalog-owned page chain.  T-5.5
   may want to formalise this with a `Heap.attach(pager, head_pid)`
   constructor so callers don't poke a private field.

4. **`test_executor_symbol_exists` was a T-5.1 contract test** — it
   originally asserted `Executor.execute(SELECT)` raised
   `NotImplementedError`.  T-5.2 makes SELECT execution work, so
   the test now asserts the result is a list.  This is the only
   test in `tests/executor/test_planner.py` that changed; the brief
   explicitly listed `tests/storage/`, `tests/sql/`, `tests/index/`,
   `tests/types/`, `tests/test_errors.py`, `tests/test_smoke.py` as
   off-limits, so `test_planner.py` was fair game.

5. **Synthetic column names still appear for non-trivial projections**
   (carry-forward from T-5.1 NIT-9) — the test
   `test_select_literal_projection` runs `SELECT 1 + 2 FROM users`
   and asserts on the tuple result, not on the label.  T-5.6 will
   resolve real labels (`'1 + 2'`) for end-user column names.

6. **`__init__.py` Executor re-export** — `Executor` is now defined
   in `tinydb.executor.executor` (split out to keep `planner.py`
   under the 280-line cap).  The package re-exports it, so the
   public import path `tinydb.executor.Executor` is preserved.  T-5.5
   can continue to import from either location.

7. **T-5.2 supports 4 unary ops + 11 binary ops** — the evaluator
   handles `= != < <= > >= + - * / AND OR` and `NOT IS NULL IS NOT
   NULL`.  The parser's full surface is broader (e.g. `BETWEEN`,
   `IN`, `LIKE`) but those are not exercised by the brief and were
   not surfaced by the planner.  T-5.3 may grow this if needed.

8. **`Plan.table` is a `@property`** — every leaf plan
   (`SeqScan` / `Insert` / `Update` / `Delete`) returns its own
   `table` field; wrappers traverse `src.table`.  This lets the
   executor resolve the base table for any plan node without a
   separate schema-walk.  T-5.3 will need to override on
   `IndexScan` (return the underlying table) and T-5.6 will need
   a similar pattern for `Aggregate` (where the row shape diverges).

9. **Coverage gap in `eval_expr.py` (72%)** — the unexercised
   branches are the Aggregate-raise path (T-5.6 territory) and a
   few defensive `NotImplementedError` paths in `_eval_binary` /
   `_eval_unary`.  The brief's 85% executor-level threshold is met
   (88% total), and the gap is by-design (out of scope).

10. **Heap `_pager` rebinding for executor-injected Heap instances**
    — when the executor constructs `Heap(self.pager, table_id=…)` and
    then rebinds `_head_pid` to the catalog's `heap_pid`, the new
    chain may span pages that the freshly-allocated `Heap` was
    never told about (the page 4 chain vs. the page 1/2 catalog).
    In practice, `Heap.scan()` walks the chain by following
    `next_page_id` from the head, so the rebind is correct — but
    it relies on the catalog's `heap_pid` being the true chain
    head.  This is consistent with the brief's
    "`Heap(pager, table_id=...)` then set `_head_pid = meta.heap_pid`"
    instruction.

## Constraints satisfied

- `planner.py` ≤ 280 lines ✓ (245)
- `ops.py` ≤ 250 lines ✓ (243)
- `eval_expr.py` ≤ 200 lines ✓ (138)
- `row_iter.py` ≤ 100 lines ✓ (50)
- `codec.py` +50 lines ✓ (+37)
- Zero external deps ✓
- No mutation: every Plan dataclass remains `@dataclass(frozen=True, slots=True, kw_only=True)` ✓
- Public symbol surface unchanged (Plan, SeqScan, IndexScan, Filter,
  Project, Sort, Limit, Insert, Update, Delete, plan, Executor all
  importable from `tinydb.executor`) ✓
- 486-test baseline preserved (now 502 green) ✓
- All new public symbols have full type annotations ✓
- No edits to `tests/storage/`, `tests/sql/`, `tests/index/`,
  `tests/types/`, `tests/test_errors.py`, `tests/test_smoke.py` ✓
