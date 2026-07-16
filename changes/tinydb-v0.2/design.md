# Design: tinydb-v0.2

## Context

- **起点**: tinydb v0.1 已发布（tag `tinydb-v0.1.0`，master HEAD `46da7e9`），826 测试 / 91.44% 覆盖率，9 批次 47 任务全部完成
- **现有架构**: `src/tinydb/{sql,storage,executor,index,tx,types,api,cli}`，零外部依赖，单写者单事务 WAL，4KB 页 + LRU 缓冲池 (64 页)，B-tree 索引，Python `cmd` REPL
- **目标产物**: 在 v0.1 基础上扩展为 v0.2，引入 JOIN/并发/CLI 增强三条新能力，保持公共 API 100% 向后兼容
- **使用模型**: 从 v0.1 的单进程单事务升级为单进程多事务 + 多进程文件互斥；CLI 从基础 REPL 升级为多行编辑 REPL
- **硬约束**（来自 `dp_0_decisions`）: Python 3.10+、零外部依赖（运行时）/ `prompt_toolkit>=3.0.40` 可选（CLI）、单 `.db` 文件、B-tree 索引沿用、WAL 事务增强为支持并发、pytest 80%+
- **目标用户**: v0.1 现有用户 + 需要多表业务表达 + 需要安全并发的工程师 + 想要更专业 CLI 的使用者
- **非目标**（来自 `proposal.md > Out`）: RIGHT/FULL JOIN、子查询、CTE、窗口函数、视图/触发器/外键、网络/复制、查询计划缓存、GUI

## Goals

1. **可读性优先**: 新模块 200-400 行，关键路径 docstring 解释"为什么"
2. **可测试性**: 所有 capability 都先写 pytest 用例（RED→GREEN→IMPROVE）
3. **正确性**: 并发场景下无死锁/无 race/无脏读
4. **教学完整**: JOIN 算子/事务隔离/REPL 实现仍是 RDB 经典知识
5. **零核心依赖**: 存储/执行器/事务层仍零依赖；仅 CLI 子包可选 `prompt_toolkit`
6. **向后兼容**: v0.1 的 826 + 727 测试 100% 通过；公共 API 仅新增可选 kw 参数
7. **优雅降级**: `prompt_toolkit` 不可用时 CLI 退化为 v0.1 行为；不支持 `fcntl` 的平台降级为进程内锁

## Decisions

### D-1: JOIN 算子分两层（Logical / Physical）
- **Choice**: 在 `tinydb/executor/planner.py` 新增两层规划：`LogicalPlanner` 把 SQL AST 改写为 `LogicalPlan`（含 `Join(left, right, kind, on_expr)` 节点），`PhysicalPlanner` 根据索引信息选择 `NestedLoopJoin` 或 `IndexedNestedLoopJoin`
- **Rationale**:
  - 与 v0.1 的 `executor/planner.py` 一脉相承（v0.1 已有 LogicalPlan→PhysicalPlan 的雏形）
  - 物理算子可独立替换（未来加 HashJoin 不影响上层）
  - 测试可分层：先测 LogicalPlan 正确性，再测 PhysicalPlan 选择
- **Alternatives considered**:
  - **直接 AST → PhysicalPlan**: 简单但难以优化
  - **查询优化器 (Selinger-style)**: 强大但对教学项目过重
  - **代价模型 + 统计信息**: 需要 catalog 统计，本版本不做
- **Trade-off**: 多一层抽象，代码量 +100 行，换可扩展性

### D-2: NestedLoopJoin 实现为左驱动朴素循环
- **Choice**: `tinydb/executor/join.py` 的 `NestedLoopJoin.execute(left, right, on_expr)` 对左输入的每行调用 `right.open()` 并流式遍历；`LEFT JOIN` 在右无匹配时填充 NULL
- **Rationale**:
  - 简单到 50 行可读
  - 流式避免一次性物化大结果
  - 对未索引列是唯一可行选项
- **Alternatives considered**:
  - **Hash Join**: 适合等值连接但需物化右表，对小左表+大右表优势不明显
  - **Sort-Merge Join**: 需要排序输入，对小数据集过度
- **Trade-off**: 复杂度 O(N×M)，无索引时表现差；依赖 IndexedNestedLoop 优化兜底

### D-3: IndexedNestedLoopJoin 复用 B-tree
- **Choice**: 当 `on_expr` 为等值条件且其中一侧列有 B-tree 索引时，`PhysicalPlanner` 把左输入作为驱动表、对每行通过 `IndexManager.seek()` 取得右表候选行集
- **Rationale**:
  - 复用 v0.1 已有的 `tinydb/index/btree.py` 与 `IndexManager`，零新增索引代码
  - 对小左表+大右表的常见场景（如"用户-订单"）性能提升 100x+
  - 与 v0.1 的 `WHERE col = ?` 索引路径保持一致
- **Alternatives considered**:
  - **强制 Hash Join**: 实现成本高，且不支持范围条件
  - **Bitmap Index**: v0.1 没有，且增加存储开销
- **Trade-off**: 仅支持等值 + 单列索引；多列复合索引留 v0.3

### D-4: 并发模型选 RWLock + 跨进程 fcntl
- **Choice**: 单进程内用 `tinydb/concurrent/rwlock.py` 实现读写锁（基于 `threading.Condition` + `threading.Lock`，优先写防饥饿）；跨进程用 `tinydb/concurrent/fcntl_lock.py` 在 WAL 追加期间持有 `fcntl.flock(LOCK_EX)`
- **Rationale**:
  - `threading` 是 stdlib，零依赖
  - `fcntl` Linux/macOS 原生支持；Windows 降级到 `msvcrt.locking`
  - RWLock 是 RDB 并发经典模型（SQLite WAL 模式同思路）
  - 跨进程只锁 WAL 而非整个 .db 文件，读者无须跨进程锁
- **Alternatives considered**:
  - **MVCC**: 强大但需保留多版本行，存储开销大；教学价值高但实现重
  - **OCC (Optimistic CC)**: 写冲突率高时性能差
  - **Lock per row**: 死锁检测复杂
- **Trade-off**: 写并发退化为单写者；适合读多写少场景；与 v0.1 单写者假设一致

### D-5: READ COMMITTED 快照实现为 WAL 段号 + 页版本
- **Choice**: `tinydb/tx/snapshot.py` 用事务开始时的 WAL 段号作为快照标识；缓冲池记录每页最后修改的 WAL 段号；读事务只接受段号 ≤ 快照号的页版本
- **Rationale**:
  - 复用 v0.1 的 WAL/REDO/UNDO 机制，无新存储结构
  - 段号天然单调递增，作为版本号直观
  - 实现简单：每页加 4 字节 last_lsn 字段
- **Alternatives considered**:
  - **完整 MVCC (行级版本链)**: 需要 row 头加 tx_id+roll_ptr，约 12 字节/行，对嵌入式 RDB 偏重
  - **Timestamp-based**: 需要 wall clock 同步，单进程内不必
- **Trade-off**: 写者仍需等待旧读事务（段号 ≤ 快照的页不可被驱逐/覆盖），但 64 页缓冲池 + 短事务不会成为瓶颈

### D-6: 死锁检测用等待图 + 周期检测
- **Choice**: `tinydb/concurrent/deadlock.py` 维护 `waits_for` 图（事务 → 等待锁持有者），DFS 检测环；检测到环时回滚最新启动的事务
- **Rationale**:
  - 简单有效，10-20 行可实现
  - 回滚最新事务是经典策略（年轻事务被牺牲）
  - 教学价值高：死锁检测是数据库经典话题
- **Alternatives considered**:
  - **超时回滚**: 实现简单但难调阈值
  - **预防 (按 ID 排序锁)**: 限制多，对复杂事务不友好
- **Trade-off**: 检测在锁请求路径上同步执行，极端场景 O(N²) 但 N 通常 < 100

### D-7: CLI 替换 cmd 为 prompt_toolkit
- **Choice**: `tinydb/cli/repl.py` 用 `prompt_toolkit.PromptSession` 替换 `cmd.Cmd`；提供 `lexer`/`formatter` 给 ANSI 着色；`history=` 参数绑定 `FileHistory('~/.tinydb_history')`
- **Rationale**:
  - `prompt_toolkit` 是事实标准，支持多行/历史/补全/着色一次性到位
  - 单文件可选依赖：检测 `importlib.util.find_spec('prompt_toolkit')`，失败则回退 v0.1 `cmd`
  - 不强制安装：用户 `pip install prompt_toolkit` 才有完整体验，否则是基础 REPL
- **Alternatives considered**:
  - **自实现 readline + ANSI**: 100+ 行且跨平台坑多
  - **pyrepl / urwid**: 生态小
  - **强制 prompt_toolkit**: 违背零依赖承诺
- **Trade-off**: 引入一个可选第三方依赖（运行时检测，不强制安装）

### D-8: 语法高亮基于 Pygments 还是手写？
- **Choice**: `tinydb/cli/highlight.py` 手写 tokenizer（复用 v0.1 的 SQL tokenizer） + 4 类颜色表；不引入 Pygments
- **Rationale**:
  - SQL 子集小（关键字 ~40 个），手写 50 行即可
  - 避免引入 Pygments 巨无霸
  - 与 v0.1 tokenizer 一致，颜色规则可单测
- **Alternatives considered**:
  - **Pygments**: 完整但 1MB+ 依赖
  - **rich**: 同 Pygments 重量级
- **Trade-off**: 不支持非 SQL 子句；未来扩展需手动加关键字

### D-9: .explain 输出格式用 ASCII 树
- **Choice**: `tinydb/cli/explain.py` 把 `PhysicalPlan` 渲染为带 `├──`/`└──`/`│` 的 ASCII 树，LogicalPlan 同理
- **Rationale**:
  - 终端普适，无需 Unicode 字体
  - 与 SQL `EXPLAIN` 业界惯例对齐（PostgreSQL psql 同风格）
  - 易测试：固定字符串断言
- **Alternatives considered**:
  - **JSON/YAML**: 机器友好但人眼不友好
  - **Mermaid**: 需要外部渲染
  - **Graphviz dot**: 需要外部工具
- **Trade-off**: 嵌套深时行宽可能爆，但 JOIN 深度 ≤5 可控

### D-10: 三个独立 git worktree 并行
- **Choice**: 创建 3 个 worktree 分支 `feature/v0.2-join`、`feature/v0.2-concurrency`、`feature/v0.2-cli`，各自在隔离工作区实现；通过共享 API 边界（`tinydb/api.py` 接口稳定 + 抽象类 `PhysicalOperator`/`Transaction`）集成；合并到 `feature/v0.2-integrate` 做 e2e 测试
- **Rationale**:
  - 三大能力互相对独立（JOIN 只改 sql+executor；并发只改 tx+storage；CLI 只改 cli 包）
  - 接口边界清晰：v0.1 的 public API 是稳定契约
  - 并行可节省 60% wall-clock 时间
- **Alternatives considered**:
  - **单 worktree 串行**: 简单但慢
  - **MONOREPO 子包**: 改动 v0.1 结构过大
- **Trade-off**: 合并冲突需要精心设计接口；e2e 集成阶段串行

### D-11: ASCII 表格格式化（手写 stdlib）
- **Choice**: `tinydb/cli/format.py` 提供 `format_table(rows: list[dict], columns: list[str]) -> str` 与 `format_line_mode(rows) -> str`；仅用 `str.ljust/rjust` + `len(str.encode('utf-8'))` 处理中英混排列宽；零外部依赖
- **Rationale**:
  - 表格渲染是纯字符串拼接，不引入 tabulate/prettytable 等第三方库（零核心依赖）
  - 类型驱动的对齐：数值右、字符串左、JSON/BLOB/DATE 各按规则走；可通过 `_align_for(typ)` 扩展
  - 与 prompt_toolkit 的 ANSI 着色共存：表格内字符串仍可被 `Lexer` 二次着色（REQ-CLI-15）
- **Alternatives considered**:
  - **tabulate**: 6KB 依赖；功能强但不需要
  - **rich Table**: 重量级 + 1MB+ 依赖
  - **手写 + wcwidth**: 多语言列宽精确但需要额外库
- **Trade-off**: 中日韩字符宽度按 2 计算（粗略估算）；用户需要精确宽时切 `.mode line`

### D-12: 计时仅发生在 CLI 层
- **Choice**: `Connection.execute()` 不返回耗时；CLI REPL 用 `time.perf_counter()` 包裹调用，渲染结果时附带耗时；耗时数据不进入 API 层
- **Rationale**:
  - 公共 API 返回 `list[dict]` 是 v0.1 兼容契约；不应附加计时字段
  - CLI 是唯一需要可见耗时的层级；嵌入式调用（Python import tinydb）由调用方自行测时
  - 计时本身 < 1μs 开销，不影响 REQ-CONC-9 的 5% 性能预算
- **Alternatives considered**:
  - **API 返回 `(rows, elapsed)`**: 破坏 v0.1 接口契约
  - **ContextVar 传递计时器**: 隐式状态，难调试
- **Trade-off**: CLI 用户无法在 Python API 中拿到耗时；如需可以包 `time.perf_counter()` 自行测量

### D-13: .mode 切换会话级状态
- **Choice**: REPL 维护 `_mode: Literal["table", "line"]`，默认 `"table"`；`.mode line` / `.mode table` 切换；状态保存在 REPL 实例（不持久化到 `~/.tinydb_history`）
- **Rationale**:
  - MySQL CLI 同款交互；用户预期不跨会话保留
  - REPL 实例已经是会话级作用域；状态归属清晰
  - 不写入历史文件避免污染命令历史
- **Alternatives considered**:
  - **持久化到配置文件**: 与 `.tinydbrc` 概念重叠，本版本不做配置文件
  - **每个查询临时指定**: `.mode` 即时切换 + SQL 前缀 `\\line` 太冗长
- **Trade-off**: 重启 REPL 后回到默认 table 模式；显式 `.mode` 即可恢复

## Risks And Trade-Offs

| 风险 | 影响 | 缓解 |
|------|------|------|
| fcntl 在 Windows 不支持 | 跨平台 CI 失败 | 检测 + 降级到 msvcrt 或单进程模式 + 文档说明 |
| `prompt_toolkit` 与零依赖承诺冲突 | v0.1 用户期望纯 stdlib | 明确为 CLI 子包可选依赖；运行时检测；缺失时降级 |
| JOIN 5 层嵌套限制被用户绕过 | 报错不友好 | 错误信息明确建议改写 SQL；后续 v0.3 再放开 |
| 读快照下写者仍需等待 | 写并发可能受限 | 64 页缓冲池 + 短事务压测验证；不通过则调整缓冲池大小 |
| 三 worktree 集成冲突 | 集成阶段失败 | 接口设计预留扩展点；e2e 测试在整合分支先跑 |
| JOIN 性能在大数据集下降 | 教学价值受损 | 文档明确"小数据/教学"定位；提供 EXPLAIN 帮用户定位 |
| 死锁检测 O(N²) | 高并发死锁检测慢 | N 通常 < 100 没问题；超 100 加超时回滚兜底 |
| 历史文件跨平台路径 | Windows 路径 `~/.tinydb_history` 解析 | 用 `pathlib.Path.home()`，跨平台一致 |
| v0.1 CLI 测试在 prompt_toolkit 模式下行为变化 | 727 测试可能失败 | 基础模式无 prompt_toolkit 时跑现有测试；新模式跑新测试；CI 矩阵双模式 |
| 表格化在宽字符（CJK）列宽不准 | 中文/日文对齐错位 | 按 UTF-8 字节数估算宽度（粗略 2 字节/字符）；用户可切 `.mode line` 规避 |
| 计时精度低于 1ms 显示为 0.00s | 用户误以为瞬时 | 仍保留小数；超 1ms 才显示非零；文档说明最小精度 |
| ANSI 颜色与表格边框冲突 | 边框被着色破坏 | 边框作为 plain 字符串渲染；着色仅作用于 cell 内容 |