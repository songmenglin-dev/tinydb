# T-9.4 — Scope audit

## Files

- `tests/scope_audit.md` (new) — human-readable audit log.

## Result

All 7 checks PASS.  Two ⚠ benign matches (reserved SQL keywords in
`tokens.py`) are documented; they cause parse errors rather than
silent feature creep.

| # | Check | Result |
|---|---|---|
| 1 | JOIN | ✓ none in executor (⚠ benign: reserved keyword in tokens.py) |
| 2 | ALTER TABLE | ⚠ benign: listed in tokens.py reserved-word table only |
| 3 | CREATE VIEW | ✓ none |
| 4 | TRIGGER | ✓ none |
| 5 | FOREIGN KEY / REFERENCES | ✓ none |
| 6 | Network imports | ✓ none |
| 7 | threading beyond WriteLock | ✓ only in tx/lock.py |

**Net result: NO scope violations.**

## Verification

All 7 grep commands from the brief ran cleanly.  Wider scan finds
the two benign reserved-keyword strings noted above; nothing else.

## Commit

- `d0867c4` — chore: T-9.4 scope audit (no violations)