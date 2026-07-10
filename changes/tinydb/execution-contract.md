# 执行合同

> 本合同由 `proposal.md` + `specs/` + `design.md` + `tasks.md` 派生。
> 任何与源工件冲突的内容以源工件为准；发现冲突时按 Escalation Rules 处理。
> DP-3 是 hard gate，未经用户显式批准不得开始实施。

## Intent Lock

- **变更名称**：`tinydb`
- **要解决的问题**：缺乏既可教学拆解（理解 RDB 内核）又可在小项目中实际使用的轻量级 Python 嵌入式关系型数据库
- **范围内**：
  - 纯 SQL 字符串接口 (`db.execute("SELECT ...")`)
  - DDL：`CREATE TABLE` / `DROP TABLE`
  - DML：`INSERT` / `SELECT` / `UPDATE` / `DELETE`
  - WHERE 条件 (AND/OR，含 `IS NULL` / `IS NOT NULL`)
  - `ORDER BY` (ASC/DESC) + `LIMIT` + `OFFSET`
  - 列约束：`PRIMARY KEY` / `NOT NULL` / `UNIQUE`
  - 聚合函数：`COUNT(*)` / `COUNT(col)` / `SUM(col)` / `AVG(col)` + `GROUP BY`
  - B-tree 索引（等值 + 范围扫描 + 复合键）
  - 10 种类型：`INT` / `FLOAT` / `TEXT` / `BOOL` / `DATE` / `TIME` / `DATETIME` / `DECIMAL` / `BLOB` / `JSON` + `NULL`
  - ACID 事务：`BEGIN` / `COMMIT` / `ROLLBACK`，WAL + REDO/UNDO 恢复
  - 单文件 `.db` 持久化 (4KB 页式 + LRU 缓冲池)
  - CLI / REPL (`tinydb <path>`, `-c "<sql>"`, 元命令 `.tables` / `.schema` / `.exit` 等)
- **范围外**（范围护栏，违反即触发回退到 `specifying`）：
  - 多表 JOIN 查询
  - 并发控制（多线程 / 多进程安全）
  - `ALTER TABLE`、视图、触发器、外键
  - 网络 / 客户端-服务器模式
  - 任何超出 `specs/` 的隐含 SQL 子集（CTE / window function / 子查询 / UNION 等）

## Approved Behavior

- **已批准需求摘要**：7 个 spec 文件 / **61 个 REQ** / **149 个 Scenario**，全部以 `MUST` / `MUST NOT` 形式表达
- **关键场景**（挑选自 specs/）：
  - `REQ-SQL-7` 解析错误带行/列位置
  - `REQ-STO-1` 单文件持久化 + 跨重启保留
  - `REQ-STO-2` 跨页溢出记录
  - `REQ-STO-3` 缓冲池 LRU 驱逐
  - `REQ-QEX-3` 等值索引查找替代全表扫描
  - `REQ-IDX-5` UNIQUE 拒绝重复键
  - `REQ-TRX-2/3/4/5` 完整 ACID 语义
  - `REQ-TRX-6/7` WAL 帧格式 + REDO/UNDO 恢复
  - `REQ-TYP-6` 类型强制规则（整数→浮点允许，浮点→整数/字符串→数字拒绝）
  - `REQ-CLI-1/3/5/8` 路径参数 / 表格输出 / 元命令 / 一次性执行
- **验收检查**：
  - 单元测试覆盖率 **≥ 80%**（`pytest --cov=src/tinydb --cov-fail-under=80` 必须通过）
  - 7 个 spec 文件全部存在且每 REQ 至少 1 个 `pytest` 用例覆盖
  - `tests/tx/test_recovery.py` 模糊测试 100+ 随机操作序列后崩溃恢复正确
  - `examples/demo.py` 端到端跑通 (create/insert/index/tx/REPL)
  - 范围审计：`git grep -nE "JOIN|OUTER JOIN|threading\.(Lock|RLock)"` 在 `src/tinydb/` 命中须经用户批准

## Design Constraints

- **架构约束**（来自 `design.md` 决策 D-1 ~ D-13）：
  - D-1: SQL 解析器为手写递归下降（`src/tinydb/sql/parser.py`），禁止引入 PLY / lark / pyparsing
  - D-2: 4KB 固定页 + 文件头 `magic + version + page_size`
  - D-3: LRU 缓冲池默认 64 页 = 256KB
  - D-4: 经典 B-tree（不分离 B+tree），order ≥ 64
  - D-5: WAL append-only，frame = `[lsn:u64, type:u8, payload:bytes, crc:u32]`
  - D-6: 单写者 `WriteLock`（基于 `threading.RLock` 上下文管理器，但**不**启用多线程并发）
  - D-7: 序列化 = 1 字节 `TypeTag` + 变长 payload (length-prefix)
  - D-8: CLI 使用 stdlib `cmd.Cmd` + `argparse`，禁止 prompt_toolkit
  - D-9: 项目布局 `src/tinydb/` + `tests/`
  - D-10: pytest TDD，每 REQ 至少 1 个集成测试
  - D-11: DECIMAL 以 `decimal.Decimal` 字符串形式存
  - D-12: JSON 使用 stdlib `json`
  - D-13: BLOB 字面量为 base64
- **接口约束**（强制 API 形状，禁止改签名）：
  - `tinydb.open(path: str) -> Database` (顶层)
  - `Database.execute(sql: str) -> list[dict]` (核心)
  - `Database.close() -> None` / `__enter__` / `__exit__`
  - 公共异常：`tinydb.TinydbError` / `ParseError(line, col, msg)` / `ConstraintViolation` / `NotNullViolation` / `TypeMismatchError`
  - 所有内部模块通过 `src/tinydb/<package>/__init__.py` 暴露，外部不得直接 import 私有子模块
- **依赖约束**：
  - **运行时零外部依赖**：仅 Python stdlib (`struct`, `os`, `decimal`, `datetime`, `json`, `base64`, `cmd`, `argparse`, `threading`, `dataclasses`, `collections`, `typing`, `io`)
  - **测试时依赖**：`pytest` + `pytest-cov` (允许在 `pyproject.toml` 的 `[project.optional-dependencies.test]` 段声明)
  - 任何新依赖引入必须先经用户批准（视为范围变更）
- **数据约束**：
  - 数据库文件后缀 `.db`，文件头固定 4KB，包含 magic `0xT1NYDB1`、version u16、page_size u16
  - WAL 文件与 `.db` 同目录，命名 `<dbname>.wal`
  - Catalog 表存于页 1-3，保留区
  - 单进程单连接单写者；不跨进程访问同一 `.db` 文件（视为未定义行为）

## Task Batches

> 完整 47 个任务见 `tasks.md`。本节定义**实施批次**与每批完成标准。

### Batch 1 — Foundation
- **目标**：类型系统、错误模型、codec 闭环
- **输入**：无（自包含）
- **输出**：`src/tinydb/{errors.py, types/}` + `tests/types/` + `tests/test_errors.py`
- **完成标准**：`pytest tests/types tests/test_errors.py tests/test_smoke.py --cov=src/tinydb/types --cov=src/tinydb/errors --cov-fail-under=85` 通过；10 种类型 roundtrip 全绿

### Batch 2 — Storage
- **目标**：4KB 页式存储 + LRU 缓冲池 + 堆表 + catalog
- **输入**：B1 完成的类型
- **输出**：`src/tinydb/storage/` + `tests/storage/`
- **完成标准**：`pytest tests/storage --cov=src/tinydb/storage --cov-fail-under=85` 通过；可独立 `from tinydb.storage import Pager, BufferPool`；catalog 重启保留验证

### Batch 3 — SQL Parser
- **目标**：递归下降 SQL 解析器，覆盖 8 REQ
- **输入**：B1.types (TypeTag + 列名解析)
- **输出**：`src/tinydb/sql/` + `tests/sql/`
- **完成标准**：`pytest tests/sql --cov=src/tinydb/sql --cov-fail-under=85` 通过；至少 30 个真实 SQL 字符串端到端解析正确

### Batch 4 — B-tree Index
- **目标**：经典 B-tree（含插入/删除/分裂/合并/复合键）+ IndexManager
- **输入**：B2.heap
- **输出**：`src/tinydb/index/` + `tests/index/`
- **完成标准**：`pytest tests/index --cov=src/tinydb/index --cov-fail-under=85` 通过；连续删除 1000 键后树平衡

### Batch 5 — Query Executor
- **目标**：planner + scan/filter/project/sort/limit/aggregate + DML 写入
- **输入**：B3.parser, B4.index, B2.catalog
- **输出**：`src/tinydb/executor/` + `tests/executor/`
- **完成标准**：`pytest tests/executor --cov=src/tinydb/executor --cov-fail-under=85` 通过；planner 在有索引时选择 IndexScan 而非 SeqScan

### Batch 6 — Transactions & WAL
- **目标**：WriteLock + WAL 帧 + 事务管理 + 约束 + 隔离 + 恢复 + checkpoint
- **输入**：B2 (PAGER), B5 (DML ops)
- **输出**：`src/tinydb/tx/` + `tests/tx/`
- **完成标准**：`pytest tests/tx --cov=src/tinydb/tx --cov-fail-under=85` 通过；`tests/tx/test_recovery.py` 模糊测试 100 序列全绿；崩溃恢复断言数据一致

### Batch 7 — Public API
- **目标**：`Database.open / execute / close` + 端到端 SQL 集成
- **输入**：B5, B6
- **输出**：`src/tinydb/api.py` + `tests/integration/test_e2e.py`
- **完成标准**：`pytest tests/integration --cov=src/tinydb --cov-fail-under=80` 通过；20+ 真实 SQL 跨能力场景绿

### Batch 8 — CLI
- **目标**：argparse + 表格输出 + REPL + 元命令 + `__main__`
- **输入**：B7
- **输出**：`src/tinydb/cli/` + `tests/cli/`
- **完成标准**：`pytest tests/cli --cov=src/tinydb/cli --cov-fail-under=80` 通过；`python -m tinydb test.db -c "SELECT 1"` 退出码 0

### Batch 9 — Polish & Release Prep
- **目标**：README + `examples/demo.py` + 全量覆盖率 + 范围审计
- **输入**：B8
- **输出**：`README.md` + `examples/demo.py`
- **完成标准**：全量 `pytest --cov=src/tinydb --cov-fail-under=80` 通过；`examples/demo.py` 跑通；`git grep` 范围审计无未批准项

## Test Obligations

- **必须先从失败测试开始的行为**：
  - 每个 task 的 TDD phase 1（RED）必须先运行 `pytest -x` 看到失败，再开始实现
  - 严禁"先写实现再补测试"
  - 每个 batch 末尾必须运行该 batch 的全量测试 + 覆盖率门禁
- **必需的边界情况**（每个 spec REQ 的 Scenario 必须全部覆盖）：
  - SQL: 大小写关键字、Unicode 标识符、转义引号、空字符串字面量、`IS NULL` 优先级
  - 存储: 文件截断恢复、并发打开同一文件、空文件首次打开
  - B-tree: 连续删除到根、最左/最右键删除、阶数边界、空索引
  - 事务: 嵌套 BEGIN 拒绝、ROLLBACK 后 SELECT 看不到、崩溃在 COMMIT 前/后、checkpoint 后旧 WAL 截断
  - 类型: 浮点精度、DECIMAL 标度溢出、BLOB 跨页、JSON 非法拒绝
  - CLI: stdin EOF、Unicode 输出、宽列自动调整
- **回归敏感区域**（修改时必跑全量）：
  - `tests/tx/test_recovery.py`（崩溃恢复）
  - `tests/integration/test_e2e.py`（端到端 SQL）
  - `tests/index/test_btree.py`（B-tree 重平衡）

## Execution Mode

- **模式**：`Batch Inline`
- **选择理由**：
  - 9 个 batch 跨多个能力域，必须分批审查与 checkpoint
  - 同一会话内可顺序执行（不外派 subagent），保留可观察性
  - 遇阻时按 DP-5 转 `bug-investigator` 后回 `build-executor`
  - 任何 batch 的失败必须先修复后进下一 batch

## Verification Dimensions

| 维度 | 状态 | 发现 |
|------|------|------|
| Completeness | Pending | — |
| Correctness | Pending | — |
| Coherence | Pending | — |

**总体结论**：Pending（待实施后由 code-reviewer 填入）

## Review Gates

- **强制审查点**：
  - 每 batch 完成后调用 **code-reviewer** 检查代码质量 + spec 合规
  - B6 完成后额外调用 **security-reviewer** 检查 WAL/恢复路径
  - B7 完成后调用 **code-reviewer** 做端到端 cross-capability 审查
- **阻塞类别**（发现即停）：
  - 引入 `proposal.md > Out` 范围外的特性（JOIN/外键/并发/网络）
  - 引入未批准的运行时依赖
  - 覆盖率 < 80% 强行合入
  - ACID 任何一项失败（原子性 / 一致性 / 隔离性 / 持久性）
  - 范围审计 grep 命中未说明项

## Escalation Rules

- **何时回退到 `specifying`**：
  - `proposal.md` 范围变更（In/Out 调整）
  - `specs/` 新增/删除/变更 REQ（即使 Scenario 调整）
  - `design.md` 决策与已批准冲突
- **何时回退到 `bridging`**：
  - `tasks.md` 批次结构实质性变化（> 25% 任务重排）
  - 新增能力或 capability 划分变化
  - 本合同与 `proposal.md` / `specs/` / `design.md` / `tasks.md` 出现不一致
- **何时不得继续实现**：
  - 同一 task 的 TDD RED 阶段看不到失败（被 mock 欺骗）
  - 模糊测试发现数据不一致
  - 用户明确喊停
  - Bug-investigator 升级 ≥ 3 次仍未通过同项

## Stale Contract Detection Triggers

- `proposal.md` 中 In/Out 调整
- `specs/` 中 REQ 数量变化 ± 1
- `design.md` 决策数变化（新增/删除）
- `tasks.md` 任务数变化 ± 10%
- 实施过程中发现 REQ 不可达（如约束组合冲突）
