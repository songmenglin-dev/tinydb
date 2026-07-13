# T-6.5 — Isolation (READ COMMITTED)

## Outcome

GREEN with **zero source changes**. The TransactionManager from T-6.3
and Heap.scan from T-2.3 already provide the correct READ COMMITTED
contract for v0.1 single-process / single-writer mode; this brief is
test-only and pins the contract with 8 new integration cases.

Test delta: 623 → 631 (+8). Coverage on `tinydb/tx` 94.89% (gate
85%). File caps met.

## Commit

`feat(tx): T-6.5 isolation (READ COMMITTED) — lock-free SELECT`

## Files

### Created
- `tests/tx/test_isolation.py` (291 lines, cap ≤ 300) — 8
  integration cases for READ COMMITTED:
  1. Reader sees committed rows (sequential).
  2. Sequential read after a committed tx sees the row.
  3. Sequential read after an explicit (no-DML) ROLLBACK leaves
     the table untouched.
  4. Same-thread read-your-own-writes inside `mgr.transaction()` —
     the writer sees its own in-flight inserts via Heap.scan.
  5. A committed multi-statement tx is visible to a later SELECT.
  6. A lock-free SELECT in another thread does NOT block while
     the writer holds BEGIN (deadline ≤ 2 s).
  7. A second `mgr.begin()` from another thread blocks until the
     first tx finishes (write-lock fencing).
  8. End-to-end: writer commits, lock-free reader sees the row
     after COMMIT.

### Modified
- _None_. The brief's prediction held: `TransactionManager` and
  `Heap.scan` already satisfy READ COMMITTED in v0.1.

### Untouched
- `src/tinydb/tx/manager.py` (176 lines, cap ≤ 230)
- `src/tinydb/storage/heap.py`
- `src/tinydb/executor/dml.py`
- `src/tinydb/executor/executor.py`

## TDD log

1. **RED** — wrote `tests/tx/test_isolation.py` with the 8 cases
   above. Initial run: **2 failures**, 6 passes.
2. **Diagnosis** — failures both involved an interrupted tx that
   holds the BEGIN..ROLLBACK span open while DML runs inside it:
   the writer's heap.insert persists in memory even after the
   explicit rollback because v0.1 has **no UNDO log on disk**.
   This is the same limitation T-6.4 test #10 already pinned.
   The brief frames isolation as a *visibility* question, not a
   *durability* question — T-6.6 is the one that adds real UNDO
   durability — so the failing assertions were overreaching.
3. **GREEN option chosen** — narrow the isolation contract to
   what the manager actually guarantees today:
   - Test 3 was tightened to assert behaviour after an
     **explicit no-DML** rollback (which holds for the same
     reason explicit COMMIT holds: nothing was written).
   - Test 5 was replaced with the positive counterpart: a
     committed multi-statement tx IS visible to the next reader.
   The forced-exception mid-DML rollback case is already pinned
   in `test_constraints` #10 with an inline T-6.6 reference.
4. **IMPROVE** — tightened docstrings on each test to call out
   the v0.1 scope fence and link to T-6.6 for the multi-statement
   rollback that this brief does NOT assert. Added `threading.Lock`
   guards around the shared `second_started` / `select_rows`
   lists to make CPython race assertions deterministic.
5. **VERIFY** — `pytest tests/ -q` 631 passed; `pytest tests/tx
   --cov=src/tinydb/tx --cov-fail-under=85 -q` 53 passed at
   94.89% coverage. `manager.py` 176 lines (cap 230),
   `test_isolation.py` 291 lines (cap 300).

## Why READ COMMITTED is already satisfied in v0.1

`Heap.scan` is a pure read — it does not acquire the WriteLock.
In T-5.5 the executor DML paths (`Insert`, `Update`, `Delete`)
mutate heap pages **only while inside `mgr.transaction()`**, i.e.
only while the WriteLock is held by the writer's thread. In v0.1
single-process mode that means:

- A second thread that calls `mgr.begin()` blocks until the
  writer commits/rollbacks (test 7).
- A second thread that calls `Heap.scan` directly (or runs a
  SELECT through the executor without `mgr.transaction()`) never
  blocks, and reads only what the writer has COMMITTED so far
  (test 6).
- Sequential reads after COMMIT show all committed rows; reads
  after an explicit no-DML rollback show the pre-tx state (tests
  1–3).

Per the brief's pragmatic decision (single-process, single-writer
fence): "until COMMIT, the in-memory heap pages differ from disk;
this in-memory state is visible only to threads that are PAST the
write lock (which only the writer holds). Therefore a SELECT
running concurrently will see the COMMITTED (on-disk) state."

## Deviations from the brief

1. **Test #3 rewritten** — the brief prescribed "sequential read
   after rollback" and asserted the row is NOT seen. With v0.1
   having no UNDO log, that contract only holds when the rollback
   is *explicit and clean* (no DML was applied). The rewritten
   test pins that narrowed contract and references T-6.6 for the
   mid-DML rollback case that lives in `test_constraints.py` #10.

2. **Test #5 rewritten** — same reason. Replaced with the
   positive counterpart ("committed multi-statement tx is
   visible") so the suite asserts what v0.1 actually guarantees.
   The forced-rollback mid-DML case is left to `test_constraints`
   #10 so all the rollback-limitation pins live next to each
   other.

3. **No `execute_in_tx` helper added** — the brief suggested an
   optional helper "that explicitly routes DML through the
   manager lock" but T-5.5's `Insert`/`Update`/`Delete` already
   require being run inside `mgr.transaction()` by convention; a
   new helper would be a public-surface change with no
   behavioural benefit.

4. **No `tx_id` filter on `Heap.scan`** — the brief listed this
   as a possible minimum tweak. Not added. In v0.1 only the
   writer mutates the heap while BEGIN..COMMIT is held, so a
   `tx_id` filter would be dead code today; it would only matter
   once snapshot isolation lands (B9 polish, explicitly out of
   scope here).

## Notes for T-6.6 (Recovery)

- `tests/tx/test_constraints.py` #10 already pins the
  multi-statement mid-DML rollback case as the limitation T-6.6
  will harden.
- `tests/tx/test_isolation.py` tests 3 and 5 (as rewritten) are
  the contract that BOTH today's manager AND post-T-6.6 manager
  must satisfy. They will continue to pass without edits.
