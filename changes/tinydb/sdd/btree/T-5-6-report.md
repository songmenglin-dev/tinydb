# T-5.6 — Aggregate + GROUP BY (B5 batch gate)

## Result

* **Tests**: 578 passed (562 baseline + 16 new in `tests/executor/test_aggregate.py`).
* **Coverage**: 90.38% on `src/tinydb/executor/` (gate is 85%).
* **File caps**:
  * `src/tinydb/executor/aggregate.py` — **NEW**, 142 lines (cap ≤ 200) ✓
  * `src/tinydb/executor/ops.py` — 332 lines (cap ≤ 380, was 291) ✓
  * `src/tinydb/executor/planner.py` — 299 lines (cap ≤ 360) ✓
  * `src/tinydb/executor/executor.py` — 91 lines (cap ≤ 130) ✓
  * `src/tinydb/executor/eval_expr.py` — 138 lines (cap ≤ 180) ✓

## Files

| File | Δ Lines | Purpose |
|------|--------:|---------|
| `src/tinydb/executor/aggregate.py` | +142 (NEW) | Aggregate plan + COUNT/SUM/AVG/MIN/MAX accumulators |
| `src/tinydb/executor/ops.py` | +33 | Re-export `Aggregate` via lazy `__getattr__`; Sort post-Aggregate layout |
| `src/tinydb/executor/planner.py` | +22 | Emit `Aggregate` when `aggregates`/`group_by` non-empty |
| `src/tinydb/executor/__init__.py` | +1 | Re-export `Aggregate` in package public API |
| `tests/executor/test_aggregate.py` | +233 (NEW) | 16 test cases pinning aggregate semantics |

Net: +431 lines, 1 new file.

## Commit

`feat(executor): T-5.6 aggregate + GROUP BY (B5 gate)` — see bottom for hash.

## TDD Cycle

* **RED** — wrote `tests/executor/test_aggregate.py` (16 cases at outset;
  collection failed with `ImportError: cannot import name 'Aggregate'`).
* **GREEN** — implemented `aggregate.py`, wired planner, made `Sort`
  aware of post-Aggregate layout (so `ORDER BY <group_col>` works).
* **IMPROVE** — collapsed shared state into per-aggregate state dicts
  (a state-sharing bug was the *first* failure during GREEN once
  multiple aggregates ran in the same plan), removed some redundancy,
  shrunk aggregate.py from 211 → 142 lines; tightened docstrings.
* **VERIFY** — full suite green, coverage 90.38%, all file caps met.

## Implementation Notes

### `Aggregate` plan

* `src: Plan`, `aggregates: Sequence[(func, column)]`, `keys: Sequence[str] = ()`.
* `table` property traverses to `self.src.table` (single-group scans still
  report the base table).
* `open()` ingests the upstream rows, partitions them by the GROUP BY key
  tuple (NULL keys drop, SQLite parity), and yields one row per group in
  encounter order — `(key_tuple..., agg_0, agg_1, ...)`.
* When no `GROUP BY` is present and no rows match, the executor still
  emits a single result row so `COUNT=0`, `SUM=None`, `AVG=None`,
  `MIN=None`, `MAX=None` surface verbatim.

### Per-aggregate state isolation

Each accumulator has its own dict so multiple aggregates in one plan
don't overwrite each other's slots. The first draft accidentally shared
a single `state` across all funcs; the first test with two aggregates
(`SELECT COUNT(age), COUNT(*) FROM users` over 4 rows including a JSON
NULL) caught it (showed `(7,7)` instead of `(3,4)` and `(4,4)`).

### Sort vs Aggregate

`:class:`Sort`` previously consulted `name_to_idx_for(table)` — a base
table position. When wrapped around an Aggregate, the row layout is
`(key_tuple..., agg_values...)`, not the underlying table. Added a
branch: if `src is Aggregate`, synthesize a column→index map keyed by
`keys` (plus synthetic `f(col)` names for aggregates) so
`ORDER BY <group_col>` resolves correctly. Reference columns of the
underlying table can no longer be referenced in `ORDER BY` once
aggregate is in play — deferred to a follow-up; v0.1 SQL only needs
the group keys to be addressable here.

### Null semantics (SQLite parity)

* `COUNT(*)` — counts every row.
* `COUNT(col)` — skips NULL.
* `SUM/AVG/MIN/MAX(col)` — skip NULL; `SUM/AVG` over zero non-NULL
  rows → `None`; `MIN/MAX` → `None`; `COUNT` over zero rows → `0`.

### Circuit for `Select.aggregates`

The brief documents that `Select.aggregates` is a tuple on the AST.
The parser does not currently populate it (T-3.5 left it defaulting
to `()`). Instead of refactoring the parser in T-5.6, the planner
walks `stmt.columns` and harvests the `Aggregate` AST nodes into a
local `agg_pairs` tuple. When the parser catches up, this can collapse
to `tuple(stmt.aggregates)` — see Deviations.

### Re-export plumbing

`aggregate.py` imports `Plan` from `tinydb.executor.ops` (base class).
`ops.py` needs to re-export the new `Aggregate` plan so public callers
can keep `from tinydb.executor.ops import Aggregate` working. A
top-level `from tinydb.executor.aggregate import Aggregate` in `ops.py`
is a circular import (aggregate.py imports Plan at module top). The
fix is a module-level `__getattr__` in `ops.py` that lazy-resolves
`Aggregate` on first attribute access; a `_LAZY` dict keeps the
mapping explicit and easy to extend.

### Project is identity when aggregates are present

The brief's pragmatic detail ("Project becomes identity when
aggregates are present") became: when `stmt.aggregates` or
`stmt.group_by` is non-empty, the planner emits an `Aggregate` plan
*instead of* the usual `Project`. This keeps the post-Aggregate tuple
as the surfaced row and avoids a second pass that would have to
re-lookup aggregate values by name (no practical index in v0.1).

## Deviations / NITs to carry forward to B6 (transactions/WAL)

1. **`Select.aggregates` never populated by the parser** — T-3.5
   built the AST field but the SELECT parser builder doesn't harvest
   Aggregate AST items into it. The planner compensates by walking
   `stmt.columns` and filtering `isinstance(c, Aggregate)`. Fix this
   in the next batch that revisits SELECT parsing (so downstream
   code can rely on `stmt.aggregates` directly per the public
   contract). v0.1 behaviour is identical either way.
2. **`ORDER BY <aggregate-name>` not supported** — Sort handles
   `ORDER BY <group_col>` (resolves to position 0..N-1) but not
   `ORDER BY MIN(age) DESC` against the synthesized `MIN(age)`
   column. The synthetic name is registered in the column map for
   planner symmetry; the eval path that reads it isn't built. Add
   when the brief that revisits Sort lands.
3. **HAVING not in AST** — confirmed via `grep` (`Select` has
   `group_by: Tuple[str, ...]` and `aggregates: Tuple[Aggregate, ...]`
   but no `having` field). Per the brief, T-5.6 documents this as
   out-of-scope; defer to B9 polish or the next executor batch.
4. **GROUP BY drops rows whose key is NULL** — SQLite parity. Other
   engines (PostgreSQL) include the NULL group as a separate
   partition. Document if/when surface area grows; v0.1 matches the
   project's reference engine (SQLite).
5. **Subqueries / DISTINCT / window funcs / FILTER** — explicitly out
   of scope per the brief; carried forward verbatim.
6. **Aggregate rows are not index-maintained** — the brief explicitly
   tells T-5.6 not to maintain indexes against aggregate results
   (read-only). IndexManager integration belongs to whoever builds
   materialized views (next batch).
7. **`_resolve` re-imports `UnknownColumnError` lazily only in the
   inner helpers — now hoisted to module top** — no performance
   impact; documents the import explicitly.
