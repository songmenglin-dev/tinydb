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
