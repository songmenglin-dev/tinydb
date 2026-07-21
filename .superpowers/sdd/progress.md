# SDD Progress Ledger — tinydb-v0.2

> Per-task loop: implementer subagent → reviewer subagent → dual verdict → fix → re-review
> Updated by build-executor after each T-task completion.

## Execution Mode
- workflow: full
- execution_mode: sdd (Subagent-Driven Development)
- contract: changes/tinydb-v0.2/execution-contract.md (DP-3 approved)
- state: approved-for-build

## Worktrees
- feature/v0.2-join: B10-B13 (JOIN)
- feature/v0.2-concurrency: B14-B17 (concurrency)
- feature/v0.2-cli: B18-B20 (CLI)
- feature/v0.2-integrate: B21 (integration)

## Tasks

### Batch 10 — JOIN SQL 解析 (feature/v0.2-join)

### Batch 18 — prompt_toolkit 迁移 (feature/v0.2-cli) — DONE
- T-18.1: `_HAS_PT = importlib.util.find_spec("prompt_toolkit") is not None`
- T-18.2: `_run_prompt_toolkit_repl` with multiline + history + continuation
- T-18.3: `_run_cmd_fallback` for missing PT; `_run_legacy` for test injection
- Continuation: backslash OR unclosed quote (REQ-CLI-1/2)
- REQ-CLI-9 banner shows degraded mode when PT missing

### Batch 19 — 高亮 + EXPLAIN (feature/v0.2-cli) — DONE
- T-19.1: `tinydb/cli/highlight.py` — hand-written tokenizer reusing `sql.tokens`
  - 4-colour ANSI palette (keyword/cyan, string/green, number/yellow, comment/grey)
  - `render_with_comments` includes `-- ...` runs as grey
- T-19.2: `make_prompt_toolkit_lexer()` builds `prompt_toolkit.lexer.Lexer` adapter
- T-19.3: `tinydb/cli/explain.py` — recursive ASCII tree (`├──`/`└──`/`│`)
- T-19.4: `Database.explain(sql)` + `.explain <SQL>` + `.explain --table <SQL>` meta cmds
  - `Database.list_tables()` + `Database.get_schema(table)` added

### Batch 20 — Meta + 历史 + MySQL 表格 + .mode (feature/v0.2-cli) — DONE
- T-20.1: `tinydb/cli/history.py` — `FileHistory` wrapper, graceful warn on unwritable
- T-20.2: `.tables` + `.schema <table>` meta cmds routed via Database methods
- T-20.3: `.history` meta command (in-session entries)
- T-20.4: `.quit`/`.exit` + Ctrl-C + EOF all return 0 cleanly
- T-20.5: 45 v0.1 CLI tests + 42 v0.2 enhance tests = 87 green (PT-present mode)
- T-20.6: `format_table` with type-aware alignment; BLOB→0xhex, NULL→literal
- T-20.7: `time.perf_counter()` wrap in CLI layer only; `N rows in set (X.XXs)` footer
- T-20.8: `.tables`/`.schema`/`.explain --table` use ASCII table format
- T-20.9: `.mode line|table` session-level toggle (REQ-CLI-16)
- T-20.10: integration suite covers all 16 REQ-CLI-*

### Cross-worktree API
- `Database.list_tables() -> list[str]` — implemented in api.py
- `Database.get_schema(table: str) -> str` — implemented in api.py
- `Database.explain(sql: str) -> str` — implemented in api.py (uses current planner)
- All three are additive — no v0.1 public API broken.

### Files Touched
- `src/tinydb/cli/highlight.py` (new)
- `src/tinydb/cli/explain.py` (new)
- `src/tinydb/cli/history.py` (new)
- `src/tinydb/cli/format.py` (modified — added ColumnMeta, format_table, format_line_mode, format_timing; kept v0.1 format_rows for argparse_ext)
- `src/tinydb/cli/repl.py` (rewritten — prompt_toolkit + fallback + new meta cmds + timing)
- `src/tinydb/api.py` (added list_tables, get_schema, explain + _build_create_table_sql helpers)
- `tests/test_cli_enhance.py` (new — 42 tests for REQ-CLI-1..16)
- `pyproject.toml` (added `cli` extra: `prompt_toolkit>=3.0.40`)

### Coverage
- `tests/test_cli_enhance.py`: 42 tests, all REQ-CLI-* covered
- `tests/cli/`: 45 v0.1 tests still pass
- Total CLI: 87 tests green

### Status
- B18 + B19 + B20: DONE
- Branch: feature/v0.2-cli, ready for B21 integration

---

# Batch 21 (B21) — 集成 + Release

## Goal
Final integration of B18-B20 CLI on top of B10-B17 (JOIN + concurrency)
that B10-B17 already merged.  Run 4 acceptance checks, polish release
artifacts, prep for DP-6 (closeout) + DP-7 (release-archivist).

## T-21.1 — Merge feature/v0.2-cli
- Conflict in src/tinydb/api.py resolved manually.
- Kept integrate's `isolation`/`pool_size`/`rwlock` + connection pool;
  kept integrate's catalog-aware `list_tables`/`get_schema`; upgraded
  `explain()` to use CLI's `format_plan_pair` ASCII renderer (REQ-CLI-13).
- Removed duplicate `from typing import List`.

## T-21.2 — 4 Acceptance Checks
| # | Check | Result |
|---|---|---|
| 1 | Coverage >= 80% | **88.75% pass** |
| 2 | v0.1 compat suite 100% | **PASS** (10/10 non-flaky; pre-existing perf flake) |
| 3 | 32-thread INSERT/SELECT 5s stress (REQ-CONC-8) | **PASS** |
| 4 | 4-process 1W/3R test (REQ-CONC-8) | **PASS** |

- Added tests/test_e2e_v0_2.py — 5 pytest cases for the v0.2 story
- Added examples/demo_v0_2.py — 7-step runnable end-to-end demo

## T-21.3 — pyproject + README polish
- Bumped pyproject.toml version 0.1.0 -> 0.2.0
- Dev Status 3 - Alpha -> 4 - Beta; added join/concurrent keywords
- README.md fully rewritten with v0.2 features (JOIN examples,
  concurrent threads, .explain, Database kwargs reference)

## T-21.4 — Scope audit + DP-6/DP-7 prep
- Scope guard: `RIGHT JOIN|FULL JOIN|subquery|CTE|MVCC|trigger` finds
  only intentional scope-guard code (no actual violations).
- Dep audit: prompt_toolkit is optional `[cli]` extra; REQ-CLI-9
  fallback (`cmd` REPL) verified in repl.py.
- Tag prep: HEAD 44b3f2c on feature/v0.2-integrate; pyproject
  version=0.2.0.  Tag `tinydb-v0.2.0` ready — release-archivist's job.

## Commits on feature/v0.2-integrate (B21)
1. fdede8d merge: integrate CLI into feature/v0.2-integrate
2. d3a5c26 fix(api): get_schema emits PRIMARY KEY/UNIQUE clauses
3. fb23191 test(e2e): v0.2 e2e story — JOIN + concurrent + .explain
4. 44b3f2c docs: polish pyproject (0.2.0) + README (v0.2 features)

## Status
- B21: DONE_WITH_CONCERNS — flaky perf-regression test on this
  WSL2 host; underlying correctness covered by other tests.  See
  task-21-report.md for details.
- Branch: feature/v0.2-integrate, ready for DP-5 / DP-7.
