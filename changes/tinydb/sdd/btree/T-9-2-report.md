# T-9.2 — Coverage audit

## Baseline (before T-9.2)

```
TOTAL                                  3670    294    92%
727 passed in 25.33s
```

Coverage was already 92% at the start of T-9.2 (well above the 80%
gate).  The brief's reference to "T-7.2 close DEVIATION 74.80%" is
from an earlier checkpoint; intermediate batches (T-6.x, T-7.x, T-8.x)
have since added tests that pushed coverage above the gate.

## TDD discipline

Wrote the 3 test modules in **RED-first** style.  Two tests surfaced
real edge-case behaviors the production code did not formally
validate:

1. **`test_crc_mismatch_raises_corruption_error`** — initial
   assertion checked the wrong frame-size arithmetic (had a stray
   `+4` for the payload byte count), masking the real assertion
   below.  Fixed the arithmetic; the CRC-mismatch assertion itself
   passed on the first try after the fix.
2. **`test_date_rejects_datetime`** — initially asserted
   `_CodecError`, but `codec.py`'s DATE branch does not pre-validate
   the type, so the subtraction raises `TypeError` at runtime.
   Updated the test to expect `TypeError` (the actual behavior).
   No production change — T-9.2 is a test-only task.

## Files

- `tests/tx/test_wal_more.py` — 11 tests (corruption, truncation,
  reopen, type bytes, fsync, recover_lsn).
- `tests/type_system/test_codec_more.py` — 25 tests (NULL, JSON null,
  BLOB sizes, DECIMAL, DATETIME TZ, decode errors, encode_row /
  decode_row, value_size parametrized).
- `tests/type_system/test_coerce_more.py` — 28 tests (INT/FLOAT/
  TEXT/BOOL/NULL/DECIMAL/BLOB/JSON strict coercion + widening tags).

## Verification

```
$ python -m pytest tests/ --cov=src/tinydb --cov-fail-under=80 -q
TOTAL                                  3670    277    92%
Required test coverage of 80% reached. Total coverage: 92.45%
814 passed in 25.92s
```

| Module | Before | After | Δ |
|---|---|---|---|
| `src/tinydb/tx/wal.py` | 93% (8 missing) | 94% (7 missing) | +1 line covered |
| `src/tinydb/types/codec.py` | 91% (16 missing) | 98% (3 missing) | +13 lines covered |
| `src/tinydb/types/coerce.py` | 91% (7 missing) | 95% (4 missing) | +3 lines covered |
| **Total suite** | 727 | **814** | **+87 tests** |
| **Total coverage** | 91.99% | **92.45%** | +0.46 pp |

## Gate

`python -m pytest tests/ --cov=src/tinydb --cov-fail-under=80 -q`:
**PASS**.

## Deviations

- The brief was written assuming coverage was at 74.80%.  In reality
  it is at 92% — the gap was closed by earlier batches.  T-9.2 still
  adds 87 new tests because the brief's scope (more coverage on the
  three named modules) was valuable and the per-module coverage did
  improve.
- `test_date_rejects_datetime` updated to expect `TypeError` instead
  of `_CodecError` to match the actual production behavior (the
  DATE branch in `codec.py` does not pre-validate the type).

## Commit

- `8f7000e` — test: T-9.2 coverage to ≥80% (WAL/Codec/Coerce)