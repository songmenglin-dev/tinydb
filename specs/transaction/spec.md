# Spec: 事务管理

## ADDED Requirements

### REQ-TRX-1: 事务控制语句
The system MUST 支持 `BEGIN`, `COMMIT`, `ROLLBACK` 三种事务控制语句。

#### Scenario: 显式事务
- WHEN 调用方在 `db.execute("BEGIN")` 与 `db.execute("COMMIT")` 之间执行 DML
- THEN 所有 DML 在 COMMIT 时一起落盘
- AND COMMIT 前对其他事务不可见 (按隔离级别)

#### Scenario: ROLLBACK 回滚
- WHEN 在 `BEGIN` 后调用 `db.execute("ROLLBACK")`
- THEN 该事务内所有 DML 撤销
- AND 数据库状态与 BEGIN 前一致

#### Scenario: 嵌套事务
- WHEN 在已有事务内再次 `BEGIN`
- THEN 抛出错误或忽略 (按实现选择，需文档化)

### REQ-TRX-2: 原子性 (Atomicity)
The system MUST 保证事务的 DML 操作要么全部生效，要么全部不生效。

#### Scenario: COMMIT 全部生效
- WHEN 事务内执行 INSERT / UPDATE / DELETE 后 COMMIT
- THEN 所有修改持久化

#### Scenario: ROLLBACK 全部撤销
- WHEN 事务内执行 INSERT / UPDATE / DELETE 后 ROLLBACK
- THEN 所有修改撤销

#### Scenario: 崩溃时撤销
- WHEN 进程在 COMMIT 之前崩溃
- THEN 启动恢复时该事务的所有修改撤销

### REQ-TRX-3: 一致性 (Consistency)
The system MUST 在事务提交时检查所有约束 (PRIMARY KEY、UNIQUE、NOT NULL、类型)，违反则事务回滚。

#### Scenario: 违反 UNIQUE
- WHEN 事务内插入重复 UNIQUE 键
- THEN 事务回滚
- AND 抛出 `ConstraintViolation`

#### Scenario: 违反 NOT NULL
- WHEN 事务内插入 NULL 到 NOT NULL 列
- THEN 事务回滚
- AND 抛出错误

### REQ-TRX-4: 隔离性 (Isolation)
The system MUST 提供至少 `READ COMMITTED` 隔离级别（基于单进程/单连接模型下，未提交事务的修改对其他事务不可见）。

#### Scenario: 未提交不可见
- WHEN 事务 T1 未 COMMIT
- THEN 事务 T2 的 SELECT 看不到 T1 的修改

#### Scenario: 提交后可见
- WHEN 事务 T1 COMMIT
- THEN 事务 T2 之后启动的 SELECT 看到 T1 的修改

#### Scenario: 单写者约束
- WHEN 数据库在同一进程内
- THEN 仅允许一个活动写入事务（write lock semantics，文档化）

### REQ-TRX-5: 持久性 (Durability)
The system MUST 保证一旦事务 COMMIT，其修改在系统崩溃后依然存在。

#### Scenario: COMMIT 后崩溃恢复
- WHEN 进程在 COMMIT 之后崩溃
- THEN 启动时重做日志，所有已 COMMIT 事务的修改恢复

#### Scenario: COMMIT 前崩溃恢复
- WHEN 进程在 COMMIT 之前崩溃
- THEN 启动时回滚该事务，所有未提交修改不出现

### REQ-TRX-6: Write-Ahead Log (WAL)
The system MUST 在修改数据页前先将该修改以日志形式写入 WAL 文件。

#### Scenario: WAL 先于数据页
- WHEN 事务修改堆或索引
- THEN 系统先写 WAL 记录并 fsync
- AND 然后修改数据页

#### Scenario: WAL 文件结构
- WHEN 检查 WAL 文件
- THEN 文件由定长帧 (frame) 组成，每帧含日志序列号 (LSN) 与日志记录

### REQ-TRX-7: 崩溃恢复
The system MUST 在启动时通过 WAL 完成 redo / undo，恢复到一致状态。

#### Scenario: REDO 阶段
- WHEN 启动时发现 WAL 中存在已 COMMIT 事务的日志
- THEN 系统重做 (REDO) 这些修改到数据页

#### Scenario: UNDO 阶段
- WHEN 启动时发现 WAL 中存在未 COMMIT 事务的日志
- THEN 系统撤销 (UNDO) 这些修改

#### Scenario: Checkpoint
- WHEN 系统周期性执行 CHECKPOINT
- THEN 已刷盘数据页对应的旧 WAL 可截断
