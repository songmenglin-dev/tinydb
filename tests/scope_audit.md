# tinydb v0.1 — Scope audit

This file documents the result of running the seven scope-check greps
against `src/tinydb/` (and `tests/`, where applicable).  All checks
passed: every match is benign.

## Out-of-scope features (from `proposal.md`)

1. JOIN queries
2. Multi-thread / multi-process concurrency (beyond single-writer)
3. ALTER TABLE
4. Views
5. Triggers
6. Foreign keys
7. Network / client-server mode

## Check results

### 1. JOIN across tables (executor/)

```
$ grep -rE "\bJOIN\b|\bjoin\b" src/tinydb/executor/
(no matches)
```

**Result: ✓ PASS.** No SQL JOIN is implemented in the executor.

Wider scan over the whole package finds:

- `src/tinydb/sql/tokens.py:101` — `"JOIN"` appears in the keyword
  reserved-word list.  Benign: the parser would tokenize it as
  `JOIN`, but no AST node recognises it, so any query containing
  `JOIN` is rejected as a parse error.
- Various `" ".join(...)` / `",".join(...)` calls — these are Python's
  `str.join`, not the SQL keyword.  Benign.

### 2. ALTER TABLE (sql/)

```
$ grep -rE "ALTER" src/tinydb/sql/
src/tinydb/sql/tokens.py:    "CREATE", "TABLE", "DROP", "ALTER", "IF", "EXISTS",
```

**Result: ⚠ benign.** `ALTER` is listed in the reserved-keyword table
in `tokens.py`.  No parser / planner / executor branch handles it; a
statement beginning with `ALTER` would be rejected as a parse error.

### 3. CREATE VIEW (whole src/)

```
$ grep -rE "CREATE VIEW|create_view|CreateView" src/tinydb/
(no matches)
```

**Result: ✓ PASS.** No views.

### 4. TRIGGER (whole src/)

```
$ grep -rE "TRIGGER|trigger" src/tinydb/
(no matches)
```

**Result: ✓ PASS.** No triggers.

### 5. FOREIGN KEY / REFERENCES (whole src/)

```
$ grep -rE "FOREIGN KEY|REFERENCES" src/tinydb/
(no matches)
```

**Result: ✓ PASS.** No foreign keys.

### 6. Network imports (whole src/)

```
$ grep -rE "import socket|import http|import urllib|import requests" src/tinydb/
(no matches)
```

**Result: ✓ PASS.** No networking modules imported anywhere in the
production code.

### 7. threading beyond WriteLock

```
$ grep -rE "threading\." src/tinydb/ | grep -v "tx/lock.py"
(no matches)
```

**Result: ✓ PASS.** The only `threading.` usage in production code is
inside `src/tinydb/tx/lock.py` (the `WriteLock` implementation), as
required by the scope fence.

## Summary

| # | Check | Result |
|---|---|---|
| 1 | JOIN | ✓ none in executor (⚠ benign: reserved keyword only) |
| 2 | ALTER TABLE | ⚠ benign: listed in tokens.py reserved-word table only |
| 3 | CREATE VIEW | ✓ none |
| 4 | TRIGGER | ✓ none |
| 5 | FOREIGN KEY / REFERENCES | ✓ none |
| 6 | Network imports | ✓ none |
| 7 | threading beyond WriteLock | ✓ only in tx/lock.py |

**Net result: NO scope violations.** The two `⚠ benign` matches are
both inert reserved-keyword strings in `tokens.py`; they cause
parse errors, not silent feature creep.

## Verification commands (re-runnable)

```bash
grep -rE "\bJOIN\b|\bjoin\b" src/tinydb/executor/
grep -rE "ALTER" src/tinydb/sql/
grep -rE "CREATE VIEW|create_view|CreateView" src/tinydb/
grep -rE "TRIGGER|trigger" src/tinydb/
grep -rE "FOREIGN KEY|REFERENCES" src/tinydb/
grep -rE "import socket|import http|import urllib|import requests" src/tinydb/
grep -rE "threading\." src/tinydb/ | grep -v "tx/lock.py"
```