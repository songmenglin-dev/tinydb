# T-6.7 — Checkpoint (Report)

## Goal
Add a periodic checkpoint that records a WAL anchor as a single `RT_CKPT` frame.  `Recovery.replay()` already ignores unknown record types, so the checkpoint is inert during replay — the B6 gate (11 explicit cases + 100-scenario fuzzy) must continue to pass.

## Files Created / Modified

| Path | Lines | Notes |
| --- | --- | --- |
| `src/tinydb/tx/checkpoint.py` | 84 | New `Checkpoint(pager, wal)` with `run() -> int` that appends one `RT_CKPT` frame whose payload is the LSN at the moment the checkpoint ran.  Public surface is one class. |
| `src/tinydb/tx/__init__.py` | +3 | Re-exports `Checkpoint`; added to `__all__`. |
| `tests/tx/test_checkpoint.py` | 247 | 6 cases covering the brief (empty ckpt, post-DML LSN advance, WAL visibility, recovery regression, two consecutive ckpts, single-frame idempotency). |

File cap met: `checkpoint.py` is 84 lines (cap ≤ 200).

## TDD Trace

1. **RED** — wrote `tests/tx/test_checkpoint.py` importing `tinydb.tx.Checkpoint`.  Collection failed with `ImportError: cannot import name 'Checkpoint' from 'tinydb.tx'`.
2. **GREEN** — added `src/tinydb/tx/checkpoint.py` and re-exported `Checkpoint` in `src/tinydb/tx/__init__.py`.  All 6 tests passed in 0.54 s.
3. **IMPROVE** — implementation is already minimal (one class, one method); added docstrings and slot properties (`pager`, `wal`) for testability/observability.  No refactor required.

## Test Delta

| Suite | Before | After |
| --- | --- | --- |
| `tests/` | 642 passed | **648 passed** (642 + 6 new) |
| `tests/tx` coverage | 93 % | **94.21 %** (gate ≥ 85) |
| `tests/tx/test_checkpoint.py` | — | 6/6 passed |

The 100-scenario fuzzy recovery test (`tests/tx/test_recovery.py::test_fuzzy_recovery_100_sequences`) still passes.

## API

```python
from tinydb.tx import Checkpoint

cp = Checkpoint(pager, wal)
lsn = cp.run()       # appends one RT_CKPT frame; returns the LSN consumed
```

`RT_CKPT` payload layout (already locked by `wal.py`): 8-byte u64 BE carrying the LSN that was next-to-assign when the checkpoint ran.  The frame is recoverable through `wal.iter_from(1)` and ignored by `Recovery.replay()` (the recovery loop already drops unknown types).

## Deviations from the Brief

- **No GitHub reuse search**: the `gh` CLI is not installed in this environment, so the mandatory GitHub-first research step from `development-workflow.md` could not run.  Code reuse was instead derived from the existing `tinydb.tx` module family (WAL append shape, slot-table class style, `_encode_*` helpers) — the implementation reuses the same `struct.pack(">Q", …)` LSN encoding idiom already in `manager.py` and `recovery.py`.  Documented in the report per the team-lead's proceed approval.
- **CodeGraph not initialized**: the indexer is not built for this project, so the `codegraph_*` lookup tools were unavailable.  Used direct `Read` on the known files (already in context from earlier batches) instead.
- **Recovery** still does not act on RT_CKPT — by design.  T-6.7 is a stamp, not a truncation step.  When LSN-per-page tracking lands (deferred), the recovery loop can use the highest LSN of any RT_CKPT seen during analysis as the truncation anchor.

## Commit

```
feat(tx): T-6.7 periodic checkpoint
```

Single commit on `feature/tinydb-v0.1.0` (branch is currently 25 commits ahead of `origin/feature/tinydb-v0.1.0` from prior batches; this commit adds the 26th).