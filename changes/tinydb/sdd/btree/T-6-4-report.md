# T-6.4 — Constraint enforcement on commit

## Outcome

GREEN. TransactionManager's auto-rollback-on-exception path now
correctly undoes single-statement DML that violates a UNIQUE or NOT
NULL constraint inside `mgr.transaction()`. The post-rollback table
state matches the pre-tx state because the executor probes UNIQUE
indexes BEFORE writing to the heap, so a rejected row never leaves
in-memory residue.

Test delta: 613 → 623 (+10). Coverage on `tinydb/tx` 94.89% (gate
85%). File caps met.

## Commit

`feat(tx): T-6.4 constraint enforcement on commit (DML rollback)`

## Files

### Created
- `tests/tx/test_constraints.py` (229 lines, cap ≤ 250) — 10
  integration cases:
  1. UNIQUE violation rolls back the whole tx.
  2. NOT NULL violation rolls back the whole tx.
  3. Multi-row INSERT where one row violates → whole batch rolled back.
  4. Follow-up tx after a failed tx succeeds.
  5. Empty tx (BEGIN/COMMIT) leaves the table untouched.
  6. UPDATE that matches no rows commits a clean no-op.
  7. UPDATE that violates UNIQUE rolls back the tx.
  8. Multiple UNIQUE indexes — any violation triggers rollback.
  9. `ConstraintViolation` derives from `TinydbError`.
  10. Known limitation pin: multi-statement tx with mid-tx rollback.

### Modified
- `src/tinydb/index/manager.py` (304 → 326 lines) — added
  `IndexManager.check_unique(table, row)` that probes each UNIQUE
  index's B-tree for the key WITHOUT mutating the index. `Insert`
  and `Update` call this before writing to the heap.
- `src/tinydb/executor/dml.py` (170 → 187 lines) — `Insert.open`
  now does a two-phase pass: validate every row (shape + NOT NULL),
  then precheck UNIQUE on the whole batch, then write to the heap.
  `Update.open` calls `check_unique` for the new row before
  `heap.delete + heap.insert`. Also lifted the
  `tuple(row_list)` allocation out of the inner loop.

### Untouched
- `src/tinydb/tx/manager.py` (176 lines, cap ≤ 220) — the brief's
  prediction held: the existing `transaction()` context manager
  already catches `BaseException` and routes it to `rollback()`,
  which is exactly the constraint-violation path.

## TDD log

1. **RED** — wrote `tests/tx/test_constraints.py` with the 10 cases.
   Initial run: 5 failures, 4 passes (one skipped on import order).
2. **Diagnosis** — failures all of the shape "the rejected INSERT
   left an in-memory heap residue". Root cause: T-5.5
   `Insert.open()` did `heap.insert()` BEFORE `indexer.on_insert()`,
   so the row landed in the heap, then the indexer raised
   `ConstraintViolation`. The manager correctly emitted
   RT_ROLLBACK and released the lock, but the dirty heap page was
   never restored.
3. **GREEN option chosen** — precheck UNIQUE in the index manager
   before mutating the heap. Two-phase INSERT (validate all, write
   all) makes single-statement rollback correct with no manager
   changes. Multi-statement rollback is the next-layer limitation
   (see below).
4. **IMPROVE** — refactored `Insert.open` to lift
   `tuple(row_list)` out of the inner write loop; collapsed
   `test_constraints.py` to a 229-line pytest fixture pattern with
   10 compact test functions.
5. **VERIFY** — `pytest tests/ -q` 623 passed; `pytest tests/tx
   --cov=src/tinydb/tx --cov-fail-under=85 -q` 45 passed at
   94.89% coverage.

## Deviations from the brief

1. **Added `IndexManager.check_unique`** — not in the brief, but
   needed because the brief said "the manager just needs to catch
   these and route them to rollback", which presumes the heap is
   in a recoverable state on rollback. T-5.5 was already inserting
   into the heap before checking uniqueness, so the heap had to be
   kept clean by an upstream precheck. Public surface unchanged
   (this is a new private method on `IndexManager`).

2. **Multi-statement-tx rollback pinned as a known limitation
   (test #10)** — the brief explicitly flagged that v0.1 has NO
   persistent undo log yet and that T-6.6 will wire it. With the
   batch precheck, a SINGLE INSERT statement rolls back cleanly.
   A multi-statement tx where the second statement violates a
   constraint leaves the first statement's writes in the
   in-memory heap. Test #10 pins the current behaviour with an
   inline comment that names T-6.6 as the tightening point.

3. **Two-phase `Insert.open`** — separates validation
   (shape + NOT NULL) from UNIQUE precheck from heap writes. The
   brief's pseudocode didn't require this, but the brief's "verify
   the table state is correct post-rollback" implicitly required
   it once we found the test failures.

4. **`ConstraintViolation` covers both UNIQUE and NOT NULL**
   (test #9) — `NotNullViolation` is a subclass of
   `ConstraintViolation`, so a single `except ConstraintViolation`
   catches both. Test #9 confirms the public surface.

## Notes for T-6.6

- The `check_unique` helper added in T-6.4 is also useful for
  T-6.6: the recovery UNDO log only needs to undo HEAP writes
  (B-tree pages can be rebuilt from the heap on crash recovery,
  per the design notes). With the precheck, the only heap writes
  inside a tx are those that pass UNIQUE — i.e. the rows T-6.6
  actually has to record in the undo log.
- Test #10 in `tests/tx/test_constraints.py` should be tightened
  to assert `== [(1, 'alice', 30)]` once T-6.6 lands; the inline
  comment names this exact assertion.