# 执行合同

> 本合同由 `proposal.md` + `specs/` + `design.md` + `tasks.md` 派生。
> 任何与源工件冲突的内容以源工件为准；发现冲突时按 Escalation Rules 处理。
> DP-3 是 hard gate，本合同由 DP-0/2 已批准 → 用户已授予全权限继续到 DP-7。

## Intent Lock

- **变更名称**：`tinydb-v0.3`
- **要解决的问题**：tinydb v0.2 显式排除客户端-服务器网络模式、跨进程协议、Java 生态接入（JDBC）；需要 v0.3 在不破坏 v0.1/v0.2 接口兼容的前提下补齐 C/S 网络架构 + 客户端-服务端协议 + CLI 双模式 + 兼容 JDBC 的 Java JAR 四条能力，使业务系统能用标准 JDBC URL `jdbc:tinydb://host:port/` 直连 tinydb，与 MySQL/PG/GaussDB 接入路径一致。
- **范围内**：
  - **网络服务**：`tinydb-server` 守护进程（asyncio TCP），参数 `--host`/`--port`/`--db-path`/`--max-conns`/`--idle-timeout`，复用 v0.2 `Database` 全栈；连接级异常隔离；PING/PONG 心跳（30s 空闲 / 3 次丢失）；SIGINT/SIGTERM 优雅关闭（30s 超时）
  - **网络服务**：HELLO 握手（no-op 认证占位，v0.4 升级）；每连接 `ServerSession` 协程 + `handler.dispatch` 调用 `Database.execute`
  - **Python 客户端**：`tinydb.client.Client`（同步）+ `tinydb.client.AsyncClient`（异步）+ `tinydb.client.Pool`；方法 `execute/execute_many/transaction/ping/close`；指数退避重连 100ms→2s（最多 5 次）
  - **Wire Protocol**：双层帧 `[LEN(4B BE)][TYPE(1B)][FLAGS(1B)][PAYLOAD]`；文本 SQL 行 + `[TYPE][LEN][VALUE]` 参数；12 个消息类（HELLO/OK/ERR/QUERY/EXEC/RESULT_HEADER/ROW/DONE/ERROR/PING/PONG/QUIT）
  - **Wire Protocol**：SQLSTATE 5 类错误（08000/22000/25000/42000/HY000）+ max_params=1024 + max_frame=16MB
  - **CLI 双模式**：`--file PATH`（embedded）/`--uri URI`（remote）互斥；URI 形式 `tinydb://[user[:pass]@]host[:port]/[db]`；运行时 `.connect <uri>`/`.disconnect`/`.status`/`.server-info`；保留 v0.2 多行编辑/语法高亮/历史/`.explain`/`.tables`/`.schema`
  - **JDBC 驱动**：Java 8+ / JDBC 4.2 / Maven；`org.tinydb.jdbc.TinyDriver` + `TinyConnection` + `TinyStatement` + `TinyPreparedStatement` + `TinyResultSet` + `TinyDatabaseMetaData`；URL `jdbc:tinydb://host:port/[database]`；JUnit 5 测试；端到端 `EndToEndTest` spawn server
  - **JDBC 异常映射**：SQLSTATE → `SQLNonTransientConnectionException`/`SQLIntegrityConstraintViolationException`/`SQLSyntaxErrorException`/`SQLDataException`/`SQLException`
  - **端到端**：Python client ↔ Python server、Java JDBC ↔ Python server 双向互操作验证
  - **spec-merge + push**：完成后 `specs/<cap>/spec.md` 合并 + `git tag tinydb-v0.3.0` + `git push origin master --tags`
- **范围外**（范围护栏，违反即触发回退到 `specifying`）：
  - TLS / SSL 加密传输
  - 用户认证 / 权限系统 / 角色（HELLO 阶段显式 no-op 留 v0.4）
  - 集群 / 主备复制 / 分布式事务 / Raft
  - prepared statement cache / 结果集缓存 / 查询计划缓存
  - 复杂类型扩展（JSON 列、数组、向量）
  - GUI / Web 管理控制台
  - MySQL / PG / ODBC 协议兼容层
  - IPv6 / Unix Domain Socket（仅 IPv4 TCP）
  - 二进制 BLOB 类型
  - 异步执行 / 游标服务化
  - Python 端 PreparedStatement 公共 API（v0.4 再补）
  - JDBC 之外的驱动形态（ODBC、.NET、Go driver 等）

## Approved Behavior

- **已批准需求摘要**：5 个 spec 文件（`network-server` / `network-client` / `wire-protocol` / `cli-cs` / `jdbc-driver`）/ **40+ 个 REQ** / 120+ Scenario，全部以 `MUST`/`SHALL` 表达
- **关键场景**（按能力挑选）：
  - `REQ-SRV-1/2/3` 默认启动 + 多客户端并发 + RWLock 串行写入
  - `REQ-SRV-4` PING/PONG 心跳 + 死亡连接 3 次丢失清理
  - `REQ-SRV-5` SIGINT 优雅关闭（活跃连接完成后 / 30s 超时）
  - `REQ-PROTO-1/2/3` 长度帧 + 12 个消息类型 + HELLO 握手（>64 字节拒绝）
  - `REQ-PROTO-4/5/6/7` QUERY 透传 + EXEC 带参数 + RESULT_HEADER/ROW/DONE 序列 + SQLSTATE 5 类
  - `REQ-CLI-1/2/3` 同步 Client 构造 + execute + AsyncClient 并发 50 查询
  - `REQ-CLI-4/5/6/7/8/9` execute_many 批量回滚 + transaction 提交/回滚 + 重连 + ping + close 幂等 + Pool acquire/release
  - `REQ-CLI-CS-1/3/5` `--file`/`--uri` 互斥 + 远程 SQL 派发 + `.status`/`.server-info`
  - `REQ-CLI-CS-4/7/8` `.connect`/`.disconnect` 动态切换 + 多行编辑保留 + 连接失败 exit code 3
  - `REQ-JDBC-1/2/3` Driver 自动注册 + TinyConnection autoCommit/commit/rollback + TinyStatement executeQuery/Update/timeout
  - `REQ-JDBC-4/5/6` TinyPreparedStatement setString/Int/Long/Double/Boolean/Null/Object + TinyResultSet 列名/列号/wasNull + TinyDatabaseMetaData getTables/getColumns
  - `REQ-JDBC-7/8/9` SQLSTATE → SQLException 子类映射 + Maven JAR <200KB + 端到端 spawn server + 完整 CRUD/事务
- **验收检查**：
  - **Python 单元测试覆盖率 ≥ 80%**（`pytest --cov=src/tinydb --cov-fail-under=80` 必须通过）
  - **Java 单元测试覆盖率 ≥ 70%**（JaCoCo `mvn verify` 通过）
  - **v0.2 全部 1003 测试 100% 通过**（向后兼容）
  - **新增测试预计 250+（Python）+ 60+（Java）**
  - **跨语言端到端**：Python client ↔ Python server、Java JDBC ↔ Python server 全部通过
  - **scope audit**：`git grep` 命中 `TLS|cert|authentication|replication|MVCC|prepared.*cache` 在 `src/tinydb/` 或 `jdbc/src/main/` 须经批准
  - **依赖审计**：Python 运行时零新增依赖；Java JAR 体积 <200KB；`junit-jupiter` 仅 test scope
  - **`tinydb-server --help` 正常输出 + `tinydb --uri tinydb://...` 远程连接成功**
  - **JDBC Hello World 跑通**（建表 + 插 1 行 + SELECT + 关闭）

## Design Constraints

- **架构约束**（来自 `design.md` 决策 D-1 ~ D-10）：
  - D-1: Wire Protocol = 文本 SQL 行 + 4 字节大端长度前缀帧（类 MySQL/PG wire），不引入 protobuf/flatbuffers
  - D-2: `tinydb-server` 单进程 asyncio（`asyncio.start_server`）+ 每连接 `ServerSession` 协程，串行处理命令；并发写互斥通过 v0.2 RWLock
  - D-3: 同步 `Client` 用 `socket` + 守护线程 + `queue.Queue`；异步 `AsyncClient` 用 `asyncio.open_connection`；共用 `tinydb.protocol` codec
  - D-4: HELLO 握手 v0.3 无认证（占位）+ OK 帧回 server 版本；v0.4 引入真实认证
  - D-5: CLI 双模式 `mode: Literal["embedded","remote"]` + `Backend` 抽象类
  - D-6: JDBC Type-4（`java.net.Socket` 直连 server）+ 纯 socket 不引入 Netty
  - D-7: JDBC PreparedStatement 复用 wire protocol `EXEC` 帧；Python 端 v0.3 不暴露 PreparedStatement API
  - D-8: SQLSTATE 5 类映射（`08000`/`22000`/`25000`/`42000`/`HY000`）
  - D-9: 协议版本号嵌入 OK 帧 `version="tinydb-0.3.0"`
  - D-10: 3 条并行轨道：wire-protocol(B1)→server(B2)+client(B3)→cli(B4)+jdbc(B5/B6)→e2e(B7)；Java 端 B5/B6 可与 Python B3/B4 部分并行
- **接口约束**（强制 API 形状，禁止改签名）：
  - **Python 新增**：
    - `tinydb.server.app.run_server(config: ServerConfig) -> None`
    - `tinydb.server.app.main() -> None`（`tinydb-server` entry point）
    - `tinydb.client.Client(host: str, port: int, *, database=None, connect_timeout=5.0, heartbeat=True)`
    - `tinydb.client.AsyncClient(host: str, port: int, ...)`
    - `tinydb.client.Pool(host: str, port: int, *, size: int = 4)`
    - `tinydb.protocol.{Frame, FrameReader, FrameWriter, Hello, Ok, Err, Query, Exec, ResultHeader, ResultRow, ResultDone, ResultError, Ping, Pong, Quit, ProtocolError}`
    - `tinydb.client.{ConnectionError, TimeoutError, IntegrityError, ProtocolError}`（继承 `tinydb.errors.TinyDBError`）
    - `tinydb.cli.{parse_uri(uri: str), Backend, EmbeddedBackend, RemoteBackend}`
  - **v0.1/v0.2 既有 API 100% 保持不变**：`tinydb.open`、`Database.execute`、`Database(path, isolation=..., pool_size=...)`、`Transaction`
  - **CLI 既有参数保留**：新增 `--uri`/`--host`/`--port` 与 `--file` 互斥
  - **Java 新增**：
    - `org.tinydb.jdbc.TinyDriver implements java.sql.Driver`
    - `org.tinydb.jdbc.TinyConnection implements java.sql.Connection`
    - `org.tinydb.jdbc.TinyStatement implements java.sql.Statement`
    - `org.tinydb.jdbc.TinyPreparedStatement extends TinyStatement implements java.sql.PreparedStatement`
    - `org.tinydb.jdbc.TinyResultSet implements java.sql.ResultSet`
    - `org.tinydb.jdbc.TinyDatabaseMetaData implements java.sql.DatabaseMetaData`
    - URL 形式 `jdbc:tinydb://[host][:port]/[database]`
- **依赖约束**：
  - **Python 运行时零新增依赖**（asyncio/threading/socket 全部 stdlib；CLI prompt_toolkit 沿用 v0.2 可选）
  - **Java 运行时零第三方依赖**（仅 JDK 8+ 标准库）
  - **Java 测试依赖**：仅 `junit-jupiter:5.10.0`（test scope）
  - **Maven 插件**：maven-surefire-plugin 3.x + JaCoCo 0.8.11（强制 ≥70% 覆盖率）
  - **pyproject.toml 新增**：`tinydb-server = "tinydb.server.app:main"`
- **数据约束**：
  - 单 `.db` 文件后端**完全复用 v0.2**，不引入新页/页格式
  - wire protocol **透传 SQL 字符串**，v0.1/v0.2 SQL 语法 100% 不变
  - max_frame_size = 16MB（`0xFFFFFF`）
  - max_params = 1024
  - max_conns 默认 64
  - heartbeat_interval 默认 30s（测试可缩到 0.1s 加速）
  - heartbeat_misses 默认 3
  - idle_timeout 默认 1800s

## Execution Plan

按 full workflow 标准流程：

1. 调用 `ssf execution recommend changes/tinydb-v0.3` 获取模式推荐（必为 `sdd`，因 7 批次 38 任务 + 跨语言 + 新模块）
2. 用户已全权授予，本合同视为确认 → 直接执行 `ssf execution plan --mode sdd --confirm ...`
3. 计划保存到 `.superpowers/sdd/execution-plan.json`
4. 按 wave 顺序执行：W1=Wire Protocol Foundation → W2=tinydb-server → W3=Python Client → W4=CLI Dual-mode → W5=JDBC Protocol → W6=JDBC Driver → W7=E2E + Merge + Push
5. 每个 wave 完成记录 `ssf execution review --wave <id> --base <sha> --head <sha> --report <path> --verdict pass|fail`

## Execution Waves

### Wave 1 — Wire Protocol Foundation (Python)

- **Wave ID**: `W1`
- **任务**：T-1.1 Frame 数据结构、T-1.2 FrameCodec、T-1.3 SQLSTATE 映射、T-1.4 Message 类族、T-1.5 Hello 握手常量
- **依赖 wave**：无
- **策略**：`parallel`（host 支持并发派发时）
- **目标**：实现 Python 端 wire protocol 完整 codec + 12 个消息类 + SQLSTATE 映射
- **输入**：`stdlib struct/io`
- **输出**：`src/tinydb/protocol/{frame,codec,messages,errors,handshake}.py` + `tests/protocol/test_*.py` 全绿
- **完成标准**：`pytest tests/protocol/ -v` 全绿；property-based 1000 次随机 roundtrip 不抛错；type-check `mypy src/tinydb/protocol` 通过
- **Review gate**：W1 完成后写 `review-W1.md`，运行 `ssf execution review --wave W1 --base <pre-sha> --head <post-sha> --report review-W1.md --verdict pass`

### Wave 2 — tinydb-server (Python asyncio)

- **Wave ID**: `W2`
- **任务**：T-2.1 ServerConfig、T-2.2 ServerSession、T-2.3 handler dispatch、T-2.4 asyncio 主循环、T-2.5 心跳、T-2.6 CLI 入口、T-2.7 pyproject entry
- **依赖 wave**：`W1`
- **策略**：`parallel`（任务间无依赖）
- **目标**：实现 `tinydb-server` 守护进程 + HELLO 握手 + 命令循环 + PING/PONG + SIGINT 优雅关闭
- **输入**：`tinydb.api.Database`、`tinydb.protocol.*`
- **输出**：`src/tinydb/server/{config,session,handler,app}.py` + `src/tinydb/server/__main__.py` + `tests/server/test_*.py`
- **完成标准**：`pytest tests/server/ -v` 全绿；手工 `tinydb-server --db-path /tmp/x.db` 可启动；HELLO + QUERY(SELECT 1) 端到端跑通
- **Review gate**：W2 完成后写 `review-W2.md`，执行 `ssf execution review --wave W2 --verdict pass`

### Wave 3 — Python Client (sync + async + pool)

- **Wave ID**: `W3`
- **任务**：T-3.1 Client 构造、T-3.2 execute+Result、T-3.3 execute_many、T-3.4 transaction、T-3.5 重连、T-3.6 ping/close、T-3.7 AsyncClient、T-3.8 Pool
- **依赖 wave**：`W1`（并行可启动；AsyncClient 独立）
- **策略**：`parallel`（sync/async/pool 三套可并行）
- **目标**：Python 同步 + 异步客户端库完整实现 + 连接池 + 指数退避重连
- **输入**：`tinydb.protocol.*`
- **输出**：`src/tinydb/client/{sync,async_client,pool,errors}.py` + `tests/client/test_*.py`
- **完成标准**：`pytest tests/client/ -v` 全绿；与 `tinydb-server` 跑端到端 SELECT/INSERT/UPDATE/DELETE/事务
- **Review gate**：W3 完成后写 `review-W3.md`，执行 `ssf execution review --wave W3 --verdict pass`

### Wave 4 — CLI Dual-Mode

- **Wave ID**: `W4`
- **任务**：T-4.1 URI 解析、T-4.2 Backend 抽象、T-4.3 CLI 启动重构、T-4.4 REPL 接受 Backend、T-4.5 .connect/.disconnect/.status/.server-info、T-4.6 连接失败错误
- **依赖 wave**：`W3`（依赖 Client 实现）
- **策略**：`parallel`（任务间无强依赖）
- **目标**：CLI 双模式启动 + 远程元命令 + 多行编辑/语法高亮保留
- **输入**：`tinydb.client.Client`、`tinydb.api.Database`
- **输出**：`src/tinydb/cli/{uri,backend}.py`（新增）；`src/tinydb/cli/{app,repl,commands}.py`（修改）
- **完成标准**：`pytest tests/cli/ -v` 全绿；手工 `tinydb --uri tinydb://127.0.0.1:8520` 远程连接成功 + SQL 执行 + `.connect` 切换
- **Review gate**：W4 完成后写 `review-W4.md`，执行 `ssf execution review --wave W4 --verdict pass`

### Wave 5 — JDBC Protocol Layer (Java，可与 W3 并行)

- **Wave ID**: `W5`
- **任务**：T-5.1 Frame + Codec、T-5.2 Messages 类族、T-5.3 SQLSTATE mapper、T-5.4 TinyTypes
- **依赖 wave**：无（独立 Java 轨道）
- **策略**：`parallel`（任务间无依赖）
- **目标**：Java 端 wire protocol 完整 codec + 消息类 + SQLSTATE mapper + JDBC Types 映射
- **输入**：JDK 8+ 标准库
- **输出**：`jdbc/src/main/java/org/tinydb/jdbc/protocol/{Frame,Codec,Messages,ErrorCode}.java` + `jdbc/src/main/java/org/tinydb/jdbc/TinyTypes.java` + `jdbc/src/main/java/org/tinydb/jdbc/TinySQLException.java`
- **完成标准**：`mvn -f jdbc/pom.xml test -Dtest=FrameTest,CodecTest,MessagesTest,ErrorCodeTest,TinyTypesTest` 全绿
- **Review gate**：W5 完成后写 `review-W5.md`，执行 `ssf execution review --wave W5 --verdict pass`

### Wave 6 — JDBC Driver 主体（Java）

- **Wave ID**: `W6`
- **任务**：T-6.1 TinyDriver 注册、T-6.2 TinyConnection、T-6.3 TinyStatement、T-6.4 TinyPreparedStatement、T-6.5 TinyResultSet、T-6.6 TinyDatabaseMetaData、T-6.7 pom.xml + JaCoCo
- **依赖 wave**：`W5`
- **策略**：`parallel`（任务间无强依赖）
- **目标**：JDBC 最小子集（Connection/Statement/PreparedStatement/ResultSet/DatabaseMetaData）+ SQLSTATE 异常映射 + Maven 配置
- **输入**：`tinydb.jdbc.protocol.*`
- **输出**：`jdbc/src/main/java/org/tinydb/jdbc/{TinyDriver,TinyConnection,TinyStatement,TinyPreparedStatement,TinyResultSet,TinyDatabaseMetaData}.java` + `jdbc/pom.xml` + `jdbc/src/main/resources/META-INF/services/java.sql.Driver`
- **完成标准**：`mvn -f jdbc/pom.xml test` 全绿；JaCoCo 覆盖率 ≥70%；`mvn package` 生成 `tinydb-jdbc-0.3.0.jar` <200KB
- **Review gate**：W6 完成后写 `review-W6.md`，执行 `ssf execution review --wave W6 --verdict pass`

### Wave 7 — E2E + Spec-Merge + Push

- **Wave ID**: `W7`
- **任务**：T-7.1 Python e2e、T-7.2 Java JDBC e2e、T-7.3 文档、T-7.4 spec-merge、T-7.5 release（commit + tag + push）
- **依赖 wave**：`W2`、`W3`、`W4`、`W5`、`W6`
- **策略**：`serial`（spec-merge 与 push 必须最后）
- **目标**：跨语言端到端验证 + spec-merge 合并到顶层 `specs/` + 打 tag + push
- **输入**：W2-W6 全部产物
- **输出**：
  - `tests/integration/test_e2e_python.py`
  - `jdbc/src/test/java/org/tinydb/jdbc/EndToEndTest.java`
  - `docs/NETWORK.md` + `docs/JDBC.md` + `README.md` 更新
  - 顶层 `specs/` reorganize（5 个新 cap + 已有 cap 完整）
  - git tag `tinydb-v0.3.0` + push origin master --tags
- **完成标准**：
  - `pytest tests/integration -m network -v` 全绿
  - `mvn -f jdbc/pom.xml test -Dtest=EndToEndTest` 全绿
  - 文档可读且示例可运行
  - `tree specs/` 显示 v0.1+v0.2+v0.3 完整 cap 树
  - `git ls-remote --tags origin | grep v0.3.0` 存在
- **Review gate**：W7 完成后写 `review-W7.md`，执行 `ssf execution review --wave W7 --verdict pass`

## Test Obligations

- **必须先从失败测试开始的行为**（TDD RED 优先）：
  - 所有 `Frame` / `FrameCodec` / `Message` 编解码
  - 所有 `Client.execute` 路径（SELECT/INSERT/UPDATE/DELETE/参数化/超时）
  - 所有 `Transaction` commit/rollback/嵌套
  - 所有 `AsyncClient` 并发 50 查询
  - 所有 `Pool` acquire/release/exhaustion
  - 所有 JDBC `Connection`/`Statement`/`PreparedStatement`/`ResultSet` 方法
  - 所有 wire protocol 错误码映射
  - 所有 CLI 元命令（`.connect`/`.disconnect`/`.status`/`.server-info`）
  - 所有 SQLSTATE → JDBC Exception 子类映射
- **必需的边界情况**：
  - frame 长度 ≥ 0xFFFFFF（超长帧）
  - frame 长度字段不完整（partial read）
  - HELLO 客户端标识 > 64 字节
  - EXEC 参数数量 > 1024
  - SELECT 空结果集
  - INSERT 主键冲突 → 22000
  - 语法错误 → 42000
  - 客户端未发 HELLO 直接发 QUERY → 08000
  - 重连 5 次后仍失败
  - Pool size=4 并发 5 个 → 超时
  - 异步 50 查询并发 + 全部正确返回
  - JDBC 同步 connection 关闭后调用方法抛 `SQLException`
  - JDBC `setNull(1, Types.INTEGER)` → server 收到 NULL
  - JDBC `wasNull()` 在 `getXxx` 返回 null 后为 true
  - JDBC `setReadOnly(true)` 抛 `SQLException("not supported in v0.3")`
- **回归敏感区域**：
  - v0.2 全部 1003 测试
  - v0.1 全部 826 测试（通过 v0.2 兼容层跑通）
  - v0.2 JOIN 算子 + 并发 RWLock
  - v0.2 CLI 多行编辑 + `.explain` 树形输出 + 表格化结果

## Execution Mode

- **可用方式与推荐**：
  - `inline`（≤3 任务）— 不适用（38 任务 + 跨语言）
  - `batch-inline`（sequential）— 不推荐（耗时过长）
  - `sdd`（推荐）— 适用：38 任务 / 7 批次 / 跨语言 / 新模块 / 跨模块
- **用户确认的模式**：`sdd`
- **推荐理由 / 项目事实**：v0.2 已使用 SDD（3 worktree 并行）成功交付 38 任务；v0.3 范围更大（5 cap + Java 轨道），SDD 是唯一可行方案
- **非推荐选择的风险确认**：N/A（推荐即 sdd）
- **执行计划命令**：`ssf execution plan changes/tinydb-v0.3 --mode sdd --confirm --reason "v0.3 38 任务 / 7 批次 / 跨语言(Python+Java) / 新模块(server/protocol/client/cli-cs/jdbc) / 跨模块(CLI 重构横跨 parser+executor+transport), 远超 inlineThreshold=3, 必须 SDD; 与 v0.2 同模式" --wave W1:parallel:T-1.1,T-1.2,T-1.3,T-1.4,T-1.5 --wave W2:parallel:T-2.1,T-2.2,T-2.3,T-2.4,T-2.5,T-2.6,T-2.7:W1 --wave W3:parallel:T-3.1,T-3.2,T-3.3,T-3.4,T-3.5,T-3.6,T-3.7,T-3.8:W1 --wave W4:parallel:T-4.1,T-4.2,T-4.3,T-4.4,T-4.5,T-4.6:W3 --wave W5:parallel:T-5.1,T-5.2,T-5.3,T-5.4: --wave W6:parallel:T-6.1,T-6.2,T-6.3,T-6.4,T-6.5,T-6.6,T-6.7:W5 --wave W7:serial:T-7.1,T-7.2,T-7.3,T-7.4,T-7.5:W2,W3,W4,W5,W6`
- **允许的修订**：可 `ssf execution revise` 升级为新 revision（如 wave 拆分变化）
- **计划 revision / artifact hash**：执行 `ssf execution plan` 后自动记录

## Verification Dimensions

| 维度 | 状态 | 发现 |
|------|------|------|
| Completeness | Pending | — |
| Correctness | Pending | — |
| Coherence | Pending | — |

**总体结论**：Pending（待 W7 后填）

## Review Gates

- **强制审查点**：每个 Execution Wave 完成后记录 `ssf execution review` 的 review receipt（`pass` 或 `fail`）
- **阻塞类别**：
  - 依赖 wave 的 review receipt 非 `pass`
  - 测试覆盖率未达标（Python <80% 或 Java <70%）
  - v0.1/v0.2 测试不通过（向后兼容破坏）
  - scope audit 命中 Out 范围（TLS/auth/replication/prepared cache 等）
  - 外部依赖审计失败（Python 引入非 stdlib 或 Java 引入非 JUnit 第三方）
- **收口条件**：所有 wave review receipt = `pass` + 端到端双向互操作通过 + spec-merge 完成 + tag pushed

## Escalation Rules

- **何时回退到 `specifying`**：
  - 用户新增范围（如要求 v0.3 加入 TLS 或认证）
  - 发现 wire protocol 设计需要破坏性变更（bump major version）
  - 验证发现 v0.1/v0.2 SQL 语法不兼容（透传假设失败）
  - 端到端发现 Python ↔ Java 协议字节序/编码不一致（需修改协议 spec）
- **何时回退到 `bridging`**：
  - tasks.md 批次划分变化（如新增 wave）
  - 验收检查项变化（如提高覆盖率门禁）
  - Design Constraint D-1 ~ D-10 中任意一条被挑战
- **何时不得继续实现**：
  - 任一 wave review receipt = `fail` 且 issue 未在 24h 内修复
  - 测试覆盖率未达标且无法在不引入新依赖前提下提升
  - spec-merge 与 v0.2 specs 冲突（CLI 部分 MODIFIED 需求）
  - Maven 构建失败且无 JDK 8 兼容方案
  - JDBC JAR 体积 > 200KB 且无法裁剪（移除 debug 符号 + 压缩）