# T-6.3 — Transaction manager — Report

## Commit
`feat(tx): T-6.3 TransactionManager (BEGIN/COMMIT/ROLLBACK)`

## Test delta
| Phase | Count |
|-------|-------|
| Baseline (T-6.2) | 602 |
| New (T-6.3)      | +11 |
| **Total green**  | **613** |

`python -m pytest tests/ -q` → `613 passed in 6.25s`

T-6.3 coverage gate: `pytest tests/tx --cov=src/tinydb/tx --cov-fail-under=85`
→ `94.89%` coverage on `tinydb.tx` (gate 85% reached).

```
src/tinydb/tx/__init__.py       4      0   100%
src/tinydb/tx/lock.py          41      4    90%
src/tinydb/tx/manager.py       68      0   100%
src/tinydb/tx/wal.py          122      8    93%
TOTAL                         235     12    95%
```

## Files

| Path | Lines | Δ | Purpose |
|------|-------|---|---------|
| `src/tinydb/tx/manager.py`     | 176 | new | `TransactionManager`, `TransactionContext`, `NestedTransactionError` |
| `src/tinydb/tx/__init__.py`    |  42 | +7  | Re-export the three new symbols |
| `tests/tx/test_manager.py`     | 213 | new | 11 cases covering happy path, exception path, nested tx, lock release, stale-tx guard, monotonic tx_id, payload encoding, and cross-thread blocking |

File caps:
- `src/tinydb/tx/manager.py` ≤ 200 → **176** ✓
- `src/tinydb/tx/__init__.py` ≤ 80 (was 35, +45 OK) → **42** ✓
- `tests/tx/test_manager.py` ≤ 300 → **213** ✓

## Deviations from the brief

1. **Lock lifetime.** The brief shows `begin()` using `with self._lock.acquire():` and `return`-ing inside the block. With `WriteLock` that pattern releases the lock as soon as `begin()` returns, which breaks the cross-thread blocking contract required by case #8 (T2 must block until T1 commits). I switched to a manual acquire: `held = self._lock.acquire()` and stash `held` on `self._held`; `commit()` / `rollback()` release it through a small `_release_lock()` helper. This preserves the brief's semantics while making the lock survive for the whole tx lifetime.

2. **`begin()` lock-then-check order.** The brief shows the nested-tx check *before* the lock acquire. That order would make a concurrent `begin()` from a second thread raise `NestedTransactionError` instead of blocking — contradicting case #8. I moved the check *inside* the critical section: concurrent callers queue on the lock and only the nested case (which can only happen from the same thread, since only the holder can have set `self._active_tx`) raises. The nested-tx test still passes; the threading test now blocks as required.

3. **Public surface.** Brief lists `TransactionManager`, `TransactionContext`, `NestedTransactionError`. All three are exported from `tinydb.tx` and `tinydb.tx.manager`. No other public additions.

4. **Pager stand-in.** The brief allows tests "without an actual Pager"; I used a minimal `_StubPager` class in the test helpers so tests stay isolated from Batch 2's storage layer.

5. **Stale-tx guard is `ValueError`** (per brief spec).

## Public API

```python
from tinydb.tx import (
    TransactionManager,    # write-lock + WAL coordinator
    TransactionContext,    # frozen dataclass: tx_id, begin_lsn, manager
    NestedTransactionError,
)

mgr = TransactionManager(pager, wal)
with mgr.transaction() as tx:
    ...                # auto-COMMIT on clean exit, auto-ROLLBACK on raise

mgr.begin()             # → TransactionContext (blocks on lock)
mgr.commit(tx)          # fsync WAL, release lock
mgr.rollback(tx)        # fsync WAL, release lock
mgr.active_tx           # current TransactionContext | None
```

`NestedTransactionError` derives from `TinydbError`, so callers can
catch a single base type.

## Out of scope (deferred to later tasks)
- Constraint enforcement on commit (T-6.4)
- Isolation / READ COMMITTED (T-6.5)
- Recovery REDO/UNDO (T-6.6)
- Checkpoint (T-6.7)
- Cross-process locks (single-process only per DP-0)