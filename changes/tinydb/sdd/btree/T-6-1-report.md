# T-6.1 Report — Write Lock

## Status
GREEN. 9/9 new tx tests pass; full suite 587 passed (578 baseline + 9 new).

## TDD Log
- **RED**: wrote `tests/tx/test_lock.py` (9 cases). Initial failure: `ModuleNotFoundError: No module named 'tinydb.tx'`.
- **GREEN**: implemented `src/tinydb/tx/__init__.py` (13 lines) + `src/tinydb/tx/lock.py` (106 lines). All 9 tests pass.
- **IMPROVE**: used `threading.Condition` with `threading.get_ident()` for holder check (per brief). Single Condition wraps an internal Lock; `_owner` + `_depth` are guarded by the Condition.

## Files Created
- `src/tinydb/tx/__init__.py` — 13 lines (cap 30)
- `src/tinydb/tx/lock.py` — 106 lines (cap 130)
- `tests/tx/__init__.py` — empty
- `tests/tx/conftest.py` — empty
- `tests/tx/test_lock.py` — 9 test cases

## Public Surface
- `tinydb.tx.WriteLock` — reentrant single-writer lock
- `tinydb.tx.WriteLockHeld` — context-manager token returned by `acquire()`

## Deviations / NITs to T-6.2
- Used `threading.Condition()` directly (no constructor argument) instead of `threading.Condition(self._lock)` — `Condition()` already wraps its own RLock internally, which is what we need for reentrant acquire. The brief's code sketch showed `Condition(self._lock)` which is also fine; ours is simpler.
- Added safety: `release()` raises `RuntimeError` if called by a non-owner thread or when depth is already 0. This is a defensive guard for v0.1 (per T-6.1 scope; not strictly required by brief tests).
- `__enter__`/`__exit__` on the `WriteLock` itself mirror `acquire`/`release` for ergonomics (e.g., `with lock: ...`).
- Zero external deps; stdlib `threading` only.

## Verification
- `python -m pytest tests/tx -q` → 9 passed
- `python -m pytest tests/ -q` → 587 passed (578 baseline intact)
- File caps respected: `__init__.py`=13 ≤ 30, `lock.py`=106 ≤ 130

## Commit
`feat(tx): T-6.1 single-writer WriteLock (reentrant)`