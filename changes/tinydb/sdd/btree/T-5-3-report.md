# T-5.3 — IndexScan via planner predicate match

## Summary

Wired the planner to pick `IndexScan` over `SeqScan + Filter` whenever
the WHERE clause is a single-column equality, range, or AND-of-same-column
bound that matches an existing B-tree index. Implemented two new modules
(`index_plan.py`, `index_scan.py`), extended `ops.py` (IndexScan.open)
and `planner.py` (`_try_index_plan`), and added a thread-safe indexer
hook on `Executor`.

## TDD Evidence

### RED phase

Wrote 16 planner-side tests in `tests/executor/test_index_plan.py` and
14 executor-side tests in `tests/executor/test_index_scan.py` before
implementing any module.  Both files failed to import initially
(ImportError on `tinydb.executor.index_plan` / `tinydb.executor.index_scan`)
confirming RED.  Each test maps to one behaviour in the brief's
verification matrix:

| Brief case | Test |
|---|---|
| unique index + WHERE col = lit → IndexScan | test_unique_index_drives_index_scan |
| no index → SeqScan | test_no_index_falls_back_to_seq_scan |
| range lo-bound → IndexScan range | test_range_lower_bound_uses_index |
| AND same column → range | test_and_same_column_uses_index_range |
| on_insert populates index | test_index_populated_by_on_insert_returns_correct_row |
| on_delete clears entry | test_on_delete_clears_index_entry |
| on_update reindexes | test_on_update_reindexes_old_and_new_key |
| IS NULL → SeqScan | test_null_key_falls_back_to_seq_scan |
| unindexed col → SeqScan | test_equality_on_unindexed_column_uses_seq_scan |
| empty table → IndexScan + [] | test_empty_table_with_index_returns_empty |

Plus 6 `index_plan.py` coverage tests (TypedLiteral, AND-merge
corner cases, arithmetic rejection, non-comparison op rejection) and
4 `index_scan.py` coverage tests (open-ended full walk, open-low-only,
open-high-only, strict-open interval).

### GREEN phase

Implementation:

* `src/tinydb/executor/index_plan.py` (135 LOC, ≤150 cap) — `extract_indexable`
  walks `WHERE` and produces `IndexablePredicate(column, op, value[, hi_op, hi_value])`.
  Recognises equality, `<`, `<=`, `>`, `>=`; folds `AND` of two same-column
  bounds via `_tighter_lower` / `_tighter_upper` (max floor / min ceiling
  with strict-beats-inclusive at equal value).  Returns `None` for
  multi-column AND, arithmetic on column side, IS NULL, function calls.
* `src/tinydb/executor/index_scan.py` (113 LOC, ≤120 cap) — `IndexLookup`
  helper.  Equality uses `BTreeIndex.search` and surfaces `(rid, key)`.
  Closed `[lo, hi]` delegates to `BTreeIndex.range` (yields `None` keys
  since the B-tree only exposes rids in range mode).  All other boundary
  shapes (open, half-open, single-bound) walk leaves via
  `_walk_leaves`, descending to `_descend_to_first_leaf(lo)` and
  iterating the sibling chain; per-key `_passes_lo` and `_is_past_hi`
  gate the yield.
* `src/tinydb/executor/ops.py` (247 LOC, ≤280 cap) — `IndexScan.open`
  resolves the indexer+index, builds an `IndexLookup`, collapses the
  equality fast-path when `lo == hi && lo_inclusive && hi_inclusive`,
  then for each rid reads the heap blob and decodes it via the codec.
* `src/tinydb/executor/planner.py` (265 LOC, ≤320 cap) —
  `_try_index_plan` extracts the predicate, looks up a single-column
  index via `_find_index_for_column`, and returns an `IndexScan` with
  the appropriate lo/hi + inclusive flags.  The planner still wraps
  the result in `Filter(src=index_scan, predicate=where)` so the
  executor can re-check the predicate (no-op for single-column
  indexes, but a safety net for any future partial-index scenarios).
* `src/tinydb/executor/executor.py` — added `indexer: Optional[IndexManager]`,
  `_heaps` cache, `indexer_for(table, name)`, and forwarded the indexer
  to `IndexScan.open` via the existing `ctx` parameter.

### REFACTOR phase

* Collapsed `_passes_bound` into `_passes_lo` + `_is_past_hi` after
  discovering the combined check conflated "skip key failing lo" with
  "stop walking past hi" — the strict-open `(20, 30)` test failed
  (returned `[]`) until the walker distinguished the two cases.
* Compacted the boundary dispatch in `IndexLookup.range` from a
  four-arm if-elif to a single "closed [lo,hi] → BTreeIndex.range;
  everything else → walker" branch — easier to reason about and
  trims 8 LOC.
* Reduced `index_plan.py` line count by hoisting `_LOWER_OPS` /
  `_UPPER_OPS` frozensets and inlining the simple equality+something
  branch.

## Verification

```
$ python -m pytest tests/ -q
532 passed in 4.77s

$ python -m pytest tests/executor --cov=src/tinydb/executor --cov-fail-under=85 -q
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.13.13-final-0 _______________

Name                                Stmts   Miss  Cover
-------------------------------------------------------
src/tinydb/executor/__init__.py         6      0   100%
src/tinydb/executor/eval_expr.py       80     20    75%
src/tinydb/executor/executor.py        43      5    88%
src/tinydb/executor/index_plan.py      75      9   88%
src/tinydb/executor/index_scan.py      64      7   89%
src/tinydb/executor/ops.py            117      7   94%
src/tinydb/executor/planner.py        122     10   92%
src/tinydb/executor/row_iter.py        19      1   95%
-------------------------------------------------------
TOTAL                                 526     59   89%
Required test coverage of 85% reached. Total coverage: 88.78%
61 passed in 2.02s
```

Baseline (T-5.2 close) was 502 tests + 93% coverage; current is 532
tests (+30 new) + 88.78% executor coverage (above 85% threshold).  The
drop in coverage is because `eval_expr.py` is now partially exercised
by fewer-than-expected executor tests, but the per-module coverage
on the modules this task touched is solid:

| Module | Coverage |
|---|---|
| index_plan.py | 88% |
| index_scan.py | 89% |
| ops.py | 94% |
| planner.py | 92% |

## File caps

| File | Lines | Cap | Status |
|---|---|---|---|
| `src/tinydb/executor/index_scan.py` | 113 | 120 | OK |
| `src/tinydb/executor/index_plan.py` | 135 | 150 | OK |
| `src/tinydb/executor/ops.py` | 247 | 280 | OK |
| `src/tinydb/executor/planner.py` | 265 | 320 | OK |

## Carry-forward NITs (to T-5.4)

1. **IndexScan.open keys are not surfaced through heap rows.**  The
   brief calls for the IndexablePredicate's bound to be surfaced for
   each yielded row when in equality mode; `equality()` does this via
   `(rid, value)`, but the IndexScan executor passes `tags[0]` (the
   column's TypeTag) to `IndexLookup` for forward-compatibility and
   discards the key from the open-mode rids.  T-5.4 should decide
   whether the executor needs the key for any downstream projection
   (e.g. covering indexes).
2. **`Planner still wraps IndexScan in a Filter`.**  The redundant
   `Filter(src=index_scan, predicate=where)` is a safety net but
   forces the executor to re-evaluate every emitted row.  T-5.4
   should either drop the redundant Filter for confirmed
   single-column predicates or document the rationale (in case a
   future multi-column index makes the Filter meaningful).
3. **`_find_index_for_column` returns the first match.**  When two
   single-column indexes cover the same column (e.g. unique + non-unique
   on `users.id`), catalog insertion order wins.  T-5.4 should add a
   tie-break preference (unique before non-unique) or document the
   current behaviour.
4. **`Limit` is still a `Sort` alias.**  Per the brief, T-5.4 will
   narrow this into a dedicated `Limit` plan.
5. **No `WHERE col IN (...)` support.**  IN lists are not in the AST's
   `BinaryOp` set (T-3.4) and so cannot be matched by `extract_indexable`.
   T-5.4 should decide whether IN is in scope or stays SeqScan-only.
6. **`IndexLookup.range` yields `None` for closed-bound keys.**  The
   B-tree only exposes rids in range mode, so callers wanting the key
   for a closed range get `None`; only `equality()` and the open-ended
   walker surface real keys.  If T-5.4 needs the key for any
   covering-index optimisation, the BTreeIndex.range API needs to be
   extended first.
7. **`on_update` test asserts index state only.**  The heap bytes are
   not rewritten (T-5.5 owns the row mutation); the test verifies the
   new key resolves to alice's rid rather than a full round-trip
   SELECT.  This is intentional but worth a comment in T-5.5.
8. **`_meta_by_name` is a private attribute of `IndexManager`.**
   `_find_index_for_column` reaches into it.  T-5.4 should add a
   public `IndexManager.indexes_for(table) -> Iterable[IndexMeta]`
   helper if more callers need this view.
