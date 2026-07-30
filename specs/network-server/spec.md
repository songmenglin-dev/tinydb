# network-server

## Requirements

### REQ-SRV-1: 启动守护进程
The system MUST 提供 `tinydb-server` 命令行入口，参数 `--host`/`-H`（默认 `127.0.0.1`）、`--port`/`-p`（默认 `8520`，范围 `1..65535`）、`--db-path`（必填，待服务的 .db 文件）、`--max-conns`（默认 `64`）、`--idle-timeout`（秒，默认 `1800`），启动后打印 `[server] listening on <host>:<port>` 并进入事件循环。

#### Scenario: 默认启动
- WHEN 执行 `tinydb-server --db-path /tmp/test.db`
- THEN 进程监听 `127.0.0.1:8520`，stdout 输出 `[server] listening on 127.0.0.1:8520`
- AND 返回 exit code `0`

#### Scenario: 自定义 host:port
- WHEN 执行 `tinydb-server -H 0.0.0.0 -p 9527 --db-path /tmp/test.db`
- THEN 进程监听 `0.0.0.0:9527`

#### Scenario: 端口冲突
- WHEN 端口已被占用
- THEN 进程在 1s 内退出，stderr 输出 `[server] bind error: address already in use`
- AND 返回 exit code `2`

### REQ-SRV-2: 接受 TCP 连接并隔离会话
The system MUST 在每条新 TCP 连接到达时创建独立 `ServerSession`，并与其他会话**异常隔离**——任一会话抛错不得中断其他会话或 server 主循环。

#### Scenario: 多客户端并发
- WHEN 同时建立 10 条 TCP 连接并各发 1 条 SELECT
- THEN 10 条连接都收到独立响应
- AND 1 条连接抛错不影响其余 9 条

#### Scenario: 连接数上限
- WHEN 当前活动连接数达到 `max_conns`
- THEN 第 `max_conns+1` 条 TCP 连接被立即关闭
- AND 客户端 `Connection reset by peer`

#### Scenario: 客户端未发 HELLO
- WHEN TCP 连接建立后 5s 内未发送任何字节
- THEN server 关闭连接
- AND 客户端收到 `Connection reset by peer`

### REQ-SRV-3: 复用 v0.2 Database 全栈
The system MUST 复用 v0.2 的 `tinydb.api.Database` 执行 SQL 语句，不得引入并行 SQL 解析/执行路径；服务端仅做协议编解码 + Database 调用。

#### Scenario: SELECT 走 v0.2 路径
- WHEN 客户端发 `SELECT * FROM t`
- THEN server 调用 `Database.execute("SELECT * FROM t")`
- AND 结果集按 wire protocol 返回

#### Scenario: 写入并发互斥
- WHEN 连接 A 发 `INSERT`、连接 B 发 `UPDATE`
- THEN 通过 v0.2 RWLock 串行化
- AND 不出现 v0.1 已修复的 WAL 追加竞态

### REQ-SRV-4: PING/PONG 心跳
The system MUST 在连接空闲（无新帧）超过 `heartbeat_interval`（默认 `30s`）时主动发 `PONG`；收到 `PING` 立即回 `PONG`；连续 `heartbeat_misses`（默认 `3`）次未收到 `PONG` 则关闭连接。

#### Scenario: 空闲 PONG
- GIVEN 连接已建且 30s 无新数据
- WHEN 心跳定时器触发
- THEN server 发 `PONG` 帧
- AND 客户端在 1s 内收到

#### Scenario: 客户端 PING
- WHEN 客户端发 `PING`
- THEN server 立即回 `PONG`
- AND round-trip `<5ms`（loopback）

#### Scenario: 死亡连接清理
- GIVEN 连接建立时 `heartbeat_misses=3`、`heartbeat_interval=1s`
- WHEN 客户端进程被 kill -9
- THEN server 在 3s 内关闭该 socket 释放 fd
- AND 活动连接数减 1

### REQ-SRV-5: 优雅关闭
The system MUST 收到 `SIGINT` / `SIGTERM` 时停止接受新连接、等待活跃连接完成当前命令（最多 `30s`）、然后关闭全部 socket 并 flush WAL。

#### Scenario: SIGINT 优雅关闭
- WHEN 进程收到 `SIGINT` 且有 2 个活跃连接各发 1 条查询
- THEN 等待两条查询完成后关闭 socket
- AND stdout 输出 `[server] shutdown complete`
- AND 返回 exit code `0`

#### Scenario: 强制关闭
- WHEN 活跃连接在 30s 内未完成
- THEN server 强制关闭 socket
- AND 返回 exit code `0`（强制关闭视为 graceful）

### REQ-SRV-6: TCP keepalive 与 socket 选项
The system MUST 在每个 accepted socket 上设置 `SO_KEEPALIVE=1`、`TCP_NODELAY=1`、接收缓冲区 `65536`、发送缓冲区 `65536`。

#### Scenario: TCP_NODELAY 验证
- WHEN 客户端发小包查询（<1400 字节）
- THEN 客户端收到响应前不必等待 Nagle 延迟
- AND round-trip `<1ms`（loopback）

### REQ-SRV-7: 服务端日志
The system MUST 输出结构化日志到 stdout，每行 `[server] <ISO8601> <LEVEL> <message>`，日志级别 `INFO`（启动/连接/断开/心跳丢失）/ `WARN`（协议异常）/ `ERROR`（不可恢复）。

#### Scenario: 连接日志
- WHEN 新连接建立
- THEN stdout 输出 `[server] 2026-07-30T15:00:00Z INFO conn=<id> opened from <ip>:<port>`

#### Scenario: 错误日志
- WHEN 客户端发非法帧
- THEN stdout 输出 `[server] ... WARN conn=<id> protocol error: ...`
- AND 连接被关闭
