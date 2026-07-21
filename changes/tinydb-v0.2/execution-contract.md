# 执行合同

> 本合同由 `proposal.md` + `specs/` + `design.md` + `tasks.md` 派生。
> 任何与源工件冲突的内容以源工件为准；发现冲突时按 Escalation Rules 处理。
> DP-3 是 hard gate，未经用户显式批准不得开始实施。

## Intent Lock

- **变更名称**：`tinydb-v0.2`
- **要解决的问题**：tinydb v0.1 显式排除多表 JOIN、并发控制（多线程/多进程）、CLI 仅基础 REPL；需要 v0.2 在不破坏 v0.1 接口兼容的前提下补齐这三条能力
- **范围内**：
  - SQL：扩展语法 `SELECT ... FROM t1 [INNER|LEFT] JOIN t2 ON <expr>`，可多层嵌套（最多 5 层）
  - SQL：USING 子句（`JOIN t USING (col)`）、表别名（`FROM users u, orders o`）
  - 执行器：NestedLoopJoin 与 IndexedNestedLoopJoin 两套算子
  - 优化器：LogicalPlanner 与 PhysicalPlanner 两层；索引可用时改写为 IndexedNestedLoopJoin
  - 并发：单进程 RWLock（`threading.Condition`）+ 跨进程 `fcntl.flock`
  - 并发：WAL 段号 + 页 `last_lsn` 实现 READ COMMITTED 快照；可选 SERIALIZABLE
  - 并发：连接池 `Database(pool_size=N)`，默认 1（保持 v0.1 行为）
  - CLI：`prompt_toolkit.PromptSession` 替换 `cmd.Cmd`；多行编辑（`\` 续行 + 未闭合引号）
  - CLI：上/下方向键历史 + Ctrl-A/E 行内移动 + ANSI 语法高亮
  - CLI：`.explain <SQL>` / `.tables` / `.schema <t>` / `.history` / `.mode table|line` / `.quit`
  - CLI：SELECT 结果以 ASCII 表格输出（边框 + 列对齐 + 行数 + 耗时）
  - 兼容：v0.1 所有公共 API 保持向后兼容；826 + 727 测试 100% 通过
- **范围外**（范围护栏，违反即触发回退到 `specifying`）：
  - RIGHT JOIN / FULL OUTER JOIN / CROSS JOIN（v0.3 再议）
  - 子查询 / CTE / 窗口函数 / UNION
  - `ALTER TABLE` / 视图 / 触发器 / 外键
  - 主从复制 / 分布式事务 / 网络协议 / 客户端-服务器模式
  - MVCC 行级版本链（本版本用 WAL 段号 + 页 LSN）
  - GUI / Web UI
  - 强制 `prompt_toolkit` 安装（必须可选 + 降级）
  - 任何超出 `specs/` 的隐含 SQL 子集或 CLI 命令

## Approved Behavior

- **已批准需求摘要**：3 个 spec 文件 / **35 个 REQ** / 88 个 Scenario，全部以 `MUST` 形式表达
- **关键场景**（按能力挑选）：
  - `REQ-JOIN-1/2` INNER/LEFT JOIN 解析
  - `REQ-JOIN-5` JOIN 嵌套深度 ≤ 5（6 层报错）
  - `REQ-JOIN-6` NLJ INNER 正确 + LEFT 保留左表 + 右 NULL 填充
  - `REQ-JOIN-7` Planner 索引可用选 INLJ，无则回退 NLJ
  - `REQ-JOIN-8` USING 列去重；歧义列名报错
  - `REQ-CONC-1` 多读并发 + 写互斥 + 读写互斥
  - `REQ-CONC-2` 跨进程 `fcntl.flock` 排他；Windows 降级
  - `REQ-CONC-3` 快照隔离：事务内读一致 + 写冲突回滚
  - `REQ-CONC-7` 死锁检测：等待图 DFS，回滚最新事务
  - `REQ-CLI-1/2` 反斜杠续行 + 未闭合引号自动续行
  - `REQ-CLI-5` 关键字/字符串/数字/注释四类 ANSI 着色
  - `REQ-CLI-6` `.explain` 输出 LogicalPlan + PhysicalPlan 双节
  - `REQ-CLI-9` `prompt_toolkit` 不可用时降级 v0.1 cmd 行为
  - `REQ-CLI-12/13/14/15/16` MySQL 风格表格 + 行数耗时 + 对齐 + 元命令表格化 + `.mode` 切换
- **验收检查**：
  - 单元测试覆盖率 **≥ 80%**（`pytest --cov=src/tinydb --cov-fail-under=80` 必须通过）
  - v0.1 全部 826 测试 + 727 CLI 测试 100% 通过（兼容保证）
  - v0.2 新增测试预计 400+（JOIN ~150 + 并发 ~120 + CLI ~150）
  - 32 线程 INSERT/SELECT 5 秒压力测试无死锁无 race（REQ-CONC-8）
  - 4 进程 1W/3R 测试无脏读（REQ-CONC-8）
  - 范围审计：`git grep -nE "RIGHT JOIN|FULL JOIN|FULL OUTER|subquery|CTE|MVCC|trigger"` 在 `src/tinydb/` 命中须经用户批准
  - 依赖审计：`pip show prompt_toolkit` 缺失时 CLI 仍可用；存储/执行器仍零依赖
  - `examples/demo_v0_2.py` 端到端跑通（建表→JOIN→并发写→多线程读→CLI 执行计划）

## Design Constraints

- **架构约束**（来自 `design.md` 决策 D-1 ~ D-13）：
  - D-1: `LogicalPlanner` + `PhysicalPlanner` 两层，目录 `tinydb/executor/`
  - D-2: `NestedLoopJoin` 左驱动朴素循环；LEFT JOIN 填 NULL
  - D-3: `IndexedNestedLoopJoin` 复用 v0.1 B-tree + `IndexManager.seek()`
  - D-4: 进程内 `threading.Condition` 实现 RWLock；跨进程 `fcntl.flock` (Windows msvcrt 降级)
  - D-5: WAL 段号 + 页 `last_lsn:u32`（4 字节）实现 READ COMMITTED 快照
  - D-6: `DeadlockDetector` 等待图 + DFS；回滚最新事务
  - D-7: CLI 用 `prompt_toolkit.PromptSession`，运行时 `importlib.util.find_spec` 检测
  - D-8: SQL 语法高亮手写 tokenizer（复用 `tinydb/sql/tokenizer.py`），不引入 Pygments
  - D-9: `.explain` 输出 ASCII 树（`├──` / `└──` / `│`）
  - D-10: 3 个 git worktree 并行：`feature/v0.2-join`、`feature/v0.2-concurrency`、`feature/v0.2-cli`
  - D-11: ASCII 表格仅用 stdlib `str.ljust/rjust` + UTF-8 字节估算列宽
  - D-12: 计时仅发生在 CLI 层；`Connection.execute()` 仍返回 `list[dict]`
  - D-13: `.mode` 切换维护在 REPL 实例，会话级状态，不持久化
- **接口约束**（强制 API 形状，禁止改签名）：
  - `tinydb.open(path)` → `Database`（沿用 v0.1）
  - `Database.__init__(path, *, isolation: IsolationLevel = READ_COMMITTED, pool_size: int = 1)` (新增 2 个可选 kw)
  - `Database.acquire(timeout=None) -> Connection` / `Database.release(conn)` / `Database.connection()` 上下文管理器（新增）
  - `Database.execute(sql: str) -> list[dict]`（沿用 v0.1；不返回耗时）
  - `Database.explain(sql: str) -> str`（新增，CLI `.explain` 调）
  - `Database.list_tables() -> list[str]` / `Database.get_schema(table) -> str`（新增）
  - `Connection.execute(sql)` / `Connection.begin()` / `Connection.commit()` / `Connection.rollback()`（沿用 v0.1）
  - 公共异常新增：`DeadlockError` / `WriteConflictError` / `AmbiguousColumnError` / `IsolationLevel` 枚举
  - 所有内部模块通过 `src/tinydb/<package>/__init__.py` 暴露；外部不得直接 import 私有子模块
- **依赖约束**：
  - **运行时核心零外部依赖**：存储/执行器/事务层仅 Python stdlib
  - **运行时 CLI 可选依赖**：`prompt_toolkit>=3.0.40`（仅 CLI 子包；`pyproject.toml` 的 `[project.optional-dependencies.cli]` 声明；运行时检测，缺失即降级）
  - **测试时依赖**：`pytest` + `pytest-cov`（沿用 v0.1）
  - 任何新依赖引入必须先经用户批准（视为范围变更）
- **数据约束**：
  - v0.1 文件头 magic 不变（保持向后兼容）；页头扩展 4 字节 `last_lsn` 字段（v0.1 文件 `last_lsn=0` 默认）
  - WAL 段号连续递增，作为快照边界；段号溢出 (u64) 视为设计错误

## Task Batches

### Batch 10 — JOIN SQL 解析（worktree 1: feature/v0.2-join）

- **目标**：扩展 SQL parser 与 AST 支持 JOIN 子句
- **输入**：v0.1 `src/tinydb/sql/parser.py` + `ast.py`
- **输出**：T-10.1..10.4（JoinPlan/JoinKind 节点 + JOIN/ON/USING/别名解析）
- **完成标准**：tests/test_join.py 6+ parser 用例全部通过；REQ-JOIN-1/2/3/4/5 覆盖

### Batch 11 — LogicalPlanner 与 JoinPlan 生成（worktree 1）

- **目标**：把 SQL AST 改写为 LogicalPlan 含 JoinNode
- **输入**：Batch 10 产出
- **输出**：T-11.1..11.4（LogicalPlanner 拆分 + JoinNode 生成 + USING→ON 改写 + 别名解析）
- **完成标准**：tests/test_join.py logical 子套全部通过；REQ-JOIN-3/4/8 覆盖

### Batch 12 — PhysicalPlanner + JoinExecutor（worktree 1）

- **目标**：实现 NLJ + INLJ 算子并接入执行器
- **输入**：Batch 11 产出 + v0.1 IndexManager
- **输出**：T-12.1..12.6（PhysicalPlanner 拆分 + NestedLoopJoin + IndexedNestedLoopJoin + 算子选择 + 投影去重 + execute 接入）
- **完成标准**：tests/test_join.py 15+ 端到端用例全部通过；REQ-JOIN-6/7/8/9 覆盖

### Batch 13 — JOIN 集成测试与回归（worktree 1）

- **目标**：v0.1 测试在 JOIN 模块下全部通过
- **输入**：Batch 12 产出
- **输出**：T-13.1..13.2（端到端 JOIN 套件 + v0.1 826 测试回归）
- **完成标准**：`pytest tests/` 全绿；test_v0_1_compat.py 100% 通过

### Batch 14 — RWLock + DeadlockDetector + ProcessLock（worktree 2: feature/v0.2-concurrency）

- **目标**：实现三大并发原语
- **输入**：Python stdlib
- **输出**：T-14.1..14.3（RWLock + DeadlockDetector + fcntl/msvcrt ProcessLock）
- **完成标准**：tests/test_concurrent.py 原语测试全绿；REQ-CONC-1/2/7 覆盖

### Batch 15 — Transaction 接入 RWLock + 页 last_lsn（worktree 2）

- **目标**：事务生命周期接入并发控制；存储层加 LSN
- **输入**：Batch 14 产出 + v0.1 tx/storage
- **输出**：T-15.1..15.3（manager 集成 + lock.py 升级 + pager 加 last_lsn）
- **完成标准**：REQ-CONC-1/7 + v0.1 测试不退化

### Batch 16 — 读快照隔离（worktree 2）

- **目标**：READ COMMITTED 快照实现
- **输入**：Batch 15 产出
- **输出**：T-16.1..16.3（Snapshot 类 + BufferPool LSN 失效 + Transaction.begin 记录）
- **完成标准**：REQ-CONC-3/4/5 覆盖；v0.1 测试不退化

### Batch 17 — 连接池 + 跨进程锁集成 + 压测（worktree 2）

- **目标**：可选连接池 + WAL 跨进程锁 + 压力测试
- **输入**：Batch 16 产出
- **输出**：T-17.1..17.4（Database.acquire/release/connection + WAL fcntl 锁 + 32线程/4进程压测 + v0.1 单线程回归）
- **完成标准**：REQ-CONC-2/6/8/9 覆盖；32线程 5s 压测无死锁；4进程 1W/3R 无脏读

### Batch 18 — CLI prompt_toolkit 迁移 + 降级（worktree 3: feature/v0.2-cli）

- **目标**：REPL 替换 cmd 为 PromptSession；缺失时降级
- **输入**：v0.1 cli/repl.py
- **输出**：T-18.1..18.3（检测 + PromptSession 多行编辑 + 降级 cmd）
- **完成标准**：REQ-CLI-1/2/3/4/9 覆盖；v0.1 727 测试在两种模式都通过

### Batch 19 — 语法高亮 + EXPLAIN（worktree 3）

- **目标**：SQL ANSI 着色 + `.explain` 元命令
- **输入**：Batch 18 产出 + Batch 12 的 PhysicalPlan
- **输出**：T-19.1..19.4（highlight.py + lexer 集成 + format_plan + `.explain` 元命令）
- **完成标准**：REQ-CLI-5/6 覆盖

### Batch 20 — 元命令 + 历史持久化 + MySQL 风格结果（worktree 3）

- **目标**：`.tables`/`.schema`/`.history`/`.quit` + FileHistory + ASCII 表格 + 计时 + `.mode` 切换
- **输入**：Batch 19 产出
- **输出**：T-20.1..20.10（FileHistory + .tables/.schema + .history + .quit + v0.1 回归 + ASCII 表格渲染器 + 计时 + 元命令表格化 + .mode 切换 + 集成测试）
- **完成标准**：REQ-CLI-7/8/10/11/12/13/14/15/16 覆盖；v0.1 727 测试在 PT-present 与 PT-absent 双模式全绿

### Batch 21 — 集成 + Release（worktree integrate: feature/v0.2-integrate）

- **目标**：合并 3 worktree + e2e + 文档 + tag
- **输入**：3 worktree 分支
- **输出**：T-21.1..21.4（合并 + e2e 故事 + pyproject + README + DP-6 验证 + DP-7 release + tag `tinydb-v0.2.0`）
- **完成标准**：4 项 acceptance checks 全绿；覆盖率 ≥ 80%；范围审计无越界；tag 推送

## Test Obligations

- **必须先从失败测试开始的行为**：
  - 所有 38 个 T-task 第 1 步必须是 RED（写一个失败的 pytest 用例）
  - 任何代码修改前必须有对应测试
- **必需的边界情况**：
  - JOIN：空表、嵌套 5 层边界、6 层报错、单行匹配、多行匹配、USING 列去重、列名歧义、索引不存在
  - 并发：32 线程压测、4 进程 1W/3R、写冲突回滚、循环死锁、跨平台 fcntl 缺失
  - CLI：未闭合引号、反斜杠续行、宽字符列宽、NULL/BLOB/大数混合、`prompt_toolkit` 缺失降级
- **回归敏感区域**：
  - v0.1 826 单元测试 + 727 CLI 测试（v0.1 compat suite 在 Batch 13/17/20 复用）
  - 性能预算：单线程单事务 P95 不退化 > 5%（REQ-CONC-9）
  - 文件头向后兼容：v0.1 生成的 `.db` 文件能在 v0.2 打开（页 `last_lsn` 默认 0）

## Execution Mode

- **模式**：`SDD` (Subagent-Driven Development)
- **选择理由**：
  - 12 批次 / 38 任务 / 3 个独立 worktree 并行，远超 `inlineThreshold=3`
  - 每能力边界清晰（JOIN 只改 sql+executor；并发只改 tx+storage；CLI 只改 cli 包）
  - 用户在 DP-0 显式选择 `execution_mode=sdd` 并确认并行策略
  - 单批次超过 3 任务时强制走 SDD 模式（per-task implementer subagent dispatch + per-task reviewer subagent dispatch）
- **SDD 含义**（来自 build-executor SKILL.md，与 superpowers `subagent-driven-development` 一致）：
  - **Per-Task Loop**：每个 T-task 由 `build-executor/implementer-prompt.md` dispatch 一个 implementer 子代理实现 → 由 `build-executor/task-reviewer-prompt.md` dispatch 一个 reviewer 子代理审查 → 双重 verdict（spec 合规 + 代码质量）
  - **Critical/Important 问题**：dispatch fix 子代理修复后重新审查
  - **进度账本**：`.superpowers/sdd/progress.md` 记录每任务 `Task N: complete (commits <base7>..<head7>, review clean)`
  - **模型选择**：机械任务用 cheap 模型，集成/判断任务用标准模型，架构/设计任务用最强大模型
  - **最终 broad review**：所有批次完成后做一次全量 review

## Verification Dimensions

| 维度 | 状态 | 发现 |
|------|------|------|
| Completeness | Pending | — |
| Correctness | Pending | — |
| Coherence | Pending | — |

**总体结论**：Pending

## Review Gates

- **强制审查点**：
  - 每批次完成后（per-batch review）：code-reviewer agent 在每个 T-task 第 5 步 COMMIT 前
  - 3 个 worktree 合并到 `feature/v0.2-integrate` 时（merge review）
  - DP-6 验收检查（4 项 acceptance all-green）
  - DP-7 release 归档（changes/tinydb-v0.2/ 归档到 changes-archive/）
- **阻塞类别**：
  - **CRITICAL**：v0.1 测试回归、文件格式破坏、并发场景数据竞争或死锁
  - **HIGH**：spec REQ 未覆盖、性能退化 > 5%、范围越界（JOIN/并发/CLI 之外的隐含能力）
  - **MEDIUM**：测试覆盖 < 80%、缺文档、未清理死代码

## Escalation Rules

- **何时回退到 `specifying`**：
  - `proposal.md` 范围变化（新增 Out 之外的 REQ 能力、移除 In 中的能力）
  - `specs/` 新增 REQ 或修改现有 REQ 的 MUST/SHALL 语义
  - `design.md` 决策被推翻需要重新设计
- **何时回退到 `bridging`**：
  - `tasks.md` 批次分解发生实质变化（增删批、合并批、改动接口契约）
  - `execution-contract.md` 与 `tasks.md` 对应关系出现 drift
- **何时不得继续实现**：
  - DP-3 未获用户显式批准
  - 任何 CRITICAL/HIGH 审查问题未关闭
  - v0.1 compat suite 失败（必须先修复，不允许跳过）
  - 跨进程锁在 CI 平台不支持且无降级（fail-fast，不静默退化）
- **冲突解决**：
  - 合同与源工件冲突 → 以源工件为准，刷新合同
  - 源工件之间冲突 → 按 `proposal > specs > design > tasks` 优先级