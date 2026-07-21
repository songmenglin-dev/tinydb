# Tasks: tinydb-v0.2

## Worktree Strategy

| Worktree | Branch | 范围 | 批次 |
|---|---|---|---|
| 1 | `feature/v0.2-join` | JOIN 语法/解析/执行/优化 | B10-B13 |
| 2 | `feature/v0.2-concurrency` | RWLock/fcntl/快照/连接池 | B14-B17 |
| 3 | `feature/v0.2-cli` | prompt_toolkit/高亮/explain/历史 | B18-B20 |
| integrate | `feature/v0.2-integrate` | 合并 3 worktree + e2e + release | B21 |

合并顺序：1 + 2 + 3 → integrate（CI 全绿）→ master → tag `tinydb-v0.2.0`。

## File Structure

### Create

| 路径 | 责任 |
|---|---|
| `src/tinydb/executor/join.py` | NestedLoopJoin / IndexedNestedLoopJoin 算子 |
| `src/tinydb/concurrent/__init__.py` | concurrent 包对外导出 |
| `src/tinydb/concurrent/rwlock.py` | `RWLock(read=True/False)` 上下文管理器 |
| `src/tinydb/concurrent/fcntl_lock.py` | 跨进程 `fcntl.flock` 包装 + Windows 降级 |
| `src/tinydb/concurrent/deadlock.py` | 等待图 + DFS 周期检测 + 回滚策略 |
| `src/tinydb/tx/snapshot.py` | `Snapshot(lsn)` 与页可见性判断 |
| `src/tinydb/cli/highlight.py` | SQL → ANSI 着色字符串 |
| `src/tinydb/cli/explain.py` | `format_plan(plan) -> str` ASCII 树 |
| `src/tinydb/cli/history.py` | `FileHistory('~/.tinydb_history')` 持久化 |
| `src/tinydb/cli/format.py` | `format_table()` / `format_line_mode()` MySQL CLI 风格输出 |
| `tests/test_join.py` | REQ-JOIN-1..10 用例 |
| `tests/test_concurrent.py` | REQ-CONC-1..9 用例 |
| `tests/test_cli_enhance.py` | REQ-CLI-1..11 用例 |

### Modify

| 路径 | 改动 |
|---|---|
| `src/tinydb/sql/parser.py` | 新增 JOIN/ON/USING/别名解析（增 200 行） |
| `src/tinydb/sql/ast.py` | 新增 `JoinPlan` / `JoinKind` / `TableAlias` 节点 |
| `src/tinydb/executor/planner.py` | 拆分 `LogicalPlanner` + `PhysicalPlanner` |
| `src/tinydb/executor/operators.py` | 注册 JoinExecutor 到 `PHYSICAL_OPS` |
| `src/tinydb/tx/manager.py` | 事务启动/提交接入 RWLock + 死锁检测 |
| `src/tinydb/tx/lock.py` | 升级为 RWLock 感知 |
| `src/tinydb/storage/pager.py` | 页头加 `last_lsn: u32` 字段（4 字节） |
| `src/tinydb/storage/buffer_pool.py` | 缓存条目加 `last_lsn`，驱逐检查 |
| `src/tinydb/cli/repl.py` | 替换 `cmd.Cmd` 为 `prompt_toolkit.PromptSession` |
| `src/tinydb/cli/__main__.py` | 启动时检测 prompt_toolkit，缺失则降级 |
| `src/tinydb/api.py` | `Database.__init__` 新增 `isolation`/`pool_size` kwargs |
| `src/tinydb/__init__.py` | 导出 `IsolationLevel` 枚举 |
| `pyproject.toml` | 新增 `[project.optional-dependencies] cli = ["prompt_toolkit>=3.0.40"]` |
| `tests/test_v0_1_compat.py` (新) | v0.1 全部测试在 v0.2 下回归 |

## Interfaces

### Public API 增量（src/tinydb/api.py）

```python
class IsolationLevel(Enum):
    READ_COMMITTED = "READ COMMITTED"
    SERIALIZABLE = "SERIALIZABLE"

class Database:
    def __init__(
        self,
        path: str | Path,
        *,
        isolation: IsolationLevel = IsolationLevel.READ_COMMITTED,
        pool_size: int = 1,
    ) -> None: ...

    def acquire(self, timeout: float | None = None) -> Connection: ...
    def release(self, conn: Connection) -> None: ...

    @contextmanager
    def connection(self) -> Iterator[Connection]: ...

class Connection:
    def execute(self, sql: str) -> list[dict]: ...     # 不变
    def begin(self) -> Transaction: ...                 # 接入 RWLock
    def explain(self, sql: str) -> str: ...              # 新增
```

### 并发包接口（src/tinydb/concurrent/*）

```python
class RWLock:
    def __init__(self, *, prefer_writer: bool = True) -> None: ...
    def acquire_read(self, timeout: float | None = None) -> None: ...
    def release_read(self) -> None: ...
    def acquire_write(self, timeout: float | None = None) -> None: ...
    def release_write(self) -> None: ...
    @contextmanager
    def read(self): ...
    @contextmanager
    def write(self): ...

class ProcessLock:
    def __init__(self, fd: int, *, exclusive: bool = True) -> None: ...
    def __enter__(self) -> None: ...
    def __exit__(self, *args) -> None: ...

class DeadlockDetector:
    def __init__(self) -> None: ...
    def add_wait(self, waiter: int, holder: int) -> None: ...
    def remove(self, tx_id: int) -> None: ...
    def detect_cycle(self) -> int | None: ...   # 返回被回滚的 tx_id
```

### 执行器接口（src/tinydb/executor/join.py）

```python
class JoinExecutor(ABC):
    @abstractmethod
    def execute(self, left: Iterator[Row], right: RowSource, on_expr: Expr, kind: JoinKind) -> Iterator[Row]: ...

class NestedLoopJoin(JoinExecutor):
    def __init__(self) -> None: ...

class IndexedNestedLoopJoin(JoinExecutor):
    def __init__(self, index_manager: IndexManager) -> None: ...
```

### 规划器接口（src/tinydb/executor/planner.py）

```python
class LogicalPlanner:
    def plan(self, ast: AST) -> LogicalPlan: ...

class PhysicalPlanner:
    def __init__(self, catalog: Catalog, index_manager: IndexManager) -> None: ...
    def plan(self, logical: LogicalPlan) -> PhysicalPlan: ...
```

### CLI 接口（src/tinydb/cli/*）

```python
def highlight_sql(sql: str) -> list[(token, color)]: ...
def format_plan(plan: LogicalPlan | PhysicalPlan) -> str: ...
def load_history(path: Path) -> FileHistory: ...
def save_history(path: Path, history: FileHistory) -> None: ...
```

### 跨批次 Consumes/Produces

| Producer | Consumer | 类型契约 |
|---|---|---|
| B10 (SQL JOIN 解析) | B11 (LogicalPlan) | `JoinPlan(left: Plan, right: Plan, kind: JoinKind, on_expr: Expr, using_cols: list[str])` |
| B10 (SQL JOIN 解析) | B12 (Plan 渲染) | 同上 |
| B11 (LogicalPlanner) | B12 (PhysicalPlanner) | `LogicalPlan(steps: list[PlanNode])` |
| B14 (RWLock) | B15 (Transaction) | `RWLock`, `DeadlockDetector` |
| B14 (RWLock) | B16 (ProcessLock) | 无（解耦） |
| B15 (Transaction) | B17 (ConnectionPool) | `Transaction(lsn: int, isolation: IsolationLevel)` |
| B12 (PhysicalPlan) | B19 (EXPLAIN) | `PhysicalPlan(tree: PlanNode)` |
| B18 (PromptSession) | B19 (EXPLAIN) | REPL `session` 单例 |
| B18 (PromptSession) | B20 (history) | `FileHistory` 实例 |
| B13/B17/B20 (单能力完成) | B21 (e2e 集成) | 全套公共 API + 测试套件 |

---

## Batch 10 — JOIN SQL 解析（worktree 1）

### T-10.1: 新增 JoinPlan/JoinKind AST 节点
- **File**: `src/tinydb/sql/ast.py` (modify)
- **Depends on**: —
- **REQ covered**: REQ-JOIN-1/2
- **Interfaces (Consumes)**: —
- **Interfaces (Produces)**: `JoinKind(Enum) {INNER, LEFT}`, `JoinPlan(Plan)`
- **TDD Phases**:
  1. RED — 写 `tests/test_join.py::test_join_plan_dataclass`，断言 JoinPlan 字段存在
  2. GREEN — 在 ast.py 新增 JoinKind + JoinPlan dataclass
  3. REFACTOR — 加 `__repr__` 调试输出
  4. RUN — `pytest tests/test_join.py::test_join_plan_dataclass -v`
  5. COMMIT — `feat(sql): add JoinPlan AST node + JoinKind enum`

### T-10.2: parser 新增 FROM t1 JOIN t2 ON expr
- **File**: `src/tinydb/sql/parser.py` (modify)
- **Depends on**: T-10.1
- **REQ covered**: REQ-JOIN-1, REQ-JOIN-2, REQ-JOIN-5
- **Interfaces (Consumes)**: `JoinPlan`, `JoinKind`
- **Interfaces (Produces)**: Parser.parse() 返回 AST
- **TDD Phases**:
  1. RED — 写 6 个 test 用例（INNER/LEFT/嵌套/缺ON/5层嵌套边界/6层报错）
  2. GREEN — parser.py 新增 `parse_from_clause()` + `parse_join_clause()` 递归下降
  3. REFACTOR — 提取 `_parse_join_kind()`、`_parse_on_expr()`
  4. RUN — `pytest tests/test_join.py -k "parser" -v`
  5. COMMIT — `feat(sql): parse INNER/LEFT JOIN with ON clause (≤5 nested)`

### T-10.3: parser 新增 USING 子句
- **File**: `src/tinydb/sql/parser.py` (modify)
- **Depends on**: T-10.2
- **REQ covered**: REQ-JOIN-3
- **Interfaces (Consumes)**: —
- **Interfaces (Produces)**: `JoinPlan.using_cols: list[str]`
- **TDD Phases**:
  1. RED — `test_parse_join_using_single_col`、`test_parse_join_using_multi_col`
  2. GREEN — parser.py 新增 `_parse_using_clause()`，JoinPlan 字段 using_cols
  3. REFACTOR — 共享 USING/ON 公共路径
  4. RUN — `pytest tests/test_join.py -k "using" -v`
  5. COMMIT — `feat(sql): parse USING clause in JOIN`

### T-10.4: parser 新增表别名
- **File**: `src/tinydb/sql/parser.py` (modify)
- **Depends on**: T-10.2
- **REQ covered**: REQ-JOIN-4
- **Interfaces (Consumes)**: —
- **Interfaces (Produces)**: `Plan.alias: str | None`
- **TDD Phases**:
  1. RED — `test_parse_alias_basic`、`test_parse_alias_mixed_with_full_name_errors`
  2. GREEN — parser 接受 `FROM t alias`，ColumnRef 解析走别名表
  3. REFACTOR — ColumnRef 解析统一走 resolved_table 字段
  4. RUN — `pytest tests/test_join.py -k "alias" -v`
  5. COMMIT — `feat(sql): parse table aliases + alias-only column refs`

---

## Batch 11 — LogicalPlanner 与 JoinPlan 生成（worktree 1）

### T-11.1: LogicalPlanner 拆分
- **File**: `src/tinydb/executor/planner.py` (modify)
- **Depends on**: T-10.1
- **REQ covered**: D-1
- **Interfaces (Consumes)**: AST
- **Interfaces (Produces)**: `LogicalPlan(steps: list[PlanNode])`, `PlanNode` 抽象基类
- **TDD Phases**:
  1. RED — 写单表 SELECT 转 LogicalPlan 测试
  2. GREEN — 抽 `LogicalPlanner.plan(ast) -> LogicalPlan`
  3. REFACTOR — 移除原 `planner.py` 中的物理规划代码到 B-12
  4. RUN — `pytest tests/test_join.py::test_logical_plan_single_table tests/ -k "logical" -v`
  5. COMMIT — `refactor(executor): split LogicalPlanner from PhysicalPlanner`

### T-11.2: LogicalPlanner 生成 JoinPlan
- **File**: `src/tinydb/executor/planner.py` (modify)
- **Depends on**: T-11.1, T-10.2
- **REQ covered**: REQ-JOIN-1/2/3/5
- **Interfaces (Consumes)**: `JoinPlan` from T-10.1
- **Interfaces (Produces)**: `LogicalPlan` 含 JoinNode
- **TDD Phases**:
  1. RED — `test_logical_plan_two_table_join`、`test_logical_plan_three_table_join`、`test_logical_plan_join_using`
  2. GREEN — `_plan_join_clause()` 把 JoinPlan AST 转 LogicalPlan JoinNode
  3. REFACTOR — 统一 PlanNode 子类（Scan/Filter/Project/Join）
  4. RUN — `pytest tests/test_join.py -k "logical and join" -v`
  5. COMMIT — `feat(executor): LogicalPlanner emits JoinNode for FROM-JOIN`

### T-11.3: USING → ON 等价改写
- **File**: `src/tinydb/executor/planner.py` (modify)
- **Depends on**: T-11.2, T-10.3
- **REQ covered**: REQ-JOIN-3
- **Interfaces (Consumes)**: `JoinPlan.using_cols`
- **Interfaces (Produces)**: `JoinNode.on_expr = And(t1.col = t2.col, ...)`
- **TDD Phases**:
  1. RED — `test_logical_plan_using_rewritten_to_on`
  2. GREEN — `_plan_join_clause()` 中 USING 分支构造 And 链
  3. REFACTOR — 提取 `_build_using_equality_chain()`
  4. RUN — `pytest tests/test_join.py -k "using" -v`
  5. COMMIT — `feat(executor): rewrite USING clause as AND chain in LogicalPlan`

### T-11.4: LogicalPlanner 别名解析与歧义检测
- **File**: `src/tinydb/executor/planner.py` (modify)
- **Depends on**: T-11.2, T-10.4
- **REQ covered**: REQ-JOIN-4, REQ-JOIN-8
- **Interfaces (Consumes)**: —
- **Interfaces (Produces)**: `ColumnRef.resolved_table: str`
- **TDD Phases**:
  1. RED — `test_logical_plan_alias_resolution`、`test_logical_plan_ambiguous_column_errors`
  2. GREEN — LogicalPlanner 校验 ColumnRef 前缀是否为已声明别名
  3. REFACTOR — 抽出 `_resolve_column_ref()` 工具函数
  4. RUN — `pytest tests/test_join.py -k "alias or ambiguous" -v`
  5. COMMIT — `feat(executor): resolve table aliases + detect ambiguous columns`

---

## Batch 12 — PhysicalPlanner + JoinExecutor（worktree 1）

### T-12.1: PhysicalPlanner 拆分
- **File**: `src/tinydb/executor/planner.py` (modify)
- **Depends on**: T-11.1
- **REQ covered**: D-1
- **Interfaces (Consumes)**: `LogicalPlan`, `Catalog`, `IndexManager`
- **Interfaces (Produces)**: `PhysicalPlan(steps: list[PhysicalNode])`
- **TDD Phases**:
  1. RED — `test_physical_plan_single_table_scan`
  2. GREEN — `PhysicalPlanner.plan(logical, catalog, idx_mgr) -> PhysicalPlan`
  3. REFACTOR — 分离 catalog/index_manager 注入
  4. RUN — `pytest tests/test_join.py -k "physical" -v`
  5. COMMIT — `refactor(executor): introduce PhysicalPlanner with catalog+index injection`

### T-12.2: NestedLoopJoin 实现
- **File**: `src/tinydb/executor/join.py` (create)
- **Depends on**: T-12.1
- **REQ covered**: REQ-JOIN-6
- **Interfaces (Consumes)**: `Row`, `RowSource`, `Expr`, `JoinKind`
- **Interfaces (Produces)**: `Iterator[Row]`
- **TDD Phases**:
  1. RED — `test_nlj_inner_join`、`test_nlj_left_join_preserves_left`、`test_nlj_left_join_nulls_right`
  2. GREEN — `NestedLoopJoin.execute()` 实现左驱动循环 + LEFT 填充 NULL
  3. REFACTOR — 抽出 `_eval_on_expr(row_left, row_right)`
  4. RUN — `pytest tests/test_join.py -k "nlj" -v`
  5. COMMIT — `feat(executor): NestedLoopJoin with INNER + LEFT support`

### T-12.3: IndexedNestedLoopJoin 实现
- **File**: `src/tinydb/executor/join.py` (modify, append class)
- **Depends on**: T-12.2, T-12.1
- **REQ covered**: REQ-JOIN-7
- **Interfaces (Consumes)**: `IndexManager.seek()`
- **Interfaces (Produces)**: `Iterator[Row]` via `IndexManager.seek()`
- **TDD Phases**:
  1. RED — `test_inlj_uses_index`、`test_inlj_falls_back_when_no_index`
  2. GREEN — `IndexedNestedLoopJoin.execute()` 调 IndexManager.seek
  3. REFACTOR — 抽象公共接口到 `JoinExecutor` 基类
  4. RUN — `pytest tests/test_join.py -k "inlj" -v`
  5. COMMIT — `feat(executor): IndexedNestedLoopJoin reuses B-tree index`

### T-12.4: PhysicalPlanner 选择算子（NLJ vs INLJ）
- **File**: `src/tinydb/executor/planner.py` (modify)
- **Depends on**: T-12.2, T-12.3
- **REQ covered**: REQ-JOIN-7
- **Interfaces (Consumes)**: `IndexManager.has_index(table, col)`
- **Interfaces (Produces)**: `PhysicalPlan` 含 NLJ 或 INLJ
- **TDD Phases**:
  1. RED — `test_planner_picks_inlj_when_index_available`、`test_planner_picks_nlj_otherwise`
  2. GREEN — `_plan_join_node()` 检查索引可用性
  3. REFACTOR — 抽出 `_choose_join_op()` 启发式
  4. RUN — `pytest tests/test_join.py -k "planner_picks" -v`
  5. COMMIT — `feat(executor): planner selects NLJ vs INLJ based on index availability`

### T-12.5: 投影去重 + JOIN+WHERE 组合
- **File**: `src/tinydb/executor/planner.py` (modify), `src/tinydb/executor/operators.py` (modify)
- **Depends on**: T-12.4
- **REQ covered**: REQ-JOIN-8, REQ-JOIN-9
- **Interfaces (Consumes)**: —
- **Interfaces (Produces)**: `Project` 节点去重 USING 列
- **TDD Phases**:
  1. RED — `test_project_dedup_using_cols`、`test_join_then_where_filter`、`test_ambiguous_column_in_select_errors`
  2. GREEN — Project 节点去除 USING 重复列；planner 在 JOIN 后挂 Filter
  3. REFACTOR — 抽出 `_dedup_columns()`
  4. RUN — `pytest tests/test_join.py -k "project or where" -v`
  5. COMMIT — `feat(executor): dedup USING cols + apply WHERE after JOIN`

### T-12.6: Database.execute 接入新算子
- **File**: `src/tinydb/api.py` (modify)
- **Depends on**: T-12.5
- **REQ covered**: REQ-JOIN-10
- **Interfaces (Consumes)**: `PhysicalPlan`
- **Interfaces (Produces)**: `list[dict]` (与 v0.1 一致)
- **TDD Phases**:
  1. RED — 跑 v0.1 现有 826 测试，确保不破坏
  2. GREEN — api.py 调 `PhysicalPlanner` + 新算子
  3. REFACTOR — 错误处理统一为 v0.1 `ExecuteError`
  4. RUN — `pytest tests/ -v`
  5. COMMIT — `feat(api): Database.execute dispatches through new PhysicalPlanner`

---

## Batch 13 — JOIN 集成测试与回归（worktree 1）

### T-13.1: 端到端 JOIN 测试套件
- **File**: `tests/test_join.py` (extend)
- **Depends on**: T-12.6
- **REQ covered**: REQ-JOIN-1..10 全覆盖
- **TDD Phases**:
  1. RED — 写 15+ 端到端用例（users×orders、3 表、USING、空集、左连接无匹配）
  2. GREEN — 全部通过
  3. REFACTOR — 抽 fixture `make_join_db(users, orders)`
  4. RUN — `pytest tests/test_join.py -v`
  5. COMMIT — `test(join): end-to-end JOIN suite covering all REQ-JOIN-*`

### T-13.2: v0.1 兼容性回归
- **File**: `tests/test_v0_1_compat.py` (create)
- **Depends on**: T-12.6
- **REQ covered**: REQ-JOIN-10
- **TDD Phases**:
  1. RED — 跑 v0.1 测试在 v0.2 下应 100% 通过
  2. GREEN — 如有失败，逐个修
  3. REFACTOR — 把 v0.1 测试 import 到 test_v0_1_compat 作为子集
  4. RUN — `pytest tests/ -v`
  5. COMMIT — `test(compat): v0.1 826 tests pass under v0.2 code`

---

## Batch 14 — RWLock + DeadlockDetector（worktree 2）

### T-14.1: RWLock 读写锁
- **File**: `src/tinydb/concurrent/rwlock.py` (create)
- **Depends on**: —
- **REQ covered**: REQ-CONC-1
- **Interfaces (Produces)**: `RWLock`, `acquire_read/write`, `release_read/write`, `@contextmanager read/write`
- **TDD Phases**:
  1. RED — `test_rwlock_multiple_readers`、`test_rwlock_writer_exclusive`、`test_rwlock_write_blocks_read`
  2. GREEN — 基于 `threading.Condition` 实现
  3. REFACTOR — 抽 `_wait_readers_drained()` 防写饥饿
  4. RUN — `pytest tests/test_concurrent.py -k "rwlock" -v`
  5. COMMIT — `feat(concurrent): RWLock with reader/writer semantics`

### T-14.2: DeadlockDetector 等待图
- **File**: `src/tinydb/concurrent/deadlock.py` (create)
- **Depends on**: T-14.1
- **REQ covered**: REQ-CONC-7
- **Interfaces (Produces)**: `DeadlockDetector`, `add_wait`, `remove`, `detect_cycle`
- **TDD Phases**:
  1. RED — `test_deadlock_no_cycle`、`test_deadlock_two_tx_cycle`、`test_deadlock_three_tx_cycle`
  2. GREEN — 维护 `waits_for: dict[int, int]` + DFS
  3. REFACTOR — 抽出 `_has_cycle_from(node, visited, stack)`
  4. RUN — `pytest tests/test_concurrent.py -k "deadlock" -v`
  5. COMMIT — `feat(concurrent): DeadlockDetector with cycle detection`

### T-14.3: ProcessLock 跨进程文件锁
- **File**: `src/tinydb/concurrent/fcntl_lock.py` (create)
- **Depends on**: —
- **REQ covered**: REQ-CONC-2
- **Interfaces (Produces)**: `ProcessLock(fd, exclusive=True)`, 上下文管理器
- **TDD Phases**:
  1. RED — `test_process_lock_basic`（同进程）、`test_process_lock_blocks_other_process`（跨进程 spawn）
  2. GREEN — Linux 用 `fcntl.flock`，Windows 降级到 `msvcrt.locking` 或抛 PlatformNotSupportedError
  3. REFACTOR — 抽 `_platform_lock(fd, exclusive)`
  4. RUN — `pytest tests/test_concurrent.py -k "process_lock" -v`
  5. COMMIT — `feat(concurrent): ProcessLock with fcntl + msvcrt fallback`

---

## Batch 15 — Transaction 接入 RWLock（worktree 2）

### T-15.1: tx/manager.py 集成 RWLock
- **File**: `src/tinydb/tx/manager.py` (modify)
- **Depends on**: T-14.1, T-14.2
- **REQ covered**: REQ-CONC-1, REQ-CONC-7
- **Interfaces (Consumes)**: `RWLock`, `DeadlockDetector`
- **Interfaces (Produces)**: `Transaction` 类持有 RWLock 引用
- **TDD Phases**:
  1. RED — `test_tx_concurrent_readers`、`test_tx_writer_excludes_others`、`test_tx_deadlock_raises`
  2. GREEN — `Transaction.begin()` 调 `rwlock.acquire_read/write()`；检测到死锁抛 `DeadlockError`
  3. REFACTOR — 把锁管理从 `lock.py` 迁入 manager
  4. RUN — `pytest tests/test_concurrent.py -k "manager" -v`
  5. COMMIT — `feat(tx): Transaction lifecycle uses RWLock + deadlock detection`

### T-15.2: tx/lock.py 升级
- **File**: `src/tinydb/tx/lock.py` (modify)
- **Depends on**: T-15.1
- **REQ covered**: REQ-CONC-1
- **TDD Phases**:
  1. RED — 验证 v0.1 `WriteLock` 接口仍可用
  2. GREEN — `WriteLock` 改为薄包装 `RWLock.write()`
  3. REFACTOR — 保留 v0.1 公共 API
  4. RUN — `pytest tests/ -v`（确认无回归）
  5. COMMIT — `refactor(tx): WriteLock wraps RWLock.write`

### T-15.3: Page header 加 last_lsn
- **File**: `src/tinydb/storage/pager.py` (modify)
- **Depends on**: —
- **REQ covered**: REQ-CONC-5
- **TDD Phases**:
  1. RED — `test_page_header_has_last_lsn`
  2. GREEN — page 头加 `last_lsn: u32`（4 字节），向后兼容 v0.1（默认 0）
  3. REFACTOR — 文件 magic 不变；新字段 default 0
  4. RUN — `pytest tests/test_storage.py -v`
  5. COMMIT — `feat(storage): page header carries last_lsn for snapshot visibility`

---

## Batch 16 — 读快照隔离（worktree 2）

### T-16.1: Snapshot 类
- **File**: `src/tinydb/tx/snapshot.py` (create)
- **Depends on**: T-15.3
- **REQ covered**: REQ-CONC-3
- **Interfaces (Produces)**: `Snapshot(lsn: int)`, `is_visible(page_lsn: int) -> bool`
- **TDD Phases**:
  1. RED — `test_snapshot_lsn_equal_visible`、`test_snapshot_lsn_greater_invisible`
  2. GREEN — `Snapshot.is_visible(page_lsn) = page_lsn <= self.lsn`
  3. REFACTOR — 加 docstring 解释可见性规则
  4. RUN — `pytest tests/test_concurrent.py -k "snapshot" -v`
  5. COMMIT — `feat(tx): Snapshot class for READ COMMITTED visibility`

### T-16.2: BufferPool 接入 LSN 失效
- **File**: `src/tinydb/storage/buffer_pool.py` (modify)
- **Depends on**: T-15.3, T-16.1
- **REQ covered**: REQ-CONC-5
- **Interfaces (Consumes)**: `Snapshot`
- **Interfaces (Produces)**: `BufferPool.fetch(page_id, snapshot: Snapshot | None)`
- **TDD Phases**:
  1. RED — `test_buffer_pool_invalidates_external_write`、`test_buffer_pool_keeps_cache_when_unmodified`
  2. GREEN — BufferPool 记录每页 last_lsn；fetch 时若外部 mtime 变化丢弃
  3. REFACTOR — 抽 `_is_stale(page_id)`
  4. RUN — `pytest tests/test_storage.py -k "buffer_pool" -v`
  5. COMMIT — `feat(storage): BufferPool invalidates pages on external LSN change`

### T-16.3: Transaction.begin 记录 Snapshot
- **File**: `src/tinydb/tx/manager.py` (modify)
- **Depends on**: T-16.1, T-16.2
- **REQ covered**: REQ-CONC-3, REQ-CONC-4
- **TDD Phases**:
  1. RED — `test_tx_read_sees_snapshot`、`test_tx_write_conflict_rolls_back`
  2. GREEN — `begin(isolation)` 时记录当前 WAL 段号作为 Snapshot
  3. REFACTOR — 抽出 `_acquire_snapshot()`
  4. RUN — `pytest tests/test_concurrent.py -k "tx_snapshot" -v`
  5. COMMIT — `feat(tx): Transaction captures snapshot on begin()`

---

## Batch 17 — 连接池 + 跨进程锁（worktree 2）

### T-17.1: Database.acquire/release + connection()
- **File**: `src/tinydb/api.py` (modify)
- **Depends on**: T-15.1
- **REQ covered**: REQ-CONC-6
- **Interfaces (Produces)**: `Database.acquire`, `Database.release`, `Database.connection()`
- **TDD Phases**:
  1. RED — `test_database_pool_size_4`、`test_database_context_manager_auto_release`、`test_database_default_pool_1`
  2. GREEN — api.py 用 `queue.Queue` 实现连接池
  3. REFACTOR — 抽 `_ConnectionPool` 内部类
  4. RUN — `pytest tests/test_concurrent.py -k "pool" -v`
  5. COMMIT — `feat(api): Database connection pool with acquire/release/connection()`

### T-17.2: ProcessLock 集成 WAL
- **File**: `src/tinydb/tx/wal.py` (modify)
- **Depends on**: T-14.3
- **REQ covered**: REQ-CONC-2
- **TDD Phases**:
  1. RED — `test_wal_acquires_process_lock`（验证 fcntl 调用）
  2. GREEN — WAL.append() 包 `with ProcessLock(wal_fd, exclusive=True)`
  3. REFACTOR — 锁粒度：仅追加期间持有
  4. RUN — `pytest tests/test_concurrent.py -k "wal_lock" -v`
  5. COMMIT — `feat(tx): WAL append acquires cross-process exclusive lock`

### T-17.3: 多线程 + 多进程并发集成测试
- **File**: `tests/test_concurrent.py` (extend)
- **Depends on**: T-17.1, T-17.2
- **REQ covered**: REQ-CONC-8
- **TDD Phases**:
  1. RED — 写 32 线程 INSERT/SELECT 压力测试 + 4 进程 1W/3R 测试
  2. GREEN — 测试通过
  3. REFACTOR — 抽 `_spawn_workers(n, fn)`
  4. RUN — `pytest tests/test_concurrent.py -k "stress" -v`
  5. COMMIT — `test(concurrent): 32-thread + 4-process integration suite`

### T-17.4: v0.1 并发兼容性回归
- **File**: `tests/test_v0_1_compat.py` (extend)
- **Depends on**: T-17.3
- **REQ covered**: REQ-CONC-9
- **TDD Phases**:
  1. RED — 跑 v0.1 测试，确保单线程性能不退化 > 5%
  2. GREEN — 修复瓶颈（如有）
  3. REFACTOR — 加性能断言 `assert elapsed < v0.1_baseline * 1.05`
  4. RUN — `pytest tests/ -v`
  5. COMMIT — `test(compat): v0.1 single-thread performance ≤ 5% regression`

---

## Batch 18 — CLI prompt_toolkit 迁移（worktree 3）

### T-18.1: 检测 prompt_toolkit 可用性
- **File**: `src/tinydb/cli/__main__.py` (modify)
- **Depends on**: —
- **REQ covered**: REQ-CLI-9
- **TDD Phases**:
  1. RED — `test_cli_detects_prompt_toolkit_available`、`test_cli_detects_prompt_toolkit_missing`
  2. GREEN — `cli/repl.py` 用 `importlib.util.find_spec('prompt_toolkit')` 设模块级常量 `_HAS_PT`
  3. REFACTOR — 抽 `_prompt_toolkit_available() -> bool`
  4. RUN — `pytest tests/test_cli_enhance.py -k "detect" -v`
  5. COMMIT — `feat(cli): detect prompt_toolkit availability at startup`

### T-18.2: PromptSession 多行编辑
- **File**: `src/tinydb/cli/repl.py` (modify)
- **Depends on**: T-18.1
- **REQ covered**: REQ-CLI-1, REQ-CLI-2, REQ-CLI-3, REQ-CLI-4
- **Interfaces (Consumes)**: `FileHistory`
- **Interfaces (Produces)**: `REPL.run()` 主循环
- **TDD Phases**:
  1. RED — 写多行续行、未闭合引号续行、上下方向键、Ctrl-A/E 测试
  2. GREEN — 用 `PromptSession(multiline=True, ...)` 实现
  3. REFACTOR — 抽 `_is_continuation(line: str) -> bool`（检测 `\` 结尾或未闭合引号）
  4. RUN — `pytest tests/test_cli_enhance.py -k "multiline or history" -v`
  5. COMMIT — `feat(cli): PromptSession-based REPL with multi-line + history`

### T-18.3: 缺失 prompt_toolkit 时降级到 cmd
- **File**: `src/tinydb/cli/repl.py` (modify)
- **Depends on**: T-18.2
- **REQ covered**: REQ-CLI-9
- **TDD Phases**:
  1. RED — `test_cli_falls_back_to_cmd`（mock 缺失 prompt_toolkit）
  2. GREEN — `_HAS_PT=False` 时复用 v0.1 的 `cmd.Cmd` 子类
  3. REFACTOR — 抽象 `BaseREPL.run()` 接口，两个子类实现
  4. RUN — `pytest tests/test_cli_enhance.py -k "fallback" -v`
  5. COMMIT — `feat(cli): graceful fallback to cmd.Cmd when prompt_toolkit absent`

---

## Batch 19 — 语法高亮 + EXPLAIN（worktree 3）

### T-19.1: SQL tokenizer 复用
- **File**: `src/tinydb/cli/highlight.py` (create)
- **Depends on**: T-18.2
- **REQ covered**: REQ-CLI-5
- **TDD Phases**:
  1. RED — `test_highlight_keywords`、`test_highlight_strings`、`test_highlight_numbers`、`test_highlight_comments`
  2. GREEN — 复用 `tinydb/sql/tokenizer.py` + 颜色映射
  3. REFACTOR — 颜色映射抽 `_COLOR_TABLE`
  4. RUN — `pytest tests/test_cli_enhance.py -k "highlight" -v`
  5. COMMIT — `feat(cli): SQL syntax highlighting with ANSI colors`

### T-19.2: 集成高亮到 PromptSession
- **File**: `src/tinydb/cli/repl.py` (modify)
- **Depends on**: T-19.1
- **REQ covered**: REQ-CLI-5
- **TDD Phases**:
  1. RED — `test_repl_uses_highlighter`
  2. GREEN — `PromptSession` 接受 `lexer=` 参数
  3. REFACTOR — 把 highlight 函数适配为 `Lexer` 接口
  4. RUN — `pytest tests/test_cli_enhance.py -k "lexer" -v`
  5. COMMIT — `feat(cli): wire syntax highlighter into PromptSession`

### T-19.3: format_plan ASCII 树
- **File**: `src/tinydb/cli/explain.py` (create)
- **Depends on**: T-12.1
- **REQ covered**: REQ-CLI-6
- **Interfaces (Consumes)**: `LogicalPlan`, `PhysicalPlan`
- **Interfaces (Produces)**: `str`
- **TDD Phases**:
  1. RED — `test_format_logical_plan`、`test_format_physical_plan`、`test_format_join_plan`
  2. GREEN — 递归 `├──`/`└──`/`│` 树
  3. REFACTOR — 抽 `_render_node(node, prefix, is_last)`
  4. RUN — `pytest tests/test_cli_enhance.py -k "format_plan" -v`
  5. COMMIT — `feat(cli): ASCII tree formatter for LogicalPlan + PhysicalPlan`

### T-19.4: Connection.explain + .explain 元命令
- **File**: `src/tinydb/api.py` (modify), `src/tinydb/cli/repl.py` (modify)
- **Depends on**: T-19.3
- **REQ covered**: REQ-CLI-6
- **TDD Phases**:
  1. RED — `test_api_explain_returns_string`、`test_cli_dot_explain_runs`
  2. GREEN — `Connection.explain(sql)` 调 planner 后调 format_plan
  3. REFACTOR — `.explain` 元命令路由
  4. RUN — `pytest tests/test_cli_enhance.py -k "explain" -v`
  5. COMMIT — `feat(cli): .explain meta-command + Connection.explain()`

---

## Batch 20 — 元命令 + 历史持久化（worktree 3）

### T-20.1: FileHistory 持久化
- **File**: `src/tinydb/cli/history.py` (create)
- **Depends on**: T-18.2
- **REQ covered**: REQ-CLI-8
- **Interfaces (Produces)**: `FileHistory(path: Path)` 包装 prompt_toolkit FileHistory
- **TDD Phases**:
  1. RED — `test_history_persists_on_quit`、`test_history_loads_on_start`、`test_history_unwritable_warns`
  2. GREEN — 用 `prompt_toolkit.history.FileHistory`
  3. REFACTOR — 异常处理：写入失败时 warn 但不抛错
  4. RUN — `pytest tests/test_cli_enhance.py -k "history_persist" -v`
  5. COMMIT — `feat(cli): FileHistory persistence at ~/.tinydb_history`

### T-20.2: .tables / .schema 元命令
- **File**: `src/tinydb/cli/repl.py` (modify), `src/tinydb/api.py` (modify)
- **Depends on**: T-19.4
- **REQ covered**: REQ-CLI-7
- **Interfaces (Produces)**: `Database.list_tables()`, `Database.get_schema(table) -> str`
- **TDD Phases**:
  1. RED — `test_cli_dot_tables`、`test_cli_dot_schema`、`test_cli_dot_schema_missing_table`
  2. GREEN — REPL do_* 方法 + api.Database 方法
  3. REFACTOR — 共用 `_run_meta_command()`
  4. RUN — `pytest tests/test_cli_enhance.py -k "tables or schema" -v`
  5. COMMIT — `feat(cli): .tables and .schema meta-commands`

### T-20.3: .history 元命令
- **File**: `src/tinydb/cli/repl.py` (modify)
- **Depends on**: T-20.1
- **REQ covered**: REQ-CLI-8
- **TDD Phases**:
  1. RED — `test_cli_dot_history_shows_last_n`
  2. GREEN — `do_history` 遍历 history 入参 + 编号
  3. REFACTOR — 抽 `_render_history(n)`
  4. RUN — `pytest tests/test_cli_enhance.py -k "dot_history" -v`
  5. COMMIT — `feat(cli): .history meta-command`

### T-20.4: .quit / Ctrl-C 中断
- **File**: `src/tinydb/cli/repl.py` (modify)
- **Depends on**: T-18.2
- **REQ covered**: REQ-CLI-10
- **TDD Phases**:
  1. RED — `test_cli_quit_exits`、`test_cli_ctrl_c_clears_buffer`、`test_cli_eof_exits`
  2. GREEN — `do_quit` + KeyboardInterrupt 处理 + EOF 处理
  3. REFACTOR — 抽 `_handle_signal()`
  4. RUN — `pytest tests/test_cli_enhance.py -k "quit or interrupt" -v`
  5. COMMIT — `feat(cli): .quit + Ctrl-C + EOF clean exit`

### T-20.5: v0.1 CLI 兼容性回归
- **File**: `tests/test_v0_1_compat.py` (extend)
- **Depends on**: T-20.4
- **REQ covered**: REQ-CLI-11
- **TDD Phases**:
  1. RED — 跑 v0.1 CLI 727 测试在 v0.2 下通过
  2. GREEN — 修回归
  3. REFACTOR — 加 CI 矩阵：分别跑 `prompt_toolkit` 安装/缺失两种环境
  4. RUN — `pytest tests/test_cli.py tests/test_cli_enhance.py -v`
  5. COMMIT — `test(compat): v0.1 727 CLI tests pass under v0.2 (both PT-present and PT-absent)`

### T-20.6: ASCII 表格渲染器
- **File**: `src/tinydb/cli/format.py` (create)
- **Depends on**: T-19.4
- **REQ covered**: REQ-CLI-12, REQ-CLI-14
- **Interfaces (Consumes)**: `list[dict]`, `list[str]` (列名)
- **Interfaces (Produces)**: `str` (带 `\n` 的多行表格)
- **TDD Phases**:
  1. RED — `test_format_table_basic`、`test_format_table_empty`、`test_format_table_alignment_numeric_right`、`test_format_table_alignment_string_left`、`test_format_table_blob_hex`、`test_format_table_null_literal`
  2. GREEN — `format_table(rows, columns, column_types)` 用 `str.ljust/rjust` 拼字符串
  3. REFACTOR — 抽 `_cell_width(value)` 与 `_align_for(typ)`
  4. RUN — `pytest tests/test_cli_enhance.py -k "format_table" -v`
  5. COMMIT — `feat(cli): ASCII table renderer with type-aware alignment`

### T-20.7: 行数与计时包装
- **File**: `src/tinydb/cli/repl.py` (modify), `src/tinydb/cli/format.py` (modify)
- **Depends on**: T-20.6
- **REQ covered**: REQ-CLI-13
- **TDD Phases**:
  1. RED — `test_repl_shows_row_count_and_timing`、`test_repl_shows_empty_set`、`test_repl_no_timing_for_ddl`、`test_format_elapsed_seconds`
  2. GREEN — REPL `do_select` 用 `time.perf_counter()` 包裹 `execute()`，输出 `N rows in set (X.XXs)`
  3. REFACTOR — 抽 `_render_timing(n_rows, elapsed) -> str`
  4. RUN — `pytest tests/test_cli_enhance.py -k "timing" -v`
  5. COMMIT — `feat(cli): SELECT timing + row count footer (MySQL CLI style)`

### T-20.8: 元命令表格化
- **File**: `src/tinydb/cli/repl.py` (modify)
- **Depends on**: T-20.6, T-20.2
- **REQ covered**: REQ-CLI-15
- **TDD Phases**:
  1. RED — `test_dot_tables_uses_table_format`、`test_dot_schema_uses_table_format`、`test_explain_table_flag`
  2. GREEN — `.tables`/`.schema`/`EXPLAIN --table` 调 `format_table()`；保留 ANSI 颜色
  3. REFACTOR — 共用 `_render_meta_table(rows, columns)`
  4. RUN — `pytest tests/test_cli_enhance.py -k "meta_table" -v`
  5. COMMIT — `feat(cli): .tables/.schema/.explain use ASCII table format`

### T-20.9: .mode 切换 table/line
- **File**: `src/tinydb/cli/repl.py` (modify)
- **Depends on**: T-20.6
- **REQ covered**: REQ-CLI-16
- **TDD Phases**:
  1. RED — `test_mode_line_renders_kv`、`test_mode_table_renders_table`、`test_mode_default_is_table`
  2. GREEN — REPL 维护 `_mode` 字段；`.mode line`/`.mode table` 切换；`format_line_mode()` 实现
  3. REFACTOR — 抽 `_render_result(rows, mode)`
  4. RUN — `pytest tests/test_cli_enhance.py -k "mode" -v`
  5. COMMIT — `feat(cli): .mode toggle between table and line output`

### T-20.10: 表格化与高亮共存测试
- **File**: `tests/test_cli_enhance.py` (extend)
- **Depends on**: T-20.6, T-20.7, T-20.8, T-20.9, T-19.2
- **REQ covered**: REQ-CLI-12..16 + REQ-CLI-5 共存
- **TDD Phases**:
  1. RED — 写 6+ 集成用例（彩色表格、宽字符表格、NULL/BLOB/大数混合）
  2. GREEN — 全部通过
  3. REFACTOR — 抽 fixture `make_colored_rows()`
  4. RUN — `pytest tests/test_cli_enhance.py -v`
  5. COMMIT — `test(cli): integration suite for table + highlight + timing`

---

## Batch 21 — 集成 + Release（worktree integrate）

### T-21.1: 合并 3 worktree
- **File**: `git merge feature/v0.2-join feature/v0.2-concurrency feature/v0.2-cli`
- **Depends on**: B13 + B17 + B20
- **TDD Phases**:
  1. RED — N/A
  2. GREEN — 解决合并冲突（接口边界对齐即可）
  3. REFACTOR — 重新跑全套 pytest
  4. RUN — `pytest tests/ -v`
  5. COMMIT — `merge: integrate JOIN + concurrency + CLI into feature/v0.2-integrate`

### T-21.2: 端到端集成测试
- **File**: `tests/test_e2e_v0_2.py` (create)
- **Depends on**: T-21.1
- **REQ covered**: 全能力端到端
- **TDD Phases**:
  1. RED — 写 10 个用户故事：建表→JOIN 查询→并发写→多线程读→CLI 执行计划
  2. GREEN — 全部通过
  3. REFACTOR — 用 fixture 共享 db 实例
  4. RUN — `pytest tests/test_e2e_v0_2.py -v`
  5. COMMIT — `test(e2e): v0.2 end-to-end stories covering all capabilities`

### T-21.3: pyproject.toml 更新与文档
- **File**: `pyproject.toml` (modify), `README.md` (modify), `docs/CLI_USAGE.md` (create)
- **Depends on**: T-21.2
- **TDD Phases**:
  1. RED — N/A（无测试）
  2. GREEN — pyproject.toml 加 optional dep；README 加 JOIN/并发小节；新文档
  3. REFACTOR — 校对链接
  4. RUN — `pip install -e ".[cli]" && pytest -v`
  5. COMMIT — `docs: v0.2 README + CLI_USAGE.md + pyproject optional deps`

### T-21.4: DP-6 验证 + DP-7 release
- **File**: 同 B21.3
- **Depends on**: T-21.3
- **TDD Phases**:
  1. RED — N/A
  2. GREEN — 验证 4 项 acceptance: ① pytest 1226+ PASS, ② coverage ≥ 80%, ③ 范围审计无新 Out 越界, ④ 0 新硬依赖（除可选 prompt_toolkit）
  3. REFACTOR — 生成 release notes
  4. RUN — `pytest tests/ --cov=src/tinydb --cov-fail-under=80`
  5. COMMIT — `chore(release): close spec-superflow DP-7 release-archivist`

---

## Requirements Mapping

| REQ | T-Covered |
|---|---|
| REQ-JOIN-1 | T-10.2 |
| REQ-JOIN-2 | T-10.2 |
| REQ-JOIN-3 | T-10.3, T-11.3 |
| REQ-JOIN-4 | T-10.4, T-11.4 |
| REQ-JOIN-5 | T-10.2 |
| REQ-JOIN-6 | T-12.2 |
| REQ-JOIN-7 | T-12.3, T-12.4 |
| REQ-JOIN-8 | T-11.4, T-12.5 |
| REQ-JOIN-9 | T-12.5 |
| REQ-JOIN-10 | T-12.6, T-13.2 |
| REQ-CONC-1 | T-14.1, T-15.1, T-15.2 |
| REQ-CONC-2 | T-14.3, T-17.2 |
| REQ-CONC-3 | T-16.1, T-16.3 |
| REQ-CONC-4 | T-16.3, T-17.1 |
| REQ-CONC-5 | T-15.3, T-16.2 |
| REQ-CONC-6 | T-17.1 |
| REQ-CONC-7 | T-14.2, T-15.1 |
| REQ-CONC-8 | T-17.3 |
| REQ-CONC-9 | T-17.4 |
| REQ-CLI-1 | T-18.2 |
| REQ-CLI-2 | T-18.2 |
| REQ-CLI-3 | T-18.2 |
| REQ-CLI-4 | T-18.2 |
| REQ-CLI-5 | T-19.1, T-19.2 |
| REQ-CLI-6 | T-19.3, T-19.4 |
| REQ-CLI-7 | T-20.2 |
| REQ-CLI-8 | T-20.1, T-20.3 |
| REQ-CLI-9 | T-18.1, T-18.3 |
| REQ-CLI-10 | T-20.4 |
| REQ-CLI-11 | T-20.5 |
| REQ-CLI-12 | T-20.6, T-20.10 |
| REQ-CLI-13 | T-20.7, T-20.10 |
| REQ-CLI-14 | T-20.6, T-20.10 |
| REQ-CLI-15 | T-20.8, T-20.10 |
| REQ-CLI-16 | T-20.9, T-20.10 |

全部 35 条 REQ 已被 T- 覆盖，每条 ≥1 个 T-task。