# Tasks: tinydb

> 任务按 8 个批次 (Batch) 组织。每个任务: 精确文件路径、5 步 TDD phase、Interfaces、依赖关系。
> 步骤原子性: 每个 TDD 子步骤 2-5 分钟可完成。
> 覆盖映射: 每个 REQ-* 至少由一个 task 验证。

---

## File Structure

### Create — Project Skeleton
- `pyproject.toml` — Python 包元数据 + 依赖声明 (无运行时依赖) + pytest 配置
- `README.md` — 安装、快速开始、示例
- `.gitignore` — Python 标准忽略 (`.venv/`, `__pycache__/`, `*.pyc`, `*.db`, `dist/`, `build/`)
- `src/tinydb/__init__.py` — 公共 API: `open(path)`, `Database`, 错误类型 re-export
- `src/tinydb/_version.py` — 版本字符串 `__version__ = "0.1.0"`
- `src/tinydb/errors.py` — `TinydbError`, `ParseError(line, col, msg)`, `ConstraintViolation`, `NotNullViolation`, `TypeMismatchError`
- `tests/conftest.py` — 共享 fixture: `tmp_db` 临时数据库文件路径, `make_db()` 工厂

### Create — Type System (`src/tinydb/types/`)
- `src/tinydb/types/__init__.py` — 暴露 `TypeTag`, `Column`, `coerce_value`
- `src/tinydb/types/codec.py` — `TypeTag` 枚举、`encode_value(v) -> bytes`、`decode_value(buf) -> (value, bytes_consumed)`
- `src/tinydb/types/system.py` — `Column(name, type_tag, not_null=False, primary_key=False, unique=False)`、类型名↔TypeTag 映射
- `src/tinydb/types/coerce.py` — `coerce_value(python_value, target_tag) -> (encoded_value, tag)`，按 REQ-TYP-6 强制规则

### Create — Storage (`src/tinydb/storage/`)
- `src/tinydb/storage/__init__.py` — 暴露 `Pager`, `BufferPool`
- `src/tinydb/storage/pager.py` — `Pager(path, page_size=4096)` 4KB 页 I/O + 文件头 (magic, version, page_size)
- `src/tinydb/storage/buffer_pool.py` — `BufferPool(pager, capacity=64)` LRU，命中计数
- `src/tinydb/storage/heap.py` — `Heap(pager, table_id)` 槽位管理，insert/read/delete
- `src/tinydb/storage/catalog.py` — `Catalog(pager)` 持久化表 schema 与表列表 (页 1-3 保留)
- `src/tinydb/storage/free_space.py` — `FreeSpaceMap` 跟踪页剩余空间

### Create — SQL (`src/tinydb/sql/`)
- `src/tinydb/sql/__init__.py` — 暴露 `parse(sql) -> Statement`
- `src/tinydb/sql/tokens.py` — `Token` 类型 + `tokenize(sql) -> list[Token]`
- `src/tinydb/sql/ast.py` — AST 节点: `CreateTable`, `DropTable`, `Insert`, `Select`, `Update`, `Delete`, `Expr`, `BinaryOp`, `Literal`, `ColumnRef`, `OrderBy`, `Limit`, `GroupBy`, `Aggregate`
- `src/tinydb/sql/parser.py` — `parse(sql: str) -> Statement` 递归下降主入口

### Create — Index (`src/tinydb/index/`)
- `src/tinydb/index/__init__.py` — 暴露 `BTreeIndex`
- `src/tinydb/index/btree.py` — `BTreeNode` (Leaf/Internal), `BTreeIndex(pager, root_pid, key_type)`, insert/delete/search/range_scan
- `src/tinydb/index/manager.py` — `IndexManager(catalog)` 按列名查找/创建/删除索引

### Create — Executor (`src/tinydb/executor/`)
- `src/tinydb/executor/__init__.py` — 暴露 `Executor`
- `src/tinydb/executor/planner.py` — `plan(stmt: Statement, catalog) -> Plan` AST→计划
- `src/tinydb/executor/ops.py` — `SeqScan`, `IndexScan`, `Filter`, `Project`, `Sort`, `Limit`, `Insert`, `Update`, `Delete`
- `src/tinydb/executor/aggregate.py` — `Aggregate(count/sum/avg)` + `GroupBy` operator

### Create — Transaction (`src/tinydb/tx/`)
- `src/tinydb/tx/__init__.py` — 暴露 `TransactionManager`
- `src/tinydb/tx/wal.py` — `WAL(pager)` 追加式日志，frame = `[lsn:u64, type:u8, payload:bytes, crc:u32]`
- `src/tinydb/tx/manager.py` — `TransactionManager(pager, wal, lock)` BEGIN/COMMIT/ROLLBACK
- `src/tinydb/tx/lock.py` — `WriteLock` 上下文管理器 (`threading.RLock`)
- `src/tinydb/tx/recovery.py` — `recover(pager, wal)` REDO/UNDO 阶段

### Create — API (`src/tinydb/`)
- `src/tinydb/api.py` — `Database(path)` / `Connection` 类，公共方法 `execute(sql) -> list[dict]`

### Create — CLI (`src/tinydb/cli/`)
- `src/tinydb/cli/__init__.py`
- `src/tinydb/cli/__main__.py` — `python -m tinydb` 入口
- `src/tinydb/cli/repl.py` — `TinydbShell(cmd.Cmd)` REPL 实现
- `src/tinydb/cli/format.py` — `format_table(rows, columns) -> str` 表格输出
- `src/tinydb/cli/argparse_ext.py` — `build_parser()` argparse 配置

### Create — Tests (`tests/`)
- `tests/conftest.py` — 共享 fixture
- `tests/types/test_codec.py` — codec 编解码
- `tests/types/test_coerce.py` — 类型强制
- `tests/storage/test_pager.py` — 页 I/O
- `tests/storage/test_buffer_pool.py` — LRU
- `tests/storage/test_heap.py` — 堆表
- `tests/storage/test_catalog.py` — 目录
- `tests/sql/test_tokens.py` — 词法
- `tests/sql/test_parser_ddl.py` — DDL 解析
- `tests/sql/test_parser_dml.py` — DML 解析
- `tests/sql/test_parser_expr.py` — 表达式
- `tests/index/test_btree.py` — B-tree 操作
- `tests/executor/test_select.py` — SELECT 执行
- `tests/executor/test_aggregate.py` — 聚合
- `tests/executor/test_dml.py` — DML 执行
- `tests/tx/test_wal.py` — WAL 帧
- `tests/tx/test_transaction.py` — ACID
- `tests/tx/test_recovery.py` — 恢复
- `tests/cli/test_repl.py` — REPL
- `tests/cli/test_argparse.py` — 参数
- `tests/integration/test_e2e.py` — 端到端 SQL 流程
- `tests/integration/test_crash_recovery.py` — 模拟崩溃恢复

---

## Interfaces (跨批次契约)

```
Pager:
  open(path: str) -> Pager
  read_page(pid: int) -> bytes                 # 4096 B
  write_page(pid: int, data: bytes) -> None
  allocate_page() -> int                       # 新页 pid
  free_page(pid: int) -> None
  close() -> None

BufferPool:
  __init__(pager: Pager, capacity: int = 64)
  fetch_page(pid: int) -> bytes
  mark_dirty(pid: int) -> None
  flush_all() -> None                          # commit 路径

Catalog:
  __init__(pager: Pager)
  create_table(name: str, columns: list[Column]) -> TableId
  drop_table(name: str) -> None
  get_table(name: str) -> TableMeta
  list_tables() -> list[str]

Heap:
  __init__(pager: Pager, table_id: TableId)
  insert(encoded_row: bytes) -> Rid
  read(rid: Rid) -> bytes | None
  delete(rid: Rid) -> None
  scan() -> Iterator[Rid]

Codec:
  encode_value(v: Any, tag: TypeTag) -> bytes
  decode_value(buf: bytes, offset: int) -> tuple[Any, int]

Parser:
  parse(sql: str) -> Statement
  raise ParseError(line, col, msg) on failure

BTreeIndex:
  search(key: Any) -> list[Rid]                # 等值
  range(lo: Any, hi: Any, inclusive: bool) -> Iterator[Rid]
  insert(key: Any, rid: Rid) -> None
  delete(key: Any, rid: Rid) -> None
  flush() -> None

Planner:
  plan(stmt: Statement, catalog: Catalog, indexes: IndexManager) -> Plan

Executor:
  execute(plan: Plan) -> list[dict]

WAL:
  append(record_type: u8, payload: bytes) -> LSN
  flush() -> None                              # fsync
  iter_from(lsn: int) -> Iterator[WALRecord]

TransactionManager:
  begin() -> TxId
  commit(tx_id: TxId) -> None
  rollback(tx_id: TxId) -> None
  active_tx() -> TxId | None

Database (public):
  open(path: str) -> Database
  execute(sql: str) -> list[dict]
  close() -> None
```

---

## Batches

### Batch 1 — Foundation (no DB I/O)

**T-1.1** Project skeleton
- File: `pyproject.toml`, `src/tinydb/__init__.py`, `src/tinydb/_version.py`, `.gitignore`, `README.md` (stub), `tests/conftest.py`
- TDD: RED 写 `tests/test_smoke.py::test_imports` (期望 `import tinydb` 成功) → GREEN 写 pyproject + `__init__.py` → IMPROVE 加 `_version.py` 与 re-export
- Interfaces: `tinydb.__version__ -> str`
- Depends on: —
- Covers: 项目入口

**T-1.2** Errors module
- File: `src/tinydb/errors.py`
- TDD: RED 写 `tests/test_errors.py::test_parse_error_carries_line_col` 与 `test_constraint_violation_is_tinydb_error` → GREEN 实现 → IMPROVE 加 `__str__` 位置格式
- Interfaces: `ParseError(line, col, msg)`, `ConstraintViolation`, `NotNullViolation`, `TypeMismatchError`, base `TinydbError`
- Depends on: T-1.1
- Covers: REQ-SQL-7 (错误报告基础)

**T-1.3** Type system: TypeTag + Column
- File: `src/tinydb/types/__init__.py`, `src/tinydb/types/system.py`
- TDD: RED `tests/types/test_system.py::test_type_tag_values_unique` + `test_column_flags` → GREEN → IMPROVE
- Interfaces: `TypeTag(Int=0x01, Float=0x02, Text=0x03, Bool=0x04, Null=0x00, Date=0x05, Time=0x06, Datetime=0x07, Decimal=0x08, Blob=0x09, Json=0x0a)`, `Column(name, tag, not_null=False, primary_key=False, unique=False)`, `parse_type_name(name: str) -> TypeTag` (INT/INTEGER, FLOAT/DOUBLE/REAL, TEXT/VARCHAR, BOOL/BOOLEAN, DATE, TIME, DATETIME/TIMESTAMP, DECIMAL/NUMERIC, BLOB/BYTEA, JSON)
- Depends on: T-1.2
- Covers: REQ-TYP-8 (类型持久化元数据)

**T-1.4** Codec: encode/decode roundtrip
- File: `src/tinydb/types/codec.py`
- TDD: RED 写 11 个类型 roundtrip 测试 (parametrize) → GREEN 写 encode/decode 通用实现 (1B tag + length-prefix for vars) → IMPROVE 错误信息
- Interfaces: `encode_value(v, tag) -> bytes`, `decode_value(buf, offset=0) -> (value, next_offset)`, `value_size(v, tag) -> int`
- Depends on: T-1.3
- Covers: REQ-TYP-1~5, REQ-TYP-9~14 (序列化层)

**T-1.5** Coercion
- File: `src/tinydb/types/coerce.py`
- TDD: RED `tests/types/test_coerce.py` 覆盖 REQ-TYP-6 所有场景 (整数→浮点 允许, 浮点→整数 拒绝, 字符串→数字 拒绝) → GREEN → IMPROVE
- Interfaces: `coerce_value(python_value, target_tag) -> (encoded_value, tag)`, 严格白名单
- Depends on: T-1.4
- Covers: REQ-TYP-6, REQ-TYP-7

**Gate for Batch 1**: `pytest tests/types tests/test_errors.py tests/test_smoke.py --cov=src/tinydb/types --cov=src/tinydb/errors --cov-fail-under=85` 通过

---

### Batch 2 — Storage (single-file persistence)

**T-2.1** Pager
- File: `src/tinydb/storage/__init__.py`, `src/tinydb/storage/pager.py`
- TDD: RED 写 `tests/storage/test_pager.py` 覆盖: 创建新文件、读取已存在文件、文件头 magic/version/page_size、读写 page_0 → GREEN → IMPROVE 加 `__enter__/__exit__`
- Interfaces: 见上
- Depends on: T-1.1
- Covers: REQ-STO-1, REQ-STO-2, REQ-STO-4 (分配/释放页)

**T-2.2** BufferPool
- File: `src/tinydb/storage/buffer_pool.py`
- TDD: RED 写 LRU 行为测试 (命中计数、驱逐最旧、容量边界) → GREEN → IMPROVE 加 `stats()`
- Interfaces: 见上
- Depends on: T-2.1
- Covers: REQ-STO-3, REQ-STO-8 (刷盘)

**T-2.3** Heap (table-level record storage)
- File: `src/tinydb/storage/heap.py`, `src/tinydb/storage/free_space.py`
- TDD: RED 写 insert→read→delete→scan 流程测试 + 跨页溢出测试 → GREEN → IMPROVE
- Interfaces: `Rid(page_id, slot_id)`, 见上
- Depends on: T-2.2
- Covers: REQ-STO-2 (跨页), REQ-STO-5, REQ-STO-7

**T-2.4** Catalog (schema persistence)
- File: `src/tinydb/storage/catalog.py`
- TDD: RED 写 `tests/storage/test_catalog.py` 覆盖 create_table/drop_table/list_tables/重启保留 → GREEN → IMPROVE
- Interfaces: `TableId(int)`, `TableMeta(name, columns)`, 见上
- Depends on: T-2.3
- Covers: REQ-STO-6

**Gate for Batch 2**: `pytest tests/storage --cov=src/tinydb/storage --cov-fail-under=85` 通过；可独立运行 `python -c "from tinydb.storage import Pager, BufferPool; ..."` 端到端

---

### Batch 3 — SQL Parser (no execution yet)

**T-3.1** Tokenizer
- File: `src/tinydb/sql/__init__.py`, `src/tinydb/sql/tokens.py`
- TDD: RED 写 `tests/sql/test_tokens.py` 覆盖: 关键字 (大写/小写)、标识符、字面量 (int/float/string/bool/null)、运算符、分号 → GREEN → IMPROVE 位置追踪
- Interfaces: `Token(kind, value, line, col)`, `tokenize(sql) -> list[Token]`, 关键字集合
- Depends on: T-1.3
- Covers: REQ-SQL-8 (错误位置基础)

**T-3.2** AST node classes
- File: `src/tinydb/sql/ast.py`
- TDD: RED 写每个节点 dataclass 构造测试 → GREEN → IMPROVE `__repr__`
- Interfaces: 所有节点 (见 design)
- Depends on: T-3.1
- Covers: AST 中间表示

**T-3.3** DDL parser (CREATE/DROP TABLE)
- File: `src/tinydb/sql/parser.py` (DDL 子集)
- TDD: RED 写 `tests/sql/test_parser_ddl.py` 7+ 场景 → GREEN → IMPROVE
- Interfaces: `parse_ddl(tokens) -> CreateTable | DropTable`
- Depends on: T-3.2
- Covers: REQ-SQL-1

**T-3.4a** Expression parser (literal/column-ref/binary-op/AND/OR/IS NULL)
  - File: `src/tinydb/sql/parser.py` 表达式子集
  - TDD: RED 10+ 场景 (RE-QSQL-3, REQ-SQL-4 部分, REQ-TYP-7) → GREEN → IMPROVE
  - Interfaces: `parse_expr(tokens) -> Expr`
  - Depends on: T-3.3
  - Covers: REQ-SQL-3, REQ-SQL-8, REQ-TYP-7 (部分)
- **T-3.4b** DML full parse
  - TDD: RED 8+ 场景 (INSERT/SELECT/UPDATE/DELETE) → GREEN → IMPROVE
  - Depends on: T-3.4a
  - Covers: REQ-SQL-2

**T-3.5** ORDER BY / LIMIT / OFFSET / GROUP BY / 聚合
- TDD: RED 5+ 场景 → GREEN → IMPROVE
- Depends on: T-3.4b
- Covers: REQ-SQL-4, REQ-SQL-6

**T-3.6** 约束字面量 (PRIMARY KEY / NOT NULL / UNIQUE) + 类型字面量 (DATE '...' etc.)
- TDD: RED 5+ 场景 → GREEN → IMPROVE
- Depends on: T-3.3
- Covers: REQ-SQL-5, REQ-TYP-9~14 字面量

**T-3.7** 错误报告
- TDD: RED 写 ParseError 行/列测试 (5+ 场景) → GREEN 完善 `parse()` 顶层包装 → IMPROVE
- Depends on: T-3.6
- Covers: REQ-SQL-7

**T-3.8** 公共 `parse(sql)` 入口
- TDD: RED 写 `tests/sql/test_parser_end_to_end.py` 8+ 真实 SQL 字符串 → GREEN → IMPROVE
- Depends on: T-3.7
- Covers: parser 集成

**Gate for Batch 3**: `pytest tests/sql --cov=src/tinydb/sql --cov-fail-under=85` 通过

---

### Batch 4 — B-tree Index

**T-4.1** B-tree leaf node
- File: `src/tinydb/index/__init__.py`, `src/tinydb/index/btree.py`
- TDD: RED 写 leaf insert + scan 顺序测试 (无需分裂) → GREEN → IMPROVE
- Interfaces: `LeafNode(keys, rids)`, `serialize/deserialize`
- Depends on: T-2.3
- Covers: REQ-IDX-1 (叶子节点部分)

**T-4.2** B-tree 节点分裂与内部节点
- TDD: RED 写超过阶数后分裂 + 父节点生成测试 → GREEN → IMPROVE
- Depends on: T-4.1
- Covers: REQ-IDX-1 (内部节点), REQ-IDX-6 (持久化基础)

**T-4.3** B-tree 等值 + 范围查找
- TDD: RED 写 search + range_scan 测试 (5+ 场景) → GREEN → IMPROVE
- Depends on: T-4.2
- Covers: REQ-IDX-2, REQ-IDX-3

**T-4.4** B-tree 删除与重平衡
- TDD: RED 写 delete + 合并/重分配测试 (8+ 场景含连续删除、最左/最右) → GREEN → IMPROVE
- Depends on: T-4.3
- Covers: REQ-IDX-1 (合并)

**T-4.5** 复合键索引
- TDD: RED 写 (a, b) 复合键测试 → GREEN → IMPROVE
- Depends on: T-4.4
- Covers: REQ-IDX-7

**T-4.6** IndexManager (catalog 集成)
- File: `src/tinydb/index/manager.py`
- TDD: RED 写 `tests/index/test_manager.py` 覆盖按列名 CRUD 索引 + UNIQUE 触发 → GREEN → IMPROVE
- Depends on: T-4.5
- Covers: REQ-IDX-4, REQ-IDX-5, REQ-IDX-6 (跨重启)

**Gate for Batch 4**: `pytest tests/index --cov=src/tinydb/index --cov-fail-under=85` 通过

---

### Batch 5 — Query Executor

**T-5.1** Plan tree + Planner
- File: `src/tinydb/executor/__init__.py`, `src/tinydb/executor/planner.py`, `src/tinydb/executor/ops.py` (基础)
- TDD: RED 写 `tests/executor/test_planner.py` 覆盖 AST→Plan 转换 (SELECT/INSERT/UPDATE/DELETE) → GREEN → IMPROVE
- Interfaces: `Plan`, `SeqScan`, `IndexScan`, `Filter`, `Project`, `Sort`, `Limit`, `Insert`, `Update`, `Delete`
- Depends on: T-3.8, T-4.6, T-2.4
- Covers: REQ-QEX-1 (基础)

**T-5.2** SeqScan + Filter + Project
- TDD: RED 写 WHERE 过滤 + 列投影测试 (6+ 场景) → GREEN → IMPROVE
- Depends on: T-5.1
- Covers: REQ-QEX-1, REQ-QEX-2, REQ-QEX-7

**T-5.3** IndexScan (planner 选择)
- TDD: RED 写 planner 在有索引时选 IndexScan 测试 → GREEN → IMPROVE
- Depends on: T-5.2
- Covers: REQ-QEX-3

**T-5.4** Sort + Limit
- TDD: RED 5+ 场景 → GREEN → IMPROVE
- Depends on: T-5.3
- Covers: REQ-QEX-4, REQ-QEX-5

**T-5.5** INSERT / UPDATE / DELETE 执行 + 索引维护
- TDD: RED 8+ 场景 → GREEN → IMPROVE
- Depends on: T-5.4
- Covers: REQ-QEX-6

**T-5.6** Aggregate + GROUP BY
- File: `src/tinydb/executor/aggregate.py`
- TDD: RED 6+ 场景 (含 NULL 跳过) → GREEN → IMPROVE
- Depends on: T-5.5
- Covers: REQ-QEX-8, REQ-QEX-9

**Gate for Batch 5**: `pytest tests/executor --cov=src/tinydb/executor --cov-fail-under=85` 通过

---

### Batch 6 — Transactions & WAL

**T-6.1** Write lock
- File: `src/tinydb/tx/__init__.py`, `src/tinydb/tx/lock.py`
- TDD: RED 写嵌套锁/可重入测试 → GREEN → IMPROVE
- Depends on: T-2.4
- Covers: REQ-TRX-4 (单写者基础)

**T-6.2** WAL append
- File: `src/tinydb/tx/wal.py`
- TDD: RED 写 frame 编码/CRC 校验测试 (5+ 场景含损坏检测) → GREEN → IMPROVE
- Interfaces: `WALRecord(lsn, type, payload)`, `append`, `iter_from`
- Depends on: T-6.1
- Covers: REQ-TRX-6 (WAL 结构)

**T-6.3** Transaction manager
- File: `src/tinydb/tx/manager.py`
- TDD: RED 写 BEGIN/COMMIT/ROLLBACK + 嵌套拒绝测试 (8+ 场景) → GREEN → IMPROVE
- Depends on: T-6.2
- Covers: REQ-TRX-1, REQ-TRX-2, REQ-TRX-5

**T-6.4** Constraint enforcement on commit
- TDD: RED 4+ 场景 (UNIQUE/NOT NULL/类型 触发回滚) → GREEN → IMPROVE
- Depends on: T-6.3
- Covers: REQ-TRX-3, REQ-TYP-5 (约束集成)

**T-6.5** Isolation (READ COMMITTED 行为)
- TDD: RED 5+ 场景 → GREEN → IMPROVE
- Depends on: T-6.4
- Covers: REQ-TRX-4

**T-6.6** Recovery (REDO/UNDO)
- File: `src/tinydb/tx/recovery.py`
- TDD: RED 写"模拟崩溃"测试 (随机操作序列 → kill → 重启验证) (6+ 场景) → GREEN → IMPROVE
- Depends on: T-6.5
- Covers: REQ-TRX-5, REQ-TRX-6, REQ-TRX-7

**T-6.7** Checkpoint
- TDD: RED 3+ 场景 → GREEN → IMPROVE
- Depends on: T-6.6
- Covers: REQ-TRX-7 (checkpoint 部分)

**Gate for Batch 6**: `pytest tests/tx --cov=src/tinydb/tx --cov-fail-under=85` 通过；`tests/tx/test_recovery.py` 模糊测试 100 序列通过

---

### Batch 7 — Public API

**T-7.1** Database class
- File: `src/tinydb/api.py`
- TDD: RED 写 `open(path)` + `execute(sql) -> list[dict]` 集成测试 → GREEN → IMPROVE
- Interfaces: `Database.open`, `Database.execute`, `Database.close`, `Database.__enter__/__exit__`
- Depends on: T-5.6, T-6.7
- Covers: 公共 API

**T-7.2** End-to-end SQL flows
- File: `tests/integration/test_e2e.py`
- TDD: RED 写 20+ 真实 SQL 场景跨能力 (创建→插入→查询→索引→事务) → GREEN (随 Database 完善) → IMPROVE
- Depends on: T-7.1
- Covers: 跨能力集成

**Gate for Batch 7**: `pytest tests/integration --cov=src/tinydb --cov-fail-under=80` 通过

---

### Batch 8 — CLI

**T-8.1** Argparse
- File: `src/tinydb/cli/__init__.py`, `src/tinydb/cli/__main__.py`, `src/tinydb/cli/argparse_ext.py`
- TDD: RED 写 `tests/cli/test_argparse.py` 覆盖 `-h`, `--help`, `-c`, `--command`, 路径参数, 未知选项 → GREEN → IMPROVE
- Depends on: T-7.1
- Covers: REQ-CLI-1, REQ-CLI-7, REQ-CLI-8

**T-8.2** Result table formatter
- File: `src/tinydb/cli/format.py`
- TDD: RED 5+ 场景 (空结果/单行/多列/Unicode) → GREEN → IMPROVE
- Depends on: T-7.1
- Covers: REQ-CLI-3

**T-8.3** REPL core
- File: `src/tinydb/cli/repl.py`
- TDD: RED 5+ 场景 (单行/多行/退出) → GREEN → IMPROVE
- Depends on: T-8.2
- Covers: REQ-CLI-2, REQ-CLI-4, REQ-CLI-6

**T-8.4** Meta-commands (.exit, .quit, .help, .tables, .schema)
- TDD: RED 6+ 场景 → GREEN → IMPROVE
- Depends on: T-8.3
- Covers: REQ-CLI-5

**T-8.5** `__main__` + entry point
- TDD: RED subprocess 跑 `python -m tinydb` 端到端 → GREEN → IMPROVE
- Depends on: T-8.4
- Covers: REQ-CLI-1, REQ-CLI-7

**Gate for Batch 8**: `pytest tests/cli --cov=src/tinydb/cli --cov-fail-under=80` 通过

---

### Batch 9 — Polish & Release Prep

**T-9.1** README + examples
- File: `README.md`, `examples/demo.py`
- TDD: 不适用 (文档)，但 examples 必须跑通
- Depends on: T-8.5

**T-9.2** 全量覆盖率检查
- 运行 `pytest --cov=src/tinydb --cov-report=term-missing --cov-fail-under=80`
- 任何模块 < 80% 标记为返工

**T-9.3** `examples/demo.py` 端到端
- 创建/插入/查询/索引/事务/REPL 演示

**T-9.4** 范围审计
- 对照 `proposal.md > Out` 清单，确认未引入 JOIN/并发/外键/触发器等

**Gate for Batch 9**: 全量测试 + 覆盖率 ≥ 80% + `examples/demo.py` 跑通 + 范围审计通过 → 准备 DP-7 归档

---

## Requirement → Task 覆盖矩阵

| REQ | Tasks |
|---|---|
| REQ-SQL-1 | T-3.3 |
| REQ-SQL-2 | T-3.4b |
| REQ-SQL-3 | T-3.4a |
| REQ-SQL-4 | T-3.5 |
| REQ-SQL-5 | T-3.6 |
| REQ-SQL-6 | T-3.5 |
| REQ-SQL-7 | T-1.2, T-3.7 |
| REQ-SQL-8 | T-3.4a |
| REQ-STO-1 | T-2.1, T-2.4 |
| REQ-STO-2 | T-2.1, T-2.3 |
| REQ-STO-3 | T-2.2 |
| REQ-STO-4 | T-2.1 |
| REQ-STO-5 | T-2.3 |
| REQ-STO-6 | T-2.4 |
| REQ-STO-7 | T-2.3 |
| REQ-STO-8 | T-2.2, T-6.3 |
| REQ-QEX-1 | T-5.1, T-5.2 |
| REQ-QEX-2 | T-5.2 |
| REQ-QEX-3 | T-5.3 |
| REQ-QEX-4 | T-5.4 |
| REQ-QEX-5 | T-5.4 |
| REQ-QEX-6 | T-5.5 |
| REQ-QEX-7 | T-5.2 |
| REQ-QEX-8 | T-5.6 |
| REQ-QEX-9 | T-5.6 |
| REQ-IDX-1 | T-4.1, T-4.2, T-4.4 |
| REQ-IDX-2 | T-4.3 |
| REQ-IDX-3 | T-4.3 |
| REQ-IDX-4 | T-4.6, T-5.5 |
| REQ-IDX-5 | T-4.6 |
| REQ-IDX-6 | T-4.2, T-4.6 |
| REQ-IDX-7 | T-4.5 |
| REQ-TRX-1 | T-6.3 |
| REQ-TRX-2 | T-6.3 |
| REQ-TRX-3 | T-6.4 |
| REQ-TRX-4 | T-6.1, T-6.5 |
| REQ-TRX-5 | T-6.3, T-6.6 |
| REQ-TRX-6 | T-6.2 |
| REQ-TRX-7 | T-6.6, T-6.7 |
| REQ-TYP-1~5 | T-1.4, T-1.5 |
| REQ-TYP-6 | T-1.5 |
| REQ-TYP-7 | T-1.5, T-3.4a |
| REQ-TYP-8 | T-1.3 |
| REQ-TYP-9 | T-1.4, T-3.6 |
| REQ-TYP-10 | T-1.4, T-3.6 |
| REQ-TYP-11 | T-1.4, T-3.6 |
| REQ-TYP-12 | T-1.4, T-3.6 |
| REQ-TYP-13 | T-1.4, T-3.6 |
| REQ-TYP-14 | T-1.4, T-3.6 |
| REQ-CLI-1 | T-8.1, T-8.5 |
| REQ-CLI-2 | T-8.3 |
| REQ-CLI-3 | T-8.2 |
| REQ-CLI-4 | T-8.3 |
| REQ-CLI-5 | T-8.4 |
| REQ-CLI-6 | T-8.3 |
| REQ-CLI-7 | T-8.1, T-8.5 |
| REQ-CLI-8 | T-8.1 |

## Dependency Graph (Batch Level)

```
B1 (Foundation)        — types/codec/errors
  ↓
B2 (Storage)           — pager/buffer/heap/catalog
  ↓
B3 (SQL Parser)        — depends on B1.types
  ↓
B4 (B-tree Index)      — depends on B2.heap
  ↓
B5 (Query Executor)    — depends on B3.parser, B4.index, B2.catalog
  ↓
B6 (Transactions)      — depends on B2 (lock)
  ↓
B7 (Public API)        — depends on B5, B6
  ↓
B8 (CLI)               — depends on B7
  ↓
B9 (Polish)            — depends on B8
```

**Sequential by batch**, with batches 3 and 4 partly parallelizable (parser is independent of B-tree internals until planner integration in B5).
