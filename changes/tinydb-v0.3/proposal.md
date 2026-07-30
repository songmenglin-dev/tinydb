# Proposal: tinydb-v0.3

## Why

tinydb v0.2 已交付嵌入式 RDB + 多表 JOIN + 单进程多事务并发 + 多行 CLI（1003 测试，88.75% 覆盖率，12 批次 38 任务），但其 `proposal.md > Out` 显式排除了客户端-服务器网络模式、跨进程协议以及 Java 生态接入。用户场景调研显示三类痛点：（1）需要让业务应用（Java/Spring/其他语言栈）以成熟驱动（JDBC）连接 tinydb，否则必须为 Python 进程内嵌启动付出成本；（2）多进程/多机部署时希望像 MySQL/PG/GaussDB 一样提供独立 `tinydb-server` 守护进程接收远程连接；（3）CLI 目前只能连本地文件，无法连远端 tinydb 实例。需要 v0.3 在不破坏 v0.1/v0.2 兼容性的前提下，补齐 **C/S 网络架构 + 客户端-服务端协议 + CLI 双模式 + 兼容 JDBC 的 Java JAR** 这四条能力，使业务系统能用标准 JDBC URL 直接连接 tinydb，与 MySQL/PG/GaussDB 的接入路径完全一致。

## What Changes

扩展 tinydb v0.2 为 v0.3，新增四项能力：

1. **C/S 网络架构**：新增独立的 `tinydb-server` 守护进程（基于 `asyncio` 的 TCP server），复用 v0.2 的 `Database`/`Transaction`/`Executor` 全栈；新增 Python 端 `tinydb.client.Client` 客户端库（同步 + 异步两套 API），通过 TCP 长连接与 server 通信；server 端实现连接级读写互斥、语句级事务隔离、阻塞式 SQL 执行与流式结果返回。
2. **客户端-服务端协议**：定义 **文本 + 长度帧** 双层 wire protocol（类 MySQL/PG wire 风格），上层 SQL 命令为 UTF-8 文本行，下层二进制 payload（参数、结果集行、错误结构）用 4 字节大端长度前缀；新增握手帧（HELLO/OK/ERR）、认证握手占位（v0.3 阶段为 no-op，向 v0.4 真实鉴权过渡）、QUERY/EXEC 帧、RESULT_HEADER / RESULT_ROW / RESULT_DONE / RESULT_ERROR 帧、STATEMENT_PREPARE/EXECUTE/CLOSE 占位（v0.4+ 启用）、PING/QUIT 心跳与优雅关闭。
3. **CLI 重构支持 C/S 模式**：v0.2 的 `tinydb.cli.repl` 重构为 `mode` 双模式（embedded 走 `Database`，remote 走 `tinydb.client.Client`）；新增命令行参数 `tinydb --uri <tinydb://host:port/db> ...` 与 `tinydb --file <path> ...` 互斥；新增 `.connect <uri>` / `.disconnect` / `.status` 元命令；保留 v0.2 全部元命令与多行编辑/语法高亮/历史/`.explain`/表格化结果。
4. **兼容 JDBC 的 Java JAR**：新增独立的 `jdbc/` 子项目（Maven 构建，JDK 8+ / JDBC 4.2 baseline），提供 `org.tinydb.jdbc.TinyDriver` + `Connection` + `Statement` + `PreparedStatement` + `ResultSet` + `DatabaseMetaData` 最小子集；通过 TCP socket 直接对接 `tinydb-server`，按 wire protocol 编解码；附带 Java 单元测试（JUnit 5）与端到端集成测试（启动 server，JDBC 走完整 SELECT/INSERT/UPDATE/DELETE/事务）。

强约束（来自 `dp_0_decisions`）：
- Python 端：**零运行时外部依赖**（asyncio/threading/socket 均为 stdlib；CLI 仍可选 `prompt_toolkit`）
- Java 端：**JDK 8+ / JDBC 4.2 baseline**，零额外依赖（仅 `junit-jupiter` 测试依赖）
- 单 `.db` 文件后端**完全复用 v0.2**，不引入新存储格式
- wire protocol **透传 SQL 字符串**，保持 v0.1/v0.2 SQL 语法兼容
- 覆盖率门禁：**Python ≥80% + Java ≥70%**（JDBC 端合理范围）
- 完成时**必须 spec-merge** + **必须 push 到 origin**

## Scope

### In

- 网络服务：`tinydb-server` 子命令启动 asyncio TCP server，监听 `host:port`，每连接一个 `ServerSession`，复用 `tinydb.api.Database` 实例
- 网络服务：连接接受、`HELLO` 握手（无认证）、命令循环、异常隔离、单写者多读者（继承 v0.2 RWLock）
- 网络服务：`PING` 心跳（30s 空闲自动回 `PONG`），`QUIT` 优雅关闭，TCP `SO_KEEPALIVE`，最大并发连接数（默认 64，可配置）
- Python 客户端：`tinydb.client.Client(host, port, ...)` 同步 API；`tinydb.client.AsyncClient` 异步 API；自动重连（指数退避 100ms→2s，最多 5 次）+ `PING` 健康检查
- Python 客户端：方法 `execute(sql, params=None)` 返回 `Result`（rows/rowcount/last_insert_id）；`execute_many` 批量；`transaction()` 上下文管理器（commit/rollback）
- 协议：`tinydb/protocol/` 子包，含 `frame.py`（编解码）、`messages.py`（消息类）、`errors.py`（SQLSTATE → ErrorCode 映射）、`handshake.py`、`command.py`、`result.py`
- 协议帧：长度前缀 4 字节大端，类型 1 字节，标志 1 字节，载荷；`[len|type|flags|payload...]`
- 协议消息：`HELLO` / `OK` / `ERR` / `QUERY` / `EXEC` / `RESULT_HEADER` / `RESULT_ROW` / `RESULT_DONE` / `RESULT_ERROR` / `PING` / `PONG` / `QUIT`
- 错误模型：服务端错误码对齐 SQLSTATE 子集（`08000` 连接异常、`22000` 数据异常、`42000` 语法错误、`25000` 事务状态非法、`HY000` 通用）
- CLI 双模式：`tinydb/cli/app.py` 重构为 `mode={"embedded","remote"}`；`--file PATH` 显式 embedded，`--uri URI` 显式 remote；启动时按模式选择后端；远程模式下 SQL 与元命令经由 `Client.execute()` 派发
- CLI 元命令扩展：`.connect <uri>` / `.disconnect` / `.status` / `.server-info` / `.quit`；保留 `.tables` / `.schema` / `.explain` / `.history` / `.help`
- JDBC 驱动：Java Maven 项目，目录 `jdbc/`（与 `src/` 平级，spec-superflow 视为新模块）
- JDBC：`org.tinydb.jdbc.TinyDriver` 实现 `java.sql.Driver`，URL 形式 `jdbc:tinydb://host:port/database`（database 可选，兼容 `jdbc:tinydb://host:port/`）
- JDBC：`TinyConnection`（autoCommit/commit/rollback/close/isValid/setCatalog）、`TinyStatement`（executeQuery/executeUpdate/execute/getResultSet/getUpdateCount/close）、`TinyPreparedStatement`（占位符 `?` + 参数绑定（字符串/整数，v0.4 扩展类型））、`TinyResultSet`（next/getString/getLong/getInt/getDouble/getBoolean/getObject/isNull/wasNull）、`TinyDatabaseMetaData`（getURL/getUserName/getDatabaseProductName/version/tables 元数据最小集）
- JDBC 单元测试：JUnit 5，覆盖每条公共方法；端到端集成测试通过 `ProcessBuilder` 启动 `tinydb-server`，跑完整 CRUD + 事务
- 端到端：跨语言端到端测试 Python client ↔ Python server、Java JDBC ↔ Python server，验证 wire protocol 互操作
- 兼容：v0.1/v0.2 公共 API 与 SQL 语法 **100% 不变**；CLI 既有命令行参数全部保留

### Out

- TLS / SSL 加密传输
- 用户认证 / 权限系统 / 角色（HELLO 阶段显式 no-op 留 v0.4）
- 集群 / 主备复制 / 分布式事务 / Raft
- prepared statement cache / 结果集缓存 / 查询计划缓存
- 复杂类型扩展（JSON 列类型、数组、向量）
- GUI / Web 管理控制台
- MySQL/PG 协议兼容层（仅 tinydb 原生协议）
- IPv6 / Unix Domain Socket（v0.3 仅 IPv4 TCP，留 v0.4）
- 二进制 BLOB 类型（占位但暂不实现）
- 异步执行 / 游标服务化（server 端单线程 asyncio，连接级串行）

## Impact

- 受影响模块（Python 端）：
  - `src/tinydb/cli/app.py`（重构 mode + 双模式启动）
  - `src/tinydb/cli/repl.py`（嵌入 `Client` 适配器）
  - `src/tinydb/cli/commands.py`（`.connect`/`.disconnect`/`.status`/`.server-info`）
  - `src/tinydb/api.py`（暴露内部钩子供 server 复用）
  - `src/tinydb/executor/dispatch.py`（允许非嵌入式入口，薄包装）
- 新增模块（Python 端）：
  - `src/tinydb/server/__init__.py`（daemon 入口）
  - `src/tinydb/server/app.py`（asyncio TCP server）
  - `src/tinydb/server/session.py`（每连接 Session）
  - `src/tinydb/server/handler.py`（命令分发到 `Database.execute`）
  - `src/tinydb/server/config.py`（host/port/max_conns/timeout）
  - `src/tinydb/client/__init__.py`
  - `src/tinydb/client/sync.py`（同步 Client）
  - `src/tinydb/client/async_client.py`（async Client）
  - `src/tinydb/client/pool.py`（同步连接池，最小实现）
  - `src/tinydb/protocol/__init__.py`
  - `src/tinydb/protocol/frame.py`
  - `src/tinydb/protocol/messages.py`
  - `src/tinydb/protocol/codec.py`
  - `src/tinydb/protocol/errors.py`
  - `src/tinydb/protocol/handshake.py`
- 新增模块（Java 端，平级于 `src/`）：
  - `jdbc/pom.xml`
  - `jdbc/src/main/java/org/tinydb/jdbc/TinyDriver.java`
  - `jdbc/src/main/java/org/tinydb/jdbc/TinyConnection.java`
  - `jdbc/src/main/java/org/tinydb/jdbc/TinyStatement.java`
  - `jdbc/src/main/java/org/tinydb/jdbc/TinyPreparedStatement.java`
  - `jdbc/src/main/java/org/tinydb/jdbc/TinyResultSet.java`
  - `jdbc/src/main/java/org/tinydb/jdbc/TinyDatabaseMetaData.java`
  - `jdbc/src/main/java/org/tinydb/jdbc/TinyTypes.java`
  - `jdbc/src/main/java/org/tinydb/jdbc/protocol/{Frame,Message,Codec,ErrorCode}.java`
  - `jdbc/src/test/java/org/tinydb/jdbc/{TinyDriverTest,TinyConnectionTest,TinyStatementTest,TinyPreparedStatementTest,TinyResultSetTest,EndToEndTest}.java`
- 新增可选依赖：Java 端 `junit-jupiter:5.10.0`（test scope）；Python 端 **零新增运行时依赖**
- 测试影响：v0.2 的 1003 测试必须 100% 通过；新增 Python 测试预计 +250（网络协议 ~80、server ~60、client ~70、CLI 双模式 ~40），Java 测试预计 +60（unit ~40、e2e ~20）
- 公共 API：
  - Python 新增：`tinydb.server.run_server`、`tinydb.client.Client`、`tinydb.client.AsyncClient`、`tinydb.protocol.*`
  - v0.1/v0.2 所有公共 API **100% 向后兼容**
- CLI：保留 v0.2 全部命令行参数；新增 `--host` / `--port` / `--uri` / `--file`
- 文档：`docs/NETWORK.md`、`docs/JDBC.md`、`docs/CLI_USAGE.md` 扩展
- 性能预算：单 server 单连接 P95 `<5ms`（不含 SQL 执行时间）；wire protocol round-trip `<1ms`（loopback）；Java JDBC round-trip `<3ms`（loopback）

## Capabilities

| 能力 | 描述 |
|------|------|
| tinydb-server 守护进程 | asyncio TCP server，监听 host:port，复用 v0.2 Database 全栈 |
| Python 同步/异步 Client | 同步 `Client` + 异步 `AsyncClient`，方法 execute/execute_many/transaction/PING |
| Wire Protocol | 文本+长度帧双层，SQL 透传，结果集流式返回 |
| 协议握手与心跳 | HELLO 握手（no-op 认证占位）、PING/PONG 心跳、QUIT 优雅关闭 |
| 错误模型 | 服务端错误码对齐 SQLSTATE 子集（5 类），含消息体与堆栈定位 |
| CLI 双模式 | embedded 走 Database，remote 走 Client；按 `--file` / `--uri` 自动选择 |
| CLI 远程元命令 | `.connect <uri>` / `.disconnect` / `.status` / `.server-info` |
| JDBC Driver | Java Type-4 驱动，JDBC 4.2 baseline，URL `jdbc:tinydb://host:port/` |
| JDBC 最小子集 | Connection/Statement/PreparedStatement/ResultSet/DatabaseMetaData + commit/rollback/setAutoCommit |
| 端到端互操作 | Python client ↔ Python server、Java JDBC ↔ Python server 双向验证 |