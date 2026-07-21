# Proposal: tinydb-v0.2

## Why

tinydb v0.1 已交付一个零依赖嵌入式 RDB，覆盖存储/解析/查询/索引/事务/类型/CLI 全部核心能力（826 测试，91.44% 覆盖率，9 批次 47 任务），但其 `proposal.md > Out` 显式排除了多表 JOIN 与并发控制，CLI 也只是基础 REPL。用户调研显示 v0.1 的两个最常见痛点是：（1）涉及多张表的真实业务无法表达（必须把数据塞进 JSON 字段或预先反规范化），（2）CLI 在写入多行 SQL 时无法编辑、报错时无法定位，且没有 SQL 执行计划可读性。需要 v0.2 在不破坏 v0.1 接口兼容的前提下补齐这三条能力。

## What Changes

扩展 tinydb v0.1 为 v0.2，新增三项能力：

1. **多表 JOIN**：SQL 解析层新增 `INNER JOIN` 与 `LEFT JOIN` 语法，AST 与执行器支持二元 JoinPlan、嵌套循环连接、ON/USING 条件求值、连接列投影；新增 IndexNestedLoop 优化以复用 B-tree。
2. **并发控制**：在保留 WAL/REDO/UNDO 的前提下，新增多线程（`threading.RWLock`）与多进程（`fcntl` 文件锁 + 共享内存页缓存失效）的安全语义；事务从单写者升级为单写者多读者；新增连接级隔离（`READ COMMITTED` 快照）。
3. **CLI 增强**：REPL 升级为多行编辑（`prompt_toolkit` 替换 `cmd`）、ANSI 语法高亮、关键字补全、`.explain <SQL>` 输出树形执行计划、`.tables`/`.schema`/`.history` 等元命令、行内历史持久化（`~/.tinydb_history`）；SELECT 结果以 MySQL CLI 风格的 ASCII 表格输出（带边框 + 列对齐 + 行数与耗时统计），`.explain`/`.tables`/`.schema` 同样应用表格样式（保留文本/颜色）。

保持零外部依赖作为强约束：v0.2 在运行时新增的依赖为 `prompt_toolkit`（CLI 增强用），并显式作为可选/可降级（CLI 无 prompt_toolkit 时回退 v0.1 行为）；存储与执行器仍零依赖。

## Scope

### In

- SQL：扩展语法 `SELECT ... FROM t1 [INNER|LEFT] JOIN t2 ON <expr> [JOIN t3 ON ...]`，可多层嵌套（最多 5 层以保性能）
- SQL：USING 子句 (`JOIN t USING (col)`)、表别名 (`FROM users u, orders o`)、连接列投影去歧义
- 执行器：新增 `JoinExecutor`，支持 NestedLoopJoin、IndexedNestedLoopJoin
- 优化器：解析后产出初始 LogicalPlan，可在索引可用时改写为 IndexedNestedLoop
- 并发：每 `Database` 持有 `RWLock`，读事务可并发，写事务独占
- 并发：跨进程用 `fcntl.flock` 排他锁保护 WAL 追加；缓冲池失效通过文件 mtime/inode 检测
- 并发：新增连接池可选（`Database(pool_size=N)`），无池时每连接独占事务
- 并发：隔离级别显式参数 `Database(isolation="READ COMMITTED")`（默认）/ `"SERIALIZABLE"`
- CLI：多行编辑（反斜杠续行或未闭合引号自动续行）、上/下方向键历史、Ctrl-A/E 行内移动、Ctrl-C 中断
- CLI：SQL 关键字/字符串/数字/注释四类语法高亮
- CLI：`.tables`（列出表名）/`.schema <table>`（DDL 形式打印建表语句）/`.explain <SQL>`（树形计划）/`.history`（最近 N 条）/`.quit`
- CLI：SELECT 结果以 ASCII 表格输出（边框 + 列对齐 + NULL 字面量 + 行数 + 耗时），`.explain`/`.tables`/`.schema` 元命令输出同样应用表格样式（保留文本与颜色）
- CLI：对齐规则：数值右对齐、字符串/日期/JSON 左对齐、BLOB 十六进制（`0x...`）显示、NULL 显示字面量 `NULL`
- 兼容：v0.1 所有公共 API（`open`、`Database.execute`、`Transaction` 接口）保持向后兼容

### Out

- ALTER TABLE / 视图 / 触发器 / 外键（与 v0.1 一致）
- 客户端-服务器模式 / 网络协议
- 主从复制 / 分布式事务
- RIGHT JOIN / FULL OUTER JOIN / CROSS JOIN（本版本不做，留给 v0.3）
- 子查询（`SELECT * FROM t WHERE id IN (SELECT ...)`）— 与 JOIN 互斥，本版本先聚焦 JOIN
- 物化视图 / 公共表表达式 (CTE) / 窗口函数
- 查询计划缓存（每次重新规划）
- GUI / Web UI（仅 CLI）
- `prompt_toolkit` 之外的备选 REPL 库

## Impact

- 受影响模块：`tinydb/sql/parser.py`（JOIN 语法）、`tinydb/sql/ast.py`（JoinPlan 节点）、`tinydb/executor/planner.py`（LogicalPlan → PhysicalPlan）、`tinydb/executor/operators.py`（JoinExecutor）、`tinydb/tx/manager.py`（事务并发）、`tinydb/tx/lock.py`（升级为 RWLock）、`tinydb/storage/pager.py`（多进程失效检测）、`tinydb/cli/repl.py`（替换 cmd 为 prompt_toolkit）、`tinydb/api.py`（Database 新增 `isolation`/`pool_size` 参数）
- 新增模块：`tinydb/cli/highlight.py`（ANSI 着色）、`tinydb/cli/explain.py`（执行计划格式化）、`tinydb/cli/history.py`（历史持久化）、`tinydb/executor/join.py`（JoinExecutor）、`tinydb/tx/snapshot.py`（读快照）、`tinydb/concurrent/fcntl_lock.py`（跨进程锁）
- 新增可选依赖：`prompt_toolkit>=3.0.40`（仅 CLI 子包需要，运行时检测）
- 测试影响：现有 826 测试必须 100% 通过；新增测试预计 +400（每项能力约 100-150 用例）
- 公共 API：`Database(path, isolation="READ COMMITTED", pool_size=1)` 新增两个可选关键字参数；旧调用方式 100% 兼容
- 文档：`docs/CLI_USAGE.md` 新增、现有 README 增补 JOIN 与并发小节
- 性能预算：单表扫描 P95 不退化 5% 以上；3 表 JOIN + 1k 行 P95 < 50ms

## Capabilities

| 能力 | 描述 |
|------|------|
| JOIN 语法 | 解析 INNER/LEFT JOIN 子句、ON/USING 条件、表别名 |
| JOIN 执行 | NestedLoop 与 IndexedNestedLoop 两套算子，可被规划器选择 |
| 并发事务 | 单进程多线程读写锁 + 多进程文件锁 + 读快照隔离 |
| 多行 CLI | 反斜杠/未闭合引号续行、行内编辑、历史导航 |
| 语法高亮 | SQL 关键字/字符串/数字/注释的 ANSI 着色 |
| 执行计划 | `.explain` 输出 LogicalPlan 与 PhysicalPlan 的树形可视化 |
| 元命令 | `.tables` / `.schema` / `.history` / `.quit` 与 `.help` |
| 结果表格化 | SELECT 结果以 ASCII 表格展示（边框 + 对齐 + 行数 + 耗时）；元命令输出同样应用表格样式 |
| 依赖降级 | `prompt_toolkit` 不可用时 CLI 回退 v0.1 行为 |