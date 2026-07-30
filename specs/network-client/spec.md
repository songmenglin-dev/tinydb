# network-client

## Requirements

### REQ-CLI-1: 同步 Client 构造
The system MUST 提供 `tinydb.client.Client(host, port, *, database=None, connect_timeout=5.0, heartbeat=True)`，构造时同步建立 TCP 连接并完成 HELLO 握手。

#### Scenario: 构造成功
- WHEN `Client("127.0.0.1", 8520)`
- THEN TCP 连接建立 + HELLO 握手完成
- AND `client.server_version == "tinydb-0.3.0"`

#### Scenario: 连接失败
- WHEN 目标端口未监听
- THEN `Client(...)` 抛出 `tinydb.client.ConnectionError`（继承 `tinydb.errors.TinyDBError`）
- AND 错误消息含目标 `host:port`

#### Scenario: 超时
- GIVEN `connect_timeout=0.5`
- WHEN 目标 IP 不可达
- THEN `Client(...)` 在 `0.5s` 后抛 `ConnectionError`
- AND 错误消息含 `timeout`

### REQ-CLI-2: 同步 execute 方法
The system MUST 提供 `client.execute(sql, params=None, *, timeout=30.0) -> Result`；`Result` 含属性 `rows`（list[list]）、`rowcount`（int）、`last_insert_id`（int|None）、`columns`（list[str]）。

#### Scenario: SELECT
- WHEN 执行 `SELECT id, name FROM users WHERE id = ?` 参数 `[1]`
- THEN 返回 `Result(rows=[[1,"Alice"]], rowcount=1, columns=["id","name"])`

#### Scenario: INSERT
- WHEN 执行 `INSERT INTO users VALUES (?, ?)` 参数 `["Bob", 30]`
- THEN 返回 `Result(rowcount=1, last_insert_id=<自增 id>)`
- AND `rows == []`

#### Scenario: 超时
- GIVEN server 卡住不响应（mock）
- WHEN 执行 execute `timeout=0.5`
- THEN 抛出 `tinydb.client.TimeoutError`
- AND 错误消息含 `timeout`

### REQ-CLI-3: 异步 AsyncClient
The system MUST 提供 `tinydb.client.AsyncClient` 异步版本，方法 `await client.execute(sql, params=None)` / `await client.execute_many(sql, params_list)`；使用 asyncio TCP（`asyncio.open_connection`）+ 自实现协议编解码。

#### Scenario: 异步 SELECT
- WHEN `await client.execute("SELECT 1")`
- THEN 返回 `Result(rows=[[1]], rowcount=1)`
- AND 不阻塞事件循环

#### Scenario: 并发多个查询
- WHEN `asyncio.gather` 调度 50 个 execute
- THEN 50 个查询全部成功
- AND 总耗时 `<2s`（loopback）

### REQ-CLI-4: execute_many 批量
The system MUST 提供 `client.execute_many(sql, params_list, *, batch_size=100) -> int`；返回总影响行数；底层分批 EXEC。

#### Scenario: 批量插入
- WHEN `execute_many("INSERT INTO t VALUES (?,?)", [[1,"a"],[2,"b"],...100 行])`
- THEN 返回 `100`
- AND server 收到 1 个批大小为 100 的 EXEC 或多个小批

#### Scenario: 失败回滚
- GIVEN 第二批含主键冲突
- WHEN `execute_many` 触发
- THEN 整个批量回滚
- AND 抛出 `tinydb.client.IntegrityError`

### REQ-CLI-5: transaction 上下文
The system MUST 提供 `client.transaction()` 返回上下文管理器；进入时发 `BEGIN`（等价于 EXEC `"BEGIN"`），退出 `with` 块时若无异常发 `COMMIT`，否则发 `ROLLBACK`。

#### Scenario: 提交
- WHEN `with client.transaction(): client.execute("INSERT ...")`
- THEN 自动 COMMIT，row 可见于下一条独立查询

#### Scenario: 回滚
- WHEN `with client.transaction(): raise RuntimeError()`
- THEN 自动 ROLLBACK，row 不可见

#### Scenario: 嵌套事务
- WHEN 内层 `with client.transaction():` 在外层 `with` 中触发
- THEN 抛出 `ProtocolError("nested transaction not supported")`

### REQ-CLI-6: 自动重连
The system MUST 在连接被对端关闭或心跳丢失时，按指数退避（100ms→200ms→400ms→800ms→1600ms，最多 5 次）自动重连并重发未确认命令；最终失败抛出 `ConnectionError`。

#### Scenario: 重连成功
- GIVEN server 重启
- WHEN 客户端执行 execute 触发重连
- THEN 5 次以内重连成功
- AND execute 返回正确结果

#### Scenario: 重连耗尽
- GIVEN server 永久下线
- WHEN 客户端 execute 触发重连
- THEN 5 次后抛 `ConnectionError("max retries exceeded")`
- AND 总耗时 `<3.5s`

### REQ-CLI-7: PING 健康检查
The system MUST 提供 `client.ping() -> float` 返回 RTT（秒）；连接健康时 RTT `<5ms`（loopback）；不健康时抛 `ConnectionError`。

#### Scenario: PING 成功
- WHEN `client.ping()`
- THEN 返回 `0.0012`（loopback）
- AND 类型 `float`

#### Scenario: PING 失败
- WHEN server 已关
- THEN `client.ping()` 抛 `ConnectionError`

### REQ-CLI-8: 优雅关闭
The system MUST 在 `client.close()` 时发 QUIT 并关闭 socket；多次调用 `close()` 安全（幂等）。

#### Scenario: close
- WHEN `client.close()`
- THEN server 收到 QUIT 帧并回 OK
- AND 客户端 socket 关闭
- AND 第二次 `close()` 不抛错

### REQ-CLI-9: 同步连接池
The system MUST 提供 `tinydb.client.Pool(host, port, *, size=4)`，实现简单连接池；`with pool.acquire() as client:` 取连接，`pool.acquire().execute(...)` 用完自动归还。

#### Scenario: 池获取/归还
- WHEN `pool.size=4` 且并发 4 个任务各 `pool.acquire()`
- THEN 4 个连接全部成功
- AND 第 5 个 `pool.acquire(timeout=0.5)` 抛 `TimeoutError`（池耗尽）

#### Scenario: 归还后复用
- WHEN `with pool.acquire() as c:` 退出块
- THEN 连接归还池
- AND 下一个 `pool.acquire()` 命中归还的连接（无需新建 TCP）
