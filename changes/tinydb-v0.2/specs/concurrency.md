# Spec: 并发控制（v0.2）

## ADDED Requirements

### REQ-CONC-1: 读写锁（进程内）
The system MUST 在 `Database` 实例上提供 `RWLock`，允许多个读事务并发，但写事务独占。

#### Scenario: 多读并发
- GIVEN Database 单实例
- WHEN 启动 4 个并发读事务（`tx = db.begin(); db.execute(SELECT...)`）
- THEN 4 个事务均可并发推进，无阻塞
- AND 总耗时接近单事务 × 1.0（无锁开销放大）

#### Scenario: 写互斥
- GIVEN 一个活跃写事务
- WHEN 第二个线程尝试 `db.begin()` 启动写事务
- THEN 第二个 `begin()` 阻塞直至第一个写事务 COMMIT 或 ROLLBACK
- AND 不抛错

#### Scenario: 读写互斥
- GIVEN 一个活跃写事务
- WHEN 另一个线程调用 `db.execute(SELECT)`
- THEN `execute` 阻塞直至写事务结束
- AND 返回结果为写事务提交后的最新数据

### REQ-CONC-2: 跨进程文件锁（fcntl）
The system MUST 通过 `fcntl.flock` 在 WAL 追加期间持有排他文件锁，防止多进程同时写入。

#### Scenario: 多进程互斥写
- GIVEN 同一 `.db` 文件被两个 Python 进程打开
- WHEN 进程 A 启动写事务，进程 B 同时启动写事务
- THEN B 的 WAL 写入阻塞至 A 提交或回滚
- AND 两个事务最终都成功，不出现撕裂写

#### Scenario: 跨平台降级
- WHEN 平台不支持 `fcntl.flock`（例如 Windows）
- THEN 记录警告日志并降级为 `msvcrt.locking` 或返回明确错误
- AND 不静默失败

### REQ-CONC-3: 读快照隔离（READ COMMITTED）
The system MUST 为读事务维护快照，事务内的 SELECT 看到一致的数据版本，即使其他事务并发提交也不影响。

#### Scenario: 事务内读一致性
- GIVEN 读事务 T1 已读取 5 行
- WHEN 另一个写事务 T2 提交插入新行 1 条
- THEN T1 继续读取仍只看到原始 5 行
- AND T1 COMMIT 后第二次查询能看到 T2 插入的行

#### Scenario: 写冲突回滚
- GIVEN 同一行被两个写事务同时修改
- WHEN 后提交的事务检测到行版本不匹配
- THEN 后提交事务回滚并抛出 `WriteConflictError`
- AND 前一个事务结果保持不变

### REQ-CONC-4: 隔离级别参数
The system MUST 接受 `Database(path, isolation="READ COMMITTED" | "SERIALIZABLE")`，默认 `READ COMMITTED`。

#### Scenario: 显式 SERIALIZABLE
- WHEN `Database(path, isolation="SERIALIZABLE")`
- THEN 读写锁升级为全程排他；任何事务启动时获取数据库锁
- AND 事务内 SELECT 看到的不只是行快照，而是事务开始时的全局快照

#### Scenario: 默认 READ COMMITTED
- WHEN `Database(path)` 不传 isolation
- THEN isolation="READ COMMITTED"
- AND 行为与 REQ-CONC-3 一致

### REQ-CONC-5: 缓冲池跨进程失效
The system MUST 在事务开始时检查 `.db` 文件的 mtime 与 inode，发现外部修改时丢弃受影响的缓冲页。

#### Scenario: 检测外部修改
- GIVEN 进程 A 的缓冲池缓存了 page=5
- WHEN 进程 B 写入并更新文件 mtime
- THEN 进程 A 下一事务访问 page=5 时重新从磁盘读取
- AND 不返回陈旧数据

#### Scenario: 无外部修改复用缓存
- GIVEN 进程 A 缓冲池缓存 page=5
- WHEN 进程 A 另一事务访问 page=5
- THEN 命中缓冲池，无磁盘 I/O
- AND 返回结果与上一事务一致

### REQ-CONC-6: 连接池（可选）
The system MUST 支持 `Database(pool_size=N)`，池内 N 个连接可被多线程借用/归还。

#### Scenario: 多线程借用连接
- GIVEN `Database(pool_size=4)`
- WHEN 4 个线程同时调用 `db.acquire()`
- THEN 4 个线程分别获得不同连接
- AND 第 5 个线程 `acquire()` 阻塞直至有人 `release()`

#### Scenario: 连接自动归还
- WHEN 使用 `with db.connection() as conn: ...` 上下文管理器
- THEN 退出 with 块后连接归还池
- AND 不留下泄漏

#### Scenario: 默认 pool_size=1
- WHEN `Database(path)` 不传 pool_size
- THEN 等价 v0.1 的单连接模型
- AND 现有 826 测试全部通过

### REQ-CONC-7: 死锁检测与回滚
The system MUST 在两事务循环等待对方锁时检测死锁，并回滚其中一个事务释放锁。

#### Scenario: 简单死锁回滚
- GIVEN 事务 A 持有 lock1 等待 lock2，事务 B 持有 lock2 等待 lock1
- WHEN 检测到死锁
- THEN 抛出 `DeadlockError` 给被回滚方
- AND 被回滚事务的所有修改撤销
- AND 另一事务可继续推进

### REQ-CONC-8: 并发测试覆盖
The system MUST 包含多线程与多进程并发集成测试，每个测试至少 10 次迭代验证无 race。

#### Scenario: 多线程压力测试
- GIVEN 32 线程并发执行 INSERT + SELECT
- WHEN 持续 5 秒
- THEN 无死锁、无数据竞争、无 OSEXception
- AND 总插入行数等于各线程计数之和

#### Scenario: 多进程读写测试
- GIVEN 4 个 Python 子进程，1 个写者 3 个读者
- WHEN 写者持续 INSERT，读者持续 SELECT
- THEN 读者永远不会看到半写入行
- AND 所有写入最终对读者可见

### REQ-CONC-9: 兼容 v0.1 单线程行为
The system MUST 保持 v0.1 单线程单事务行为不变，所有 826 个现有测试通过。

#### Scenario: 单线程无开销
- WHEN 单线程单事务执行 v0.1 工作负载
- THEN 与 v0.1 相比性能退化 < 5%
- AND 公共 API 100% 向后兼容