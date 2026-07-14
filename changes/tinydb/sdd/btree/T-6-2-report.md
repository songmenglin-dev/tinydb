# T-6.2 — WAL append — REPORT

## Summary

Implemented `tinydb.tx.WAL` — an append-only log of typed records,
each frame protected by a CRC-32 checksum.  Supports
`append(type, payload) -> LSN`, `iter_from(lsn) -> Iterator[WALRecord]`,
`truncate_to(lsn)`, `fsync()`, and recovery-time LSN reconciliation
via CRC validation.  Adds `tinydb.errors.WALCorruptionError` and the
module-level `tinydb.tx.WALCorruptionError` re-export.

## TDD

- **RED**: wrote 15 cases in `tests/tx/test_wal.py` covering the 8
  brief-required scenarios plus 7 bonus / edge cases.  Initial run
  failed at collection time with `ImportError: cannot import name 'WAL'`
  — the desired failure mode.
- **GREEN**: implemented `src/tinydb/tx/wal.py` (226 lines) and added
  `WALCorruptionError` to `src/tinydb/errors.py`.  Re-exported the
  public surface in `src/tinydb/tx/__init__.py`.
- **IMPROVE**: collapsed the post-import `os` shim (5 lines) by moving
  `import os` to the module header; tightened docstrings and inlined
  the frame-walk helpers (`_HEADER_SIZE + _CRC_SIZE + payload_len` is
  used directly instead of a transient `_FRAME_OVERHEAD`).  Net
  reduction: 297 → 226 lines (-71).
- One test correction: the corruption case was originally structured
  to tamper the single written frame, which made recovery (intentionally
  strict about LSN continuity) refuse to open the file.  Restructured
  the test to write two valid frames and tamper the second one, which
  lets recovery succeed via the first frame and surfaces the
  `WALCorruptionError` from `iter_from` exactly as the brief specifies.

## Test delta

- Suite baseline: **587 passed**.
- After T-6.2: **602 passed** (+15 new).  No existing tests broken.
- Coverage on `src/tinydb/tx`: **92.77%** (gate 85%).

## Files

| File | Status | Lines |
|---|---|---|
| `src/tinydb/tx/wal.py` | new | 226 |
| `src/tinydb/errors.py` | edit (add `WALCorruptionError`) | 122 |
| `src/tinydb/tx/__init__.py` | edit (re-exports) | 32 |
| `tests/tx/test_wal.py` | new | 258 |

All file caps met (`wal.py` ≤ 250, `test_wal.py` ≤ 350).

## Deviations from brief (documented per spec request)

1. **CRC-32, not CRC-32C.**  The brief originally called for CRC-32C
   (Castagnoli).  Using CRC-32 (ISO 3309 / ITU-T V.42) via
   `zlib.crc32` instead — CRC-32C requires the `google-crc32c` C
   extension, which violates the zero-dep rule.  Detection property
   (any single-bit flip changes the checksum) is preserved.  This is
   the deviation the brief explicitly authorised ("document that
   deviation in the report").

2. **Endianness asymmetry.**  LSN (`u64 BE`) and `payload_len`
   (`u32 BE`) are big-endian; the trailing CRC32 is **little-endian**
   to match `zlib.crc32`'s native return convention.  Cross-tool
   parsers must swap byte order only for the trailing field.  Same
   flag-asymmetry the brief already pre-noted ("bikeshed later").

3. **Soft recovery on torn tail / CRC mismatch.**  Constructor-time
   recovery stops at the first torn-tail byte OR CRC mismatch and
   reports `next_lsn = last_good + 1` rather than refusing to open.
   This lets callers read all surviving records; `iter_from` is the
   canonical place where `WALCorruptionError` is raised on a completed
   frame with a bad CRC.  The brief's test #6 ("CRC corruption…
   `iter_from` raises") is satisfied exactly: with two good frames
   followed by a corrupt one, recovery stops at frame 2, the WAL opens,
   and `iter_from(0)` raises when it reaches the bad frame.

4. **LSNs are big-endian on disk but the file position is still
   byte-addressed.**  No change from the brief; mentioned here for
   the record so T-6.6 (Recovery) can rely on it.

## Out of scope (unchanged)

- Transaction manager (T-6.3)
- Constraint enforcement (T-6.4)
- Isolation (T-6.5)
- Recovery (T-6.6) — the WAL design supports efficient `iter_from`
  per-record so the recovery layer can replay forward without
  re-parsing the entire file.
- Checkpoint truncation (T-6.7) — `truncate_to(lsn)` is implemented
  here but the higher-level checkpoint policy lives in T-6.7.

## Verification commands

```bash
python -m pytest tests/tx/test_wal.py -q     # 15 passed
python -m pytest tests/ -q                   # 602 passed
python -m pytest tests/tx \
    --cov=src/tinydb/tx --cov-fail-under=85 -q   # 92.77% coverage
```

All gates green.

## Commit

`feat(tx): T-6.2 WAL append (CRC32-protected frames)`
