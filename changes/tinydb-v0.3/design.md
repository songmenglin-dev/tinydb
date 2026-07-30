# Design: tinydb-v0.3

## Context

- **起点**: tinydb v0.2 已发布（tag `tinydb-v0.2.0`，master HEAD `f652636`），1003 测试 / 88.75% 覆盖率，12 批次 38 任务全部完成
- **现有架构**: `src/tinydb/{sql,storage,executor,index,tx,types,api,cli}`，Python 3.10+，零运行时依赖（CLI prompt_toolkit 可选），单 `.db` 文件后端，单进程多事务 RWLock 并发，prompt_toolkit REPL
- **目标产物**: 在 v0.2 基础上扩展为 v0.3，引入 **tinydb-server 守护进程 + Python Client + Wire Protocol + CLI 双模式 + JDBC Java JAR** 五条新能力，保持公共 API 100% 向后兼容
- **使用模型**:
  - Python 端：业务代码可继续 in-process 调用 `Database`，也可改用 `tinydb.client.Client` 跨进程访问远端 server
  - Java 端：通过 JDBC URL `jdbc:tinydb://host:port/` 直连 server，业务系统零修改即可用标准 JDBC API
  - 部署形态：`tinydb-server --db-path X.db -H 0.0.0.0 -p 8520` 单进程守护
- **硬约束**（来自 `dp_0_decisions`）:
  - Python 3.10+ **零运行时外部依赖**（asyncio/threading/socket 全部 stdlib）
  - Java 8+ / JDBC 4.2 baseline（Maven 构建，JDK 1.8 source/target）
  - 单 `.db` 文件后端**完全复用 v0.2**
  - wire protocol 透传 SQL 字符串，v0.1/v0.2 SQL 语法 **100% 不变**
  - 覆盖率门禁：**Python ≥80% + Java ≥70%**
  - 完成时**必须 spec-merge + push 到 origin**
- **目标用户**:
  - 现有 tinydb Python 用户（嵌入式）
  - 新增：跨进程/多机部署的 Python 用户（Client）
  - 新增：Java 生态用户（JDBC）— 这是数量级最大的增量
- **非目标**（来自 `proposal.md > Out`）: TLS / 用户认证 / 集群复制 / prepared statement cache / GUI / IPv6 / UDS / 二进制 BLOB / JSON 列类型 / 异步游标

## Goals

1. **协议简洁可调试**: wire protocol 用文本+长度帧，可直接 `tcpdump` + 手写 socket 验证；不引入 protobuf/flatbuffers 等二进制 IDL
2. **服务端极简**: `tinydb-server` 单进程 asyncio，复用 v0.2 `Database.execute` 全栈，不实现并行 SQL 路径
3. **Python 客户端零依赖**: 同步 + 异步两套 API 全部用 stdlib（socket + asyncio + threading）
4. **CLI 双模式透明**: `--file`/`--uri` 互斥启动；运行时 `.connect`/`.disconnect` 切换；元命令同名同语义
5. **JDBC 最小可用**: 满足 80% JDBC 使用场景（CRUD + 事务 + ResultSet + MetaData），未实现方法显式抛 `SQLException` 不静默
6. **跨语言互操作**: Python client ↔ Python server、Java JDBC ↔ Python server 双向验证
7. **优雅降级**: server 启动失败（端口占用/.db 损坏）给出明确错误并 exit code 2/4；CLI 连接失败 stderr 清晰
8. **可测试性**: 每条 capability 都先写 pytest/JUnit 用例（RED→GREEN→IMPROVE），wire protocol 用 property-based test 验证帧编解码
9. **向后兼容**: v0.2 的 1003 测试 100% 通过；公共 API 仅新增可选 kw 参数；CLI 既有参数保留
10. **零核心依赖**: Python 运行时零依赖；Java JAR 零第三方依赖（仅 JUnit 测试范围）

## Decisions

### D-1: Wire Protocol = 文本 SQL 行 + 4 字节大端长度前缀帧
- **Choice**: 双层帧 —— 上层 PAYLOAD 中 SQL 字符串为 UTF-8 文本 + 参数类型/值用 `[TYPE(1B)][LEN(4B BE)][VALUE]`；外层帧头 `[LEN(4B BE)][TYPE(1B)][FLAGS(1B)]`
- **Rationale**:
  - 类 MySQL/PG wire 风格，可直接 `tcpdump -A` 调试业务 SQL
  - 长度前缀便于流式读取（不像换行分隔那样需要扫描）
  - 4 字节长度上限 16MB 足够传输单条 INSERT/UPDATE
  - 不引入 protobuf/flatbuffers 等 IDL 工具链，避免构建系统膨胀
- **Alternatives considered**:
  - **纯二进制 MessagePack**: 紧凑但不可读，调试困难
  - **JSON 行分隔**: 易调试但解析开销大、长度字段冗余
  - **HTTP+JSON over TCP**: 易集成但违反 C/S 直连语义
- **Trade-off**: 长度前缀比 line-delimited 多 6 字节开销；换来 streaming 友好

### D-2: tinydb-server 单进程 asyncio
- **Choice**: `asyncio.start_server` 单进程监听；每条 accepted socket 创建 `ServerSession` 协程；Session 内**串行**处理命令（一次一条 SQL），并发写互斥通过 v0.2 RWLock
- **Rationale**:
  - asyncio 零依赖；与 v0.2 单写者假设对齐
  - 协程栈轻量，64 并发连接内存 < 10MB
  - 复用 v0.2 `Database.execute`，不实现并行 SQL 解析/执行
- **Alternatives considered**:
  - **多线程（threading + socket）**: GIL 下同进程多连接收益有限，复杂度高
  - **多进程（pre-fork / multiprocessing）**: 状态共享难，违背单 `.db` 文件约束
  - **async/await + uvloop**: uvloop 是 C 扩展，违反零依赖
- **Trade-off**: GIL 下 Python CPU 密集型 SQL 仍串行；但 v0.2 已经是这个模型，server 无放大效应

### D-3: Python Client 同步用 socket + threading 收发
- **Choice**: `tinydb.client.Client` 用 `socket.create_connection` + `threading.Thread`（守护线程读循环）+ `queue.Queue` 把读帧派发到主调线程；同步 `execute` 用 `threading.Event` 等待 response
- **Rationale**:
  - 同步 API 在业务代码中比 asyncio 更易用
  - 读循环 daemon 线程是 stdlib 经典模式
  - 心跳/PING/QUIT 都在读循环内调度，无需定时器线程
- **Alternatives considered**:
  - **selectors 单线程**: 无守护线程但需要手动 pump
  - **run_in_executor 包装 async**: 增加复杂度但保留 asyncio 心智
  - **grpc / thrift**: 重量级且需 IDL
- **Trade-off**: 同步 Client 每连接占 1 线程；连接池复用可缓解

### D-4: Python AsyncClient 用 asyncio 同一协议栈
- **Choice**: `tinydb.client.AsyncClient` 用 `asyncio.open_connection` + asyncio StreamReader/Writer；编解码复用 `tinydb.protocol` 模块（同一份 codec 在同步/异步两侧都用）
- **Rationale**:
  - 协议编解码层与传输层解耦，同一 codec 跨 sync/async
  - 业务可在 FastAPI/aiohttp 中直接 await
  - asyncio 在高并发场景优势明显（数千连接）
- **Alternatives considered**:
  - **同步 Client + 异步包装**: 失真，GIL 仍阻塞
  - **uvloop 加速**: 违反零依赖
- **Trade-off**: 异步 API 比同步 API 略复杂，文档要求更明确

### D-5: 协议握手 HELLO 无认证（v0.3 占位）
- **Choice**: HELLO 帧携带 client 标识字符串，server 回 OK + server 版本；不校验任何密码/令牌
- **Rationale**:
  - v0.3 Out 显式排除认证；提供 hook 让 v0.4 引入时不破坏协议兼容
  - 调试时可 `nc` 手敲 HELLO 验证 server 可用
  - 明文 HELLO 是 v0.3 默认占位；未来 TLS 包裹即可升级
- **Alternatives considered**:
  - **v0.3 直接做 challenge-response**: 工作量翻倍；Out 已排除
  - **HELLO 携带 token + HMAC**: 复杂度溢出 v0.3 范围
- **Trade-off**: 任何能连上端口的客户端都能执行 SQL；v0.3 部署需配 `bind 127.0.0.1` 或网络层 ACL

### D-6: CLI 双模式 mode 字段
- **Choice**: `tinydb/cli/app.py` 顶层 `mode: Literal["embedded","remote"]` 字段；`run_embedded(path)` / `run_remote(uri)` 两个工厂；`REPL` 类接受 `backend: Database | Client` 抽象
- **Rationale**:
  - mode 显式比 if-else 分支可测
  - backend 多态让元命令（`.tables`/`.schema`/`.explain`）在两种模式下走同一代码路径
  - 启动选项校验集中在 `app.py`
- **Alternatives considered**:
  - **命令子类化 EmbeddedREPL/RemoteREPL**: 重类型，复用差
  - **插件式 backend 注册**: 过设计
- **Trade-off**: mode 字段值运行时不变；运行时切换走 `.connect`/`.disconnect` 元命令

### D-7: JDBC 用纯 socket 直连 server（Type-4）
- **Choice**: `org.tinydb.jdbc.TinyDriver` 用 `java.net.Socket` 直接连 tinydb-server；按 wire protocol 编解码帧；不使用任何第三方 NIO 库（Netty/Mina）
- **Rationale**:
  - Type-4 纯 Java 驱动，跨平台零依赖
  - `java.net.Socket` 同步阻塞足够（每连接 1 线程），与 Python 同步 Client 对称
  - JAR 体积小（<200KB）
- **Alternatives considered**:
  - **java.nio 异步**: 复杂度高，且 JDBC API 同步语义下价值有限
  - **Netty**: 引入依赖 + 增加 JAR 体积
- **Trade-off**: JDBC 高并发场景每连接 1 线程；连接池（c3p0/HikariCP 外部）可缓解；本驱动不内置池

### D-8: JDBC PreparedStatement 复用同一 wire protocol EXEC 帧
- **Choice**: Python PreparedStatement（占位 v0.4）与 JDBC PreparedStatement 都通过 EXEC 帧带参数；v0.3 阶段 Python 端不暴露 PreparedStatement API（仅 JDBC 端），wire protocol 同一份
- **Rationale**:
  - v0.3 Out 排除 Python prepared statement cache，简化 Python 端
  - Java 端用户强需求（JDBC 习惯）
  - 协议层统一编码/解码
- **Alternatives considered**:
  - **Python 同步 PS 占位**: 投入低但 v0.3 Out 不需要
  - **JDBC 不走 EXEC 走 QUERY 字符串拼接**: 注入风险 + 性能差
- **Trade-off**: Python 端用户需要手写参数化 SQL；可在 v0.4 补

### D-9: SQLSTATE 子集 5 类
- **Choice**: server 端错误码映射到 5 类 SQLSTATE（`08000`/`22000`/`25000`/`42000`/`HY000`），JDBC 端按此映射到 `java.sql.SQLException` 子类
- **Rationale**:
  - 与 MySQL/PG/ODBC 的 SQLSTATE 对齐，业务系统可移植
  - 5 类覆盖 95% 错误场景；细分（22001 截断/22002 NULL 等）留 v0.4
- **Alternatives considered**:
  - **完整 SQLSTATE (~70 类)**: 工作量翻倍；本版本边际收益低
  - **自定义 code**: 业务系统不可移植
- **Trade-off**: 错误分类较粗；少数错误（如 `22001` 截断）会被映射到 `22000`

### D-10: 协议版本号嵌入 OK 帧
- **Choice**: server OK 帧回 `version="tinydb-0.3.0"`；未来 v0.4 协议破坏性变更时 bump major
- **Rationale**:
  - client/server 协议版本协商可见
  - 调试 `nc 127.0.0.1 8520` 直接看到版本
- **Alternatives considered**:
  - **HELLO 时 client 声明支持版本、server 选择最高公共版本**: 标准但 v0.3 阶段冗余
- **Trade-off**: v0.3 协议固定无协商；v0.4 引入多版本时补

## Risks And Trade-Offs

### R-1: HELLO 无认证导致生产部署风险
- **风险**: 默认 server 监听 0.0.0.0 时，任何能访问端口的客户端都能执行 SQL
- **缓解**: README 显式说明 v0.3 仅适合可信网络；推荐 `bind 127.0.0.1` 或网络层 ACL；v0.4 引入认证
- **Trade-off 接受**: 与 v0.3 Out 一致

### R-2: asyncio 单进程串行 SQL 的吞吐瓶颈
- **风险**: GIL + 串行 execute 在多连接高 QPS 下退化
- **缓解**: v0.2 已证明 RWLock 模型读多写少场景 OK；D-2 选择与 v0.2 模型对齐；高 QPS 场景留 v0.4 多进程/多机
- **Trade-off 接受**: 与 v0.3 单进程假设一致

### R-3: JDBC 单连接 1 线程（同步 socket）的扩展性
- **风险**: 高并发下 JVM 线程数膨胀
- **缓解**: 文档说明推荐外部 HikariCP/c3p0 池化；驱动不内置池保持 JAR 简洁
- **Trade-off 接受**: 与 D-7 一致

### R-4: wire protocol 透传 SQL 注入面
- **风险**: client 拼接字符串 → server 拼接 → SQL 注入
- **缓解**: 文档强制使用 EXEC 帧带参数；CLI 用户应避免 f-string 拼接；Python 端仅 EXEC 支持参数
- **Trade-off 接受**: 与 REQ-PROTO-5 一致

### R-5: Java 8 source/target 限制 API 选择
- **风险**: 部分现代 API（`List.of`、`var`、records）不可用
- **缓解**: 严格用 Java 8 子集；JDBC 4.2 即 Java 8 时代的 API
- **Trade-off 接受**: 与 dp_0 constraints 一致

### R-6: Python 端跨包导入循环
- **风险**: `tinydb.client` ↔ `tinydb.protocol` ↔ `tinydb.server` 可能形成循环
- **缓解**: 严格分层：`protocol` 零依赖（仅 stdlib）、`client` 只依赖 `protocol`、`server` 只依赖 `tinydb.api` + `protocol`；CLI 单独包
- **Trade-off 接受**: 与 D-1/D-3 一致

### R-7: 测试时长爆炸
- **风险**: 端到端测试（spawn server + JDBC e2e）单测 60+ 用例可能拖慢 CI
- **缓解**: e2e 测试标记 `@Tag("e2e")`，Maven Surefire 分阶段；Python e2e 用 pytest marker `network`
- **Trade-off 接受**: 跨语言互操作不可妥协

### R-8: spec-merge 与 v0.2 specs 重叠
- **风险**: v0.2 已有 9 个 spec 文件（cli/concurrency/sql-join/...），v0.3 新增 5 个，merge 时结构需保持一致
- **缓解**: v0.3 spec 全部新增在 `changes/tinydb-v0.3/specs/`，merge 后并入 `specs/<cap>/spec.md`（cli → cli 增量；network-server → 新 cap；wire-protocol → 新 cap；network-client → 新 cap；jdbc-driver → 新 cap）
- **Trade-off 接受**: 与 dp_0 spec-merge 必需一致