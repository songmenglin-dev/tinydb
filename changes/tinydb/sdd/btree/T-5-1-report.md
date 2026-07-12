# T-5.1 — Plan tree + Planner — Report

## Summary

Implemented the AST → Plan tree translation layer per `T-5-1.md`.
All 15 planner tests pass; existing 471 tests still pass (total **486**).
Branch `feature/tinydb-v0.1.0`.

## Commit

- Hash (short): `5e36763`
- Hash (full): `5e367637c480e5698d828d69f73ae93072b960d5`
- Message: `feat(executor): T-5.1 plan tree + planner`

## Test count delta

| State           | Count |
|-----------------|-------|
| Before (B5 start) | 471 |
| After (T-5.1)     | **486** (+15) |

Test tail (RED → GREEN):
- RED (collection error, before any production code):
  ```
  E   ModuleNotFoundError: No module named 'tinydb.executor'
  =========================== 1 error in 0.26s ===============================
  ```
- GREEN (final):
  ```
  tests/executor/test_planner.py::test_select_star_from_users          PASSED
  tests/executor/test_planner.py::test_select_specific_columns         PASSED
  tests/executor/test_planner.py::test_select_star_with_where          PASSED
  tests/executor/test_planner.py::test_select_with_where_order_by      PASSED
  tests/executor/test_planner.py::test_select_limit_offset_no_order_by PASSED
  tests/executor/test_planner.py::test_insert_plan_shape               PASSED
  tests/executor/test_planner.py::test_update_plan_with_predicate      PASSED
  tests/executor/test_planner.py::test_delete_plan_with_predicate      PASSED
  tests/executor/test_planner.py::test_unknown_table_raises            PASSED
  tests/executor/test_planner.py::test_unknown_column_in_where_raises  PASSED
  tests/executor/test_planner.py::test_try_index_plan_called_but_returns_none PASSED
  tests/executor/test_planner.py::test_group_by_aggregate_plan_constructs PASSED
  tests/executor/test_planner.py::test_executor_symbol_exists          PASSED
  tests/executor/test_planner.py::test_index_scan_dataclass_shape      PASSED
  tests/executor/test_planner.py::test_limit_alias_is_sort             PASSED
  ============================== 15 passed in 0.32s ==============================
  ```

Full suite (after):
```
486 passed in 4.33s
```

## Files created

| Path                                         | Lines |
|----------------------------------------------|-------|
| `src/tinydb/executor/__init__.py`            | 33    |
| `src/tinydb/executor/ops.py`                 | 176 (≤ 200 limit ✓) |
| `src/tinydb/executor/planner.py`             | 250 (≤ 250 limit ✓) |
| `tests/executor/__init__.py`                 | 0     |
| `tests/executor/conftest.py`                 | 48    |
| `tests/executor/test_planner.py`             | 311   |
| **Total**                                    | **818** |

## Deviations / NITs to carry forward to T-5.2

1. **No `Engine` / no `open_db`** — the brief's conftest snippet referenced
   `tinydb.storage.engine.Engine` and `tinydb.open_db`, neither of which
   exists in the codebase (B7 deliverable). Confirmed with team-lead, then
   used `Pager.open(...)` + `Catalog(pager)` directly per the actual
   pattern in `tests/storage/test_catalog.py` and `tests/index/test_btree.py`.
   T-5.2 fixtures should use the same `Pager`+`Catalog` pair; revisit when
   B7 lands.

2. **`parse` not exported from `tinydb.sql.__init__`** — the brief's tests
   refer to `tinydb.sql.parse`, but the SQL `__init__.py` only re-exports
   tokens + AST + DDL/DML/expression parse functions. Tests use
   `tinydb.sql.parser.parse_dml_string` directly (the underlying entry
   point). T-5.2 test code will need the same alias.

3. **Dataclass `kw_only=True` (Python 3.10+)** — the brief's `ops.py`
   snippet used `@dataclass(frozen=True, slots=True)` without the
   `kw_only` flag, which forces subclasses to declare `op_name` first
   and prevents inheriting a non-default field after a default. With the
   dataclass-with-inheritance pitfall, every Plan subclass needed
   `kw_only=True` so `op_name` can keep its default value while
   required positional fields stay positional. All Plan dataclasses are
   keyword-constructible; T-5.2 should preserve this convention.

4. **Insert plan carries multi-row `values`** — the brief's `InsertPlan.values`
   snippet shows `tuple` (single row). Real `Insert.values` is a
   `Tuple[Tuple[Any, ...], ...]` (multi-row). Planner forwards the
   full outer tuple; T-5.5 executor iterates `plan.values` to insert
   each row.

5. **`_try_index_plan` always returns `None`** — T-5.3 fills in the
   real EQ / range selection. Stub signature is locked: `(predicate,
   table_meta) -> Optional[IndexScan]`. Module-level (not nested)
   so T-5.3's tests can `monkeypatch.setattr(planner_mod, "_try_index_plan", ...)`.

6. **Plan ordering: `Sort` wraps `Project`** — confirmed by the brief's
   text ("wrap in Sort(filter_or_project, ...)"). Tests reflect this;
   T-5.4's executor must walk Sort → Project → Filter → SeqScan from
   the outside in.

7. **`SELECT *` always produces a Project** — even though Project on
   `SELECT *` is semantically a no-op, the planner emits one so the
   executor sees a uniform shape. List order matches catalog column
   order. T-5.2's executor can fast-path on the Project shape and skip
   re-shuffling.

8. **`GROUP BY` execution deferred to T-5.6** — `plan()` constructs a
   tree for `SELECT COUNT(*), name FROM users GROUP BY name`, but the
   executor raises `NotImplementedError` (placeholder). The planner
   validates group-by column names against the schema early so callers
   get a clean `UnknownColumnError`.

9. **Project columns for expression items** — `SELECT 1 + 2 FROM t`
   produces a column named `"BinaryOp"`. T-5.6 will refine (real label
   is the SQL expression text). Currently stable enough for testing
   but not for end-user column names.

## Constraints satisfied

- `planner.py` ≤ 250 lines ✓ (exactly 250)
- `ops.py` ≤ 200 lines ✓ (176)
- Zero external dependencies ✓
- No external imports outside the brief's allowlist ✓
- No mutation: every Plan dataclass is `@dataclass(frozen=True, slots=True, kw_only=True)` ✓
- Full type hints on public symbols ✓
- No edits outside `src/tinydb/executor/` and `tests/executor/` ✓
- All public symbols from the brief exported ✓