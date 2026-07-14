# T-5.5 — INSERT / UPDATE / DELETE execution + index maintenance — Report

## Summary

The Executor now writes. INSERT/UPDATE/DELETE plans push rows through Heap with the IndexManager firing on every maintenance hook so all B-tree indexes stay in sync. Schema constraints (NOT NULL, UNIQUE) surface as the right TinydbError subclass (`NotNullViolation`, `ConstraintViolation`).

Branch: `feature/tinydb-v0.1.0`.

## Recovery Note

The original implementer (sub-agent) was terminated by an upstream API rate-limit (HTTP 429) **after** the GREEN + VERIFY steps completed but **before** the report was written and the commit was made. All implementation files were already on disk and the suite was already green; the recovery here is mechanical verification + report + single commit. No code rewrite was needed.

## Commit

- Hash (short): *populated below by git*
- Hash (full): *populated below by git*
- Message: `feat(executor): T-5.5 DML execution + index maintenance`

## Test count delta

| State              | Count |
|--------------------|-------|
| Before (T-5.4 close)  | 549 |
| After (T-5.5)         | **562** (+13 new tests in `tests/executor/test_dml.py`) |

Full suite (after): **562 passed in 5.43s**.

Executor coverage (per-file):
```
src/tinydb/executor/__init__.py         7      0   100%
src/tinydb/executor/dml.py             87      4    95%
src/tinydb/executor/eval_expr.py       80     20    75%
src/tinydb/executor/executor.py        38      3    92%
src/tinydb/executor/heap_bind.py       13      1    92%
src/tinydb/executor/index_plan.py      75      9    88%
src/tinydb/executor/index_scan.py      64      7    89%
src/tinydb/executor/ops.py            146     15   90%
src/tinydb/executor/planner.py        124      9    93%
src/tinydb/executor/row_iter.py        19      1    95%
TOTAL                                 653     69    89%
Required test coverage of 85% reached. Total coverage: 89.43%
```

## Files created / modified

| Path                                         | Lines (Δ) | Notes |
|----------------------------------------------|-----------|-------|
| `src/tinydb/types/codec.py`                  | 322 (+58) | added `encode_row_coerced(values, tags)` |
| `src/tinydb/executor/dml.py`                 | 167 (new) | `Insert`/`Update`/`Delete.open` + helpers (`_assert_not_null`, `_dml_context`) |
| `src/tinydb/executor/heap_bind.py`           |  38 (new) | `bind_heap(catalog, table_name) -> Heap` (NIT-10 fix from T-5.2) |
| `src/tinydb/executor/ops.py`                 | 291 (−22)| DML dataclasses moved to `dml.py`; re-exported here for back-compat |
| `src/tinydb/executor/executor.py`            |  91 (−6) | DML-stub `NotImplementedError` removed |
| `src/tinydb/executor/__init__.py`            |  40 (+2) | re-export `bind_heap` |
| `tests/executor/test_dml.py`                 | 357 (new) | 13 cases |
| **Total production Δ**                       | **+38** (176 - 138) | |
| **Total test Δ**                             | **+357** | |

All file caps met:
- `src/tinydb/executor/dml.py` ≤ 250 ✓ (167)
- `src/tinydb/executor/heap_bind.py` ≤ 50 ✓ (38)
- `src/tinydb/executor/ops.py` ≤ 380 ✓ (291)
- `src/tinydb/executor/executor.py` ≤ 130 ✓ (91)
- `src/tinydb/types/codec.py` +80 ✓ (+58)

## Deviations / NITs to carry forward to T-5.6

1. **DELETE + INSERT on UPDATE — Rid changes** — Heap has no in-place update (B2 contract); the executor rewrites a row by `delete(rid) + insert(blob)`. The new Rid triggers a full index dance: `indexer.on_delete(old_rid)` followed by `indexer.on_insert(new_rid, new_row)`. This is correct but **changes the row's identity**. B7 / Future work may want a real in-place update (and FK-style references would then need adjustment).
2. **`_assert_not_null` runs before encode** — INSERT/UPDATE both check NOT NULL constraints on the Python tuple before calling `encode_row_coerced`. NULL goes through the codec as `TypeTag.Null` regardless of column tag (per B1 design — `Null` is its own tag), so inserting a NULL into a NULLABLE column works the same.
3. **`bind_heap` reads `catalog._pager`** — still a private field access. B7's `Engine` will expose `.pager` publicly; until then, `Executor` and `bind_heap` agree on this convention. Document in B7 brief.
4. **`encode_row_coerced` lives in `types/codec.py`** — per brief; tested via the 13 DML cases. Side effect: DML paths must `coerce_value` first (each call returns `(bytes, actual_tag)`); the wrapper concatenates the bytes directly. There is no logical change to `coerce_value` itself.
5. **`Heap.scan()` snapshot for DML** — UPDATE/DELETE take `list(heap.scan())` to avoid mutating the chain under iteration. UPDATE then makes two more calls (delete + insert); INSERT/DO-NOTHING/UPDATE-WITHOUT-MATCH are all single-pass.
6. **UNIQUE enforcement belongs to IndexManager, not the executor** — `indexer.on_insert` raises `ConstraintViolation`; the executor just lets it bubble. This is the right separation: every index type will need its own UNIQUE check; the executor doesn't have to learn them.
7. **`_dml_context` returns a 4-tuple, not a dataclass** — pragmatic; the helper saves typing and the executor only touches each element a few times. Not a NIT, just a small style note.
8. **`eval_expr` signature** — `Update.open` calls `eval_expr(expr, old_row, n2i)` for assignment evaluation. The function evaluates the **old row's** value (because RHS expressions like `SET age = age + 1` need to read the existing column). Confirm this matches the SQL spec for SetClause semantics — for v0.1 it does, but PostgreSQL allows subqueries in updates later (out of scope; T-6.7 wouldn't cover this either).

## Constraints satisfied

- `dml.py` ≤ 250 ✓ (167)
- `heap_bind.py` ≤ 50 ✓ (38)
- `ops.py` ≤ 380 ✓ (291)
- `executor.py` ≤ 130 ✓ (91)
- `codec.py` + ≤ 80 ✓ (+58)
- Zero external deps.
- Immutability: DML dataclasses remain `@dataclass(frozen=True, slots=True)`.
- 100% of existing 549 tests still pass.
