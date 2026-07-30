# Tasks: tinydb-v0.3

## File Structure

### Create (Python 端, src/tinydb/)

| 路径 | 职责 |
|------|------|
| `src/tinydb/protocol/__init__.py` | 协议包入口，导出 Frame/Message/Codec |
| `src/tinydb/protocol/frame.py` | 帧结构 `Frame(len, type, flags, payload)` + 异常 |
| `src/tinydb/protocol/codec.py` | `FrameReader(io.BytesIO)`/`FrameWriter` 流式编解码 |
| `src/tinydb/protocol/messages.py` | 消息类 `Hello/Ok/Err/Query/Exec/ResultHeader/ResultRow/ResultDone/ResultError/Ping/Pong/Quit` |
| `src/tinydb/protocol/errors.py` | `ProtocolError` + `SQLSTATE` 映射（5 类） |
| `src/tinydb/protocol/handshake.py` | HELLO 流程常量（client/server） |
| `src/tinydb/server/__init__.py` | server 包入口，导出 `run_server` |
| `src/tinydb/server/app.py` | `asyncio` TCP server 主循环 + 信号处理 |
| `src/tinydb/server/session.py` | `ServerSession` 每连接协程（handshake + 命令循环） |
| `src/tinydb/server/handler.py` | 命令分派到 `tinydb.api.Database.execute` + 错误映射 |
| `src/tinydb/server/config.py` | `ServerConfig` dataclass（host/port/max_conns/...） |
| `src/tinydb/client/__init__.py` | client 包入口 |
| `src/tinydb/client/sync.py` | `Client(host, port, ...)` 同步实现 |
| `src/tinydb/client/async_client.py` | `AsyncClient` 异步实现 |
| `src/tinydb/client/pool.py` | `Pool` 同步连接池 |
| `src/tinydb/client/errors.py` | `ConnectionError/TimeoutError/IntegrityError/ProtocolError` |
| `src/tinydb/cli/app.py` | 重构为 mode 双模式启动 |
| `src/tinydb/cli/backend.py` | `Backend` 抽象类（embedded/remote 两种实现） |
| `src/tinydb/cli/uri.py` | URI 解析 `tinydb://[user[:pass]@]host[:port]/[db]` |

### Create (Python 端, tests/)

| 路径 | 职责 |
|------|------|
| `tests/protocol/test_frame.py` | 帧编解码单元测试 |
| `tests/protocol/test_messages.py` | 消息序列化单元测试 |
| `tests/protocol/test_codec.py` | 流式 codec + property-based 测试 |
| `tests/protocol/test_errors.py` | SQLSTATE 映射测试 |
| `tests/server/test_app.py` | server 启动 + accept + bind 错误测试 |
| `tests/server/test_session.py` | 单连接握手 + 命令循环测试 |
| `tests/server/test_handler.py` | 命令分派到 Database.execute 测试 |
| `tests/server/test_heartbeat.py` | PING/PONG + idle PONG + 死亡连接清理测试 |
| `tests/server/test_shutdown.py` | SIGINT 优雅关闭测试 |
| `tests/client/test_sync.py` | 同步 Client execute/PING/transaction 测试 |
| `tests/client/test_async.py` | 异步 AsyncClient 并发测试 |
| `tests/client/test_pool.py` | 连接池 acquire/release 测试 |
| `tests/client/test_reconnect.py` | 指数退避重连测试 |
| `tests/cli/test_mode.py` | CLI 双模式启动测试 |
| `tests/cli/test_uri.py` | URI 解析测试 |
| `tests/cli/test_remote_meta.py` | 远程 .connect/.disconnect/.status/.server-info 测试 |
| `tests/integration/test_e2e_python.py` | Python client ↔ Python server 端到端 |
| `tests/integration/test_concurrent_server.py` | 多客户端并发 + RWLock 互斥 |

### Create (Java 端, jdbc/)

| 路径 | 职责 |
|------|------|
| `jdbc/pom.xml` | Maven 配置（JDK 8 source/target + JUnit 5 + JaCoCo ≥70%）|
| `jdbc/src/main/resources/META-INF/services/java.sql.Driver` | 驱动 SPI 注册 |
| `jdbc/src/main/java/org/tinydb/jdbc/TinyDriver.java` | `java.sql.Driver` 实现 + URL 前缀匹配 |
| `jdbc/src/main/java/org/tinydb/jdbc/TinyConnection.java` | `Connection` 实现 |
| `jdbc/src/main/java/org/tinydb/jdbc/TinyStatement.java` | `Statement` 实现 |
| `jdbc/src/main/java/org/tinydb/jdbc/TinyPreparedStatement.java` | `PreparedStatement` 实现 + 参数绑定 |
| `jdbc/src/main/java/org/tinydb/jdbc/TinyResultSet.java` | `ResultSet` 实现 + 列名查找 |
| `jdbc/src/main/java/org/tinydb/jdbc/TinyDatabaseMetaData.java` | `DatabaseMetaData` 实现（最小子集）|
| `jdbc/src/main/java/org/tinydb/jdbc/TinyTypes.java` | JDBC `Types` ↔ wire protocol type code 映射 |
| `jdbc/src/main/java/org/tinydb/jdbc/TinySQLException.java` | SQLSTATE → `SQLException` 子类映射 |
| `jdbc/src/main/java/org/tinydb/jdbc/protocol/Frame.java` | Java 端帧结构 + 编解码 |
| `jdbc/src/main/java/org/tinydb/jdbc/protocol/Codec.java` | Java 端流式 codec |
| `jdbc/src/main/java/org/tinydb/jdbc/protocol/Messages.java` | Java 端消息类 |
| `jdbc/src/main/java/org/tinydb/jdbc/protocol/ErrorCode.java` | SQLSTATE 5 类 + mapper |
| `jdbc/src/test/java/org/tinydb/jdbc/TinyDriverTest.java` | Driver 注册 + URL 解析测试 |
| `jdbc/src/test/java/org/tinydb/jdbc/TinyConnectionTest.java` | Connection 方法测试 |
| `jdbc/src/test/java/org/tinydb/jdbc/TinyStatementTest.java` | Statement 方法测试 |
| `jdbc/src/test/java/org/tinydb/jdbc/TinyPreparedStatementTest.java` | PS 参数绑定测试 |
| `jdbc/src/test/java/org/tinydb/jdbc/TinyResultSetTest.java` | ResultSet 列访问 + 类型转换测试 |
| `jdbc/src/test/java/org/tinydb/jdbc/EndToEndTest.java` | spawn server + 完整 CRUD + 事务 |

### Modify

| 路径 | 改动 |
|------|------|
| `src/tinydb/cli/app.py` | 增加 `--host`/`--port`/`--uri`/`--file` 参数；mode 选择 backend |
| `src/tinydb/cli/repl.py` | REPL 接受 backend 抽象而非 Database |
| `src/tinydb/cli/commands.py` | 新增 `.connect`/`.disconnect`/`.status`/`.server-info` |
| `pyproject.toml` | 增加 `tinydb-server` console_script entry point |
| `README.md` | 新增 C/S + JDBC 章节 |
| `docs/NETWORK.md` | 新建 — 网络协议与 server 配置 |
| `docs/JDBC.md` | 新建 — JDBC 接入指南 |

## Interfaces

### Wire Protocol 层（Python 端）

`src/tinydb/protocol/frame.py` **Produces**:
- `class Frame: len:int, type:int, flags:int, payload:bytes`
- `class ProtocolError(TinyDBError)`

`src/tinydb/protocol/codec.py` **Produces**:
- `class FrameWriter: write_frame(Frame) -> None`
- `class FrameReader: read_frame() -> Frame`（EOF/不完整 → ProtocolError）

`src/tinydb/protocol/messages.py` **Produces**:
- `class Hello(client: str)`
- `class Ok(version: str)`
- `class Err(code: str, msg: str)`
- `class Query(sql: str)`
- `class Exec(sql: str, params: list[Param])`
- `class ResultHeader(columns: list[tuple[str, int]])`
- `class ResultRow(values: list[Any])`
- `class ResultDone(rowcount: int, last_insert_id: int, status_flags: int)`
- `class ResultError(code: str, msg: str)`
- `class Ping(ts: int)`, `class Pong(ts: int)`, `class Quit()`

`src/tinydb/protocol/errors.py` **Produces**:
- `SQLSTATE_MAP: dict[str, type[TinyDBError]]` — 5 类映射

**Consumes**: stdlib `struct`/`io`

### Wire Protocol 层（Java 端）

`org.tinydb.jdbc.protocol.Frame` **Produces**: `record Frame(int len, byte type, byte flags, byte[] payload)` + `Frame.read(DataInputStream) / Frame.write(DataOutputStream)`

`org.tinydb.jdbc.protocol.Codec` **Produces**: 静态方法 `encodeHello/Ok/Err/Query/Exec/...` + `decodeFrame`

### Server 层

`src/tinydb/server/app.py` **Produces**:
- `async def run_server(config: ServerConfig) -> None`
- `def main() -> None`（CLI 入口）

`src/tinydb/server/session.py` **Produces**:
- `class ServerSession: async def handle(reader, writer) -> None`

`src/tinydb/server/handler.py` **Consumes**: `tinydb.api.Database` — 调用 `db.execute(sql, params)`

### Client 层

`src/tinydb/client/sync.py` **Produces**:
- `class Client: def execute(self, sql, params=None, *, timeout=30.0) -> Result`
- `class Result: rows, rowcount, last_insert_id, columns`

**Consumes**: `tinydb.protocol.Frame/Reader/Writer/Messages`

`src/tinydb/client/async_client.py` **Produces**:
- `class AsyncClient: async def execute(self, sql, params=None) -> Result`
- `async def execute_many(self, sql, params_list) -> int`

### CLI 层

`src/tinydb/cli/backend.py` **Produces**:
- `class Backend(ABC): def execute(self, sql, params) -> Result; def close(self) -> None; def ping(self) -> float`
- `class EmbeddedBackend(Backend)` — 包装 `tinydb.api.Database`
- `class RemoteBackend(Backend)` — 包装 `tinydb.client.Client`

`src/tinydb/cli/uri.py` **Produces**:
- `def parse_uri(uri: str) -> tuple[host, port, database]`

### JDBC 层

`org.tinydb.jdbc.TinyDriver` **Consumes**: `org.tinydb.jdbc.protocol.Codec` — 调用 `writeFrame/readFrame` 与 `tinydb-server` 通信

`org.tinydb.jdbc.TinyConnection` **Consumes**: `TinyStatement`/`TinyPreparedStatement`/`TinyDatabaseMetaData`

---

## Tasks

### Batch 1: Wire Protocol 基础（Python 端）

#### T-1.1 Frame 数据结构
- **File**: `src/tinydb/protocol/frame.py`
- **TDD**:
  1. RED: 写 `tests/protocol/test_frame.py::test_frame_construct` — 构造 `Frame(len=5, type=0x10, flags=0, payload=b"hello")` 验证字段
  2. RED: `test_frame_to_bytes` — 验证序列化字节序（大端长度）
  3. GREEN: 实现 `Frame` dataclass + `to_bytes/from_bytes`（用 `struct.pack(">I", self.len)`）
  4. IMPROVE: 加 `__repr__` 便于调试
- **Interfaces**: `Frame(len:int, type:int, flags:int, payload:bytes)` + `ProtocolError`
- **Depends on**: —
- **Acceptance**: `pytest tests/protocol/test_frame.py -v` 全绿

#### T-1.2 FrameCodec 流式编解码
- **File**: `src/tinydb/protocol/codec.py`
- **TDD**:
  1. RED: `test_codec_write_then_read_roundtrip` — `writer.write_frame(f); reader.read_frame() == f`
  2. RED: `test_codec_partial_frame` — 写入 5 字节长度帧，reader 第一次返回不完整 → 抛 `IncompleteFrameError`
  3. RED: `test_codec_oversize_frame` — 写 `len=0xFFFFFF` 帧 → reader 抛 `ProtocolError`
  4. GREEN: 实现 `FrameWriter(io.BytesIO)`/`FrameReader(io.BytesIO)`
  5. IMPROVE: 加 `MaxFrameSizeError` 独立异常类型
- **Interfaces**: `FrameWriter.write_frame(f)`, `FrameReader.read_frame() -> Frame`
- **Depends on**: T-1.1
- **Acceptance**: `pytest tests/protocol/test_codec.py -v` 全绿；property-based 1000 次随机 roundtrip 不抛错

#### T-1.3 SQLSTATE 错误映射
- **File**: `src/tinydb/protocol/errors.py`
- **TDD**:
  1. RED: `test_sqlstate_map_covers_5_codes` — 5 类 code 都在 map
  2. RED: `test_sqlstate_to_exception_class` — `map_sqlstate("08000") is ConnectionException`
  3. GREEN: 定义 `SQLSTATE_MAP` + `map_sqlstate(code) -> type[Exception]`
  4. IMPROVE: 加 `__all__` 导出
- **Interfaces**: `SQLSTATE_MAP`, `map_sqlstate`
- **Depends on**: —
- **Acceptance**: `pytest tests/protocol/test_errors.py -v` 全绿

#### T-1.4 Message 类族
- **File**: `src/tinydb/protocol/messages.py`
- **TDD**:
  1. RED: `test_hello_encode_decode` — `Hello("py-1.0").to_frame().payload_as_utf8() == "py-1.0"`
  2. RED: `test_query_empty_sql` — `Query("")` 编码后 `len` = 0
  3. RED: `test_exec_with_params` — `Exec("SELECT ?", [Param(INT64, 42)])` 编码后含 type+len+data
  4. RED: `test_result_done_flags` — `ResultDone(1, 5, 0x05)` flags 字段正确
  5. GREEN: 实现所有 12 个消息类（每类 `to_frame()/from_frame()`）
  6. IMPROVE: 加 `MessageType` enum 替代裸 byte
- **Interfaces**: 12 个消息类，每类 `to_frame() -> Frame` / `from_frame(Frame) -> Self`
- **Depends on**: T-1.1, T-1.3
- **Acceptance**: `pytest tests/protocol/test_messages.py -v` 全绿

#### T-1.5 Hello 握手协议常量
- **File**: `src/tinydb/protocol/handshake.py`
- **TDD**:
  1. RED: `test_hello_client_id_max_64_bytes` — 客户端 id 字段超过 64 字节时 `Hello.__post_init__` 抛 `ValueError`
  2. RED: `test_ok_version_string` — `Ok(version="0.3.0")` 序列化后含 version
  3. GREEN: 实现 HELLO/OK 常量 + 校验
  4. IMPROVE: 文档注释引用 REQ-PROTO-3
- **Interfaces**: 重新导出 `Hello/Ok` from `messages.py`
- **Depends on**: T-1.4
- **Acceptance**: 单元测试 + `grep` 校验协议常量引用

---

### Batch 2: tinydb-server（Python 端 asyncio）

#### T-2.1 ServerConfig dataclass
- **File**: `src/tinydb/server/config.py`
- **TDD**:
  1. RED: `test_config_defaults` — 默认 host=127.0.0.1、port=8520、max_conns=64、idle_timeout=1800
  2. RED: `test_config_port_range` — port=0 或 port=70000 抛 `ValueError`
  3. GREEN: 实现 `@dataclass class ServerConfig`
  4. IMPROVE: 加 `__post_init__` 校验
- **Interfaces**: `ServerConfig(host, port, db_path, max_conns, idle_timeout, heartbeat_interval, heartbeat_misses)`
- **Depends on**: —
- **Acceptance**: `pytest tests/server/test_config.py -v`（如未存在则合并入 test_app.py）

#### T-2.2 ServerSession 握手 + 命令循环
- **File**: `src/tinydb/server/session.py`
- **TDD**:
  1. RED: `test_session_handshake_then_query` — mock `Database` 收到 `Hello + Query(SELECT 1)` 返回 `Ok + ResultHeader + ResultRow + ResultDone`
  2. RED: `test_session_missing_hello_closes` — 直接发 Query 时回 Err(code=08000) 后关闭
  3. RED: `test_session_quit_closes_gracefully` — 发 Quit 回 Ok 后关闭
  4. GREEN: 实现 `class ServerSession` 协程方法 `async def handle(reader, writer, db)`
  5. IMPROVE: 加异常隔离 `try/except` 包住命令循环
- **Interfaces**: `class ServerSession: async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, db: Database) -> None`
- **Depends on**: T-1.4, T-2.1
- **Acceptance**: `pytest tests/server/test_session.py -v` 全绿

#### T-2.3 命令分派 handler
- **File**: `src/tinydb/server/handler.py`
- **TDD**:
  1. RED: `test_dispatch_query_select` — handler 收 `Query("SELECT 1")` 返回 ResultHeader/Row/Done
  2. RED: `test_dispatch_query_syntax_error` — mock parser 抛 SyntaxError → 回 `ResultError(code=42000)`
  3. RED: `test_dispatch_exec_with_params` — handler 收 `Exec(sql, params=[INT64,42])` 调用 `db.execute(sql, [42])`
  4. GREEN: 实现 `async def dispatch(session, msg, db) -> list[Frame]`
  5. IMPROVE: 把异常映射到 SQLSTATE 集中处理
- **Interfaces**: `async def dispatch(session: ServerSession, msg: Message, db: Database) -> list[Frame]`
- **Depends on**: T-2.2
- **Acceptance**: `pytest tests/server/test_handler.py -v` 全绿；含 mock Database 5 场景

#### T-2.4 asyncio TCP server 主循环 + 信号处理
- **File**: `src/tinydb/server/app.py`
- **TDD**:
  1. RED: `test_run_server_binds_and_accepts` — 启动 `run_server` 后 socket 可 connect
  2. RED: `test_run_server_bind_error` — 同端口二次启动抛 `OSError("address in use")`
  3. RED: `test_run_server_sigint_graceful` — 发 SIGINT 后 run_server 干净退出（exit code 0）
  4. GREEN: 实现 `async def run_server(config)` + `def main()`
  5. IMPROVE: 注册 SIGINT/SIGTERM handler + 等待活跃连接完成
- **Interfaces**: `async def run_server(config: ServerConfig) -> None`、`def main() -> None`
- **Depends on**: T-2.1, T-2.2, T-2.3
- **Acceptance**: `pytest tests/server/test_app.py -v` 全绿；含 30s 强制关闭 timeout

#### T-2.5 心跳与死亡连接清理
- **File**: `src/tinydb/server/session.py`（扩）
- **TDD**:
  1. RED: `test_session_idle_pong` — 30s 无数据触发 server 主动发 Pong
  2. RED: `test_session_ping_returns_pong` — 客户端 Ping(ts) → server 回 Pong(ts)
  3. RED: `test_session_kill9_cleanup` — 模拟 client 死连接 → server 在 heartbeat_misses×interval 后关闭
  4. GREEN: 在 `ServerSession.handle` 中加入 `asyncio.wait_for(reader.read, timeout=heartbeat_interval)` + PONG
  5. IMPROVE: 用 `loop.call_at` 替代 wait_for 实现精确心跳
- **Interfaces**: 扩展 `ServerSession` 含心跳
- **Depends on**: T-2.2
- **Acceptance**: `pytest tests/server/test_heartbeat.py -v` 全绿；测试用 `heartbeat_interval=0.1s` 加速

#### T-2.6 CLI 入口 tinydb-server
- **File**: `src/tinydb/server/__main__.py`
- **TDD**:
  1. RED: `test_cli_help` — `python -m tinydb.server --help` exit 0
  2. RED: `test_cli_default_port` — `python -m tinydb.server --db-path /tmp/x.db` 监听 127.0.0.1:8520
  3. GREEN: `argparse` + 调 `main()`
  4. IMPROVE: 加 `[server]` 前缀日志
- **Interfaces**: console_script `tinydb-server`
- **Depends on**: T-2.4
- **Acceptance**: `pytest tests/server/test_cli.py -v` 全绿；手工 `tinydb-server --help` 正常

#### T-2.7 pyproject.toml entry point
- **File**: `pyproject.toml`（改）
- **TDD**: 直接编辑
  1. 在 `[project.scripts]` 添加 `tinydb-server = "tinydb.server.app:main"`
  2. 不引入新依赖
- **Acceptance**: `pip install -e .` 后 `which tinydb-server` 找到

---

### Batch 3: Python Client（同步 + 异步）

#### T-3.1 同步 Client 构造 + HELLO
- **File**: `src/tinydb/client/sync.py`
- **TDD**:
  1. RED: `test_client_connect_and_hello` — mock server 回 Ok 后 `client.server_version == "tinydb-0.3.0"`
  2. RED: `test_client_connect_refused` — 端口未监听时 `Client(...)` 抛 `ConnectionError`
  3. RED: `test_client_hello_timeout` — `connect_timeout=0.1` 不响应时抛 `TimeoutError`
  4. GREEN: 实现 `class Client.__init__(self, host, port, ...)`
  5. IMPROVE: 守护读线程守护 `daemon=True`
- **Interfaces**: `class Client(host, port, *, database=None, connect_timeout=5.0, heartbeat=True)`
- **Depends on**: T-1.4, T-1.5
- **Acceptance**: `pytest tests/client/test_sync.py -v` 全绿

#### T-3.2 同步 execute + Result
- **File**: `src/tinydb/client/sync.py`（扩）
- **TDD**:
  1. RED: `test_execute_select_returns_result` — mock 回 ResultHeader+Row+Done → `Result(rows, rowcount, columns)`
  2. RED: `test_execute_insert_returns_rowcount` — `Result(rowcount=1, last_insert_id=5)`
  3. RED: `test_execute_query_timeout` — mock 不响应 + `timeout=0.1` → 抛 `TimeoutError`
  4. GREEN: 实现 `def execute(self, sql, params=None, *, timeout=30.0) -> Result`
  5. IMPROVE: 用 `threading.Event` 等待 response + `queue.Queue` 派发
- **Interfaces**: `def execute(sql, params, timeout) -> Result`
- **Depends on**: T-3.1
- **Acceptance**: `pytest tests/client/test_sync.py::test_execute_*` 全绿

#### T-3.3 execute_many 批量
- **File**: `src/tinydb/client/sync.py`（扩）
- **TDD**:
  1. RED: `test_execute_many_batch_size_100` — 100 个 params 走 1 批 → 返回 100
  2. RED: `test_execute_many_rollback_on_conflict` — 第 50 行主键冲突 → 抛 `IntegrityError`
  3. GREEN: 实现 `def execute_many(self, sql, params_list, batch_size=100) -> int`
  4. IMPROVE: 加 `BatchTooLargeError` 独立异常
- **Interfaces**: `def execute_many(sql, params_list, batch_size=100) -> int`
- **Depends on**: T-3.2
- **Acceptance**: `pytest tests/client/test_sync.py::test_execute_many_*` 全绿

#### T-3.4 transaction 上下文
- **File**: `src/tinydb/client/sync.py`（扩）
- **TDD**:
  1. RED: `test_transaction_commit` — `with client.transaction(): execute(INSERT)` → 下一条独立 SELECT 可见
  2. RED: `test_transaction_rollback` — 块内抛错 → row 不可见
  3. RED: `test_transaction_nested_raises` — 嵌套触发抛 `ProtocolError`
  4. GREEN: 实现 `def transaction(self) -> ContextManager`
  5. IMPROVE: 加 `transaction_depth` 状态字段
- **Interfaces**: `@contextmanager def transaction(self) -> Iterator[None]`
- **Depends on**: T-3.2
- **Acceptance**: `pytest tests/client/test_sync.py::test_transaction_*` 全绿

#### T-3.5 自动重连（指数退避）
- **File**: `src/tinydb/client/sync.py`（扩）
- **TDD**:
  1. RED: `test_reconnect_after_server_restart` — 中途重启 server，execute 重试 5 次内成功
  2. RED: `test_reconnect_max_retries_exceeded` — server 永久下线 → 抛 `ConnectionError`
  3. GREEN: 实现 `_reconnect_with_backoff()`（100→200→400→800→1600ms）
  4. IMPROVE: 加 `_retry_count` 状态字段
- **Interfaces**: 内部 `_reconnect_with_backoff()`
- **Depends on**: T-3.2
- **Acceptance**: `pytest tests/client/test_reconnect.py -v` 全绿；总耗时断言 `<3.5s`

#### T-3.6 ping/close
- **File**: `src/tinydb/client/sync.py`（扩）
- **TDD**:
  1. RED: `test_ping_returns_rtt` — server 回 Pong → `client.ping() < 0.01`（loopback）
  2. RED: `test_ping_after_close_raises` — close 后 ping 抛 `ConnectionError`
  3. RED: `test_close_is_idempotent` — close() × 2 不抛错
  4. GREEN: 实现 `def ping(self) -> float`、`def close(self)`
  5. IMPROVE: close 发 Quit + 等待 OK
- **Interfaces**: `def ping() -> float`、`def close()`
- **Depends on**: T-3.1
- **Acceptance**: `pytest tests/client/test_sync.py::test_ping_* / test_close_*` 全绿

#### T-3.7 AsyncClient 异步实现
- **File**: `src/tinydb/client/async_client.py`
- **TDD**:
  1. RED: `test_async_execute_select` — `await AsyncClient(host, port).execute("SELECT 1")`
  2. RED: `test_async_concurrent_50_queries` — `asyncio.gather` 50 个 execute 全部成功
  3. RED: `test_async_execute_many` — `await ac.execute_many(sql, [params × 100])`
  4. GREEN: 实现 `class AsyncClient` 用 `asyncio.open_connection`
  5. IMPROVE: 复用 `tinydb.protocol.codec.FrameReader`（同步版）
- **Interfaces**: `class AsyncClient: async def execute/ping/close`
- **Depends on**: T-1.2, T-1.4
- **Acceptance**: `pytest tests/client/test_async.py -v` 全绿

#### T-3.8 Pool 连接池
- **File**: `src/tinydb/client/pool.py`
- **TDD**:
  1. RED: `test_pool_acquire_release` — `pool.acquire()` 返回 `Client`，with 退出归还
  2. RED: `test_pool_exhaustion_timeout` — size=4 并发 5 → 第 5 个 `acquire(timeout=0.1)` 抛 `TimeoutError`
  3. RED: `test_pool_reuse_after_release` — 释放后 acquire 命中已归还的连接
  4. GREEN: 实现 `class Pool`，内部用 `queue.Queue`
  5. IMPROVE: 归还时校验连接健康（ping）
- **Interfaces**: `class Pool(host, port, *, size=4): def acquire() -> Client`
- **Depends on**: T-3.1
- **Acceptance**: `pytest tests/client/test_pool.py -v` 全绿

---

### Batch 4: CLI 双模式

#### T-4.1 URI 解析
- **File**: `src/tinydb/cli/uri.py`
- **TDD**:
  1. RED: `test_parse_uri_full` — `tinydb://user:pw@host:9527/db` → (host,9527,"db")
  2. RED: `test_parse_uri_default_port` — `tinydb://host/x` → port=8520
  3. RED: `test_parse_uri_wrong_scheme` — `http://...` 抛 `ValueError("invalid scheme")`
  4. GREEN: 实现 `def parse_uri(uri: str) -> ParsedURI`
  5. IMPROVE: 支持 IPv6 host（`[::1]:8520`）
- **Interfaces**: `def parse_uri(uri: str) -> tuple[str, int, str]`
- **Depends on**: —
- **Acceptance**: `pytest tests/cli/test_uri.py -v` 全绿

#### T-4.2 Backend 抽象
- **File**: `src/tinydb/cli/backend.py`
- **TDD**:
  1. RED: `test_embedded_backend_execute` — mock Database，Backend.execute 返回 Result
  2. RED: `test_remote_backend_ping` — mock Client，Backend.ping 返回 RTT
  3. RED: `test_backend_close` — 两种 backend.close() 都安全
  4. GREEN: 实现 `class Backend(ABC)` + `EmbeddedBackend` + `RemoteBackend`
  5. IMPROVE: 加 `mode: Literal["embedded","remote"]` 属性
- **Interfaces**: `class Backend(ABC): execute/ping/close`
- **Depends on**: T-3.1
- **Acceptance**: `pytest tests/cli/test_backend.py -v` 全绿

#### T-4.3 CLI 启动重构（mode 选择）
- **File**: `src/tinydb/cli/app.py`
- **TDD**:
  1. RED: `test_cli_file_mode_starts_embedded` — `--file /tmp/x.db` 起 embedded
  2. RED: `test_cli_uri_mode_starts_remote` — `--uri tinydb://...` 起 remote
  3. RED: `test_cli_mutually_exclusive` — `--file` + `--uri` 同时给 → exit 2
  4. GREEN: 重构 `app.py` 增加 `--host`/`--port`/`--uri`/`--file` 参数
  5. IMPROVE: 默认 mode=embedded（无 --uri 时）
- **Interfaces**: argparse 新增 `--uri URI`、`--host HOST`、`--port PORT`
- **Depends on**: T-4.1, T-4.2
- **Acceptance**: `pytest tests/cli/test_mode.py -v` 全绿

#### T-4.4 REPL 接受 Backend
- **File**: `src/tinydb/cli/repl.py`
- **TDD**:
  1. RED: `test_repl_routes_select_to_backend` — input `SELECT 1` → Backend.execute 收到 `"SELECT 1"`
  2. RED: `test_repl_routes_explain_to_embedded_only` — remote 模式下 `.explain` 返回 `not supported in remote mode`
  3. GREEN: 重构 `REPL.__init__(backend: Backend)` 替代 `database: Database`
  4. IMPROVE: 保留 v0.2 多行编辑/语法高亮/历史
- **Interfaces**: `class REPL: __init__(backend: Backend)`
- **Depends on**: T-4.2
- **Acceptance**: `pytest tests/cli/test_repl.py -v`（保留 v0.2 测试基础上扩展）

#### T-4.5 元命令 .connect/.disconnect/.status/.server-info
- **File**: `src/tinydb/cli/commands.py`
- **TDD**:
  1. RED: `test_cmd_connect_switches_remote` — `.connect uri` 关闭旧连接建新连接
  2. RED: `test_cmd_disconnect_closes` — `.disconnect` 后 execute 抛 `not connected`
  3. RED: `test_cmd_status_shows_mode` — `.status` 输出 mode=remote/embedded + 连接信息
  4. RED: `test_cmd_server_info_only_remote` — embedded 模式下 `.server-info` 返回 `not available in embedded mode`
  5. GREEN: 注册 4 个新元命令
  6. IMPROVE: `.status` 输出 rtt 通过 `backend.ping()`
- **Interfaces**: 注册到 REPL command table
- **Depends on**: T-4.4
- **Acceptance**: `pytest tests/cli/test_remote_meta.py -v` 全绿

#### T-4.6 连接失败错误信息
- **File**: `src/tinydb/cli/app.py`（扩）
- **TDD**:
  1. RED: `test_cli_remote_connection_failed_exit_3` — server 未启动时 `tinydb --uri ...` 退出 3 + stderr 含 `Connection refused`
  2. GREEN: 启动时连接失败 catch + 输出 + sys.exit(3)
  3. IMPROVE: stderr 前缀 `[cli]`
- **Acceptance**: `pytest tests/cli/test_mode.py::test_cli_remote_connection_failed_exit_3` 全绿

---

### Batch 5: JDBC 协议层（Java 端，并行可早于 B6 启动）

#### T-5.1 Java 端 Frame + Codec
- **File**: `jdbc/src/main/java/org/tinydb/jdbc/protocol/Frame.java` + `Codec.java`
- **TDD**:
  1. RED: `FrameTest::testFrameRoundtrip` — `Frame(len=5, type=0x10, flags=0, payload=...)` 序列化后反序列化字段相等
  2. RED: `CodecTest::testCodecOversize` — `len=0xFFFFFF` 抛 `ProtocolException`
  3. RED: `CodecTest::testCodecReadPartialFrame` — 字节流不足时抛 `EOFException` 或返回 `null`
  4. GREEN: 用 `DataInputStream`/`DataOutputStream` 实现编解码
  5. IMPROVE: 用 `ByteBuffer` 替代 stream（性能）
- **Interfaces**: `record Frame(int len, byte type, byte flags, byte[] payload)` + `Codec.encodeHello/Ok/Query/Exec/Ping/Quit + decodeFrame`
- **Depends on**: —
- **Acceptance**: `mvn -f jdbc/pom.xml test -Dtest=CodecTest,FrameTest` 全绿

#### T-5.2 Java 端 Messages 类族
- **File**: `jdbc/src/main/java/org/tinydb/jdbc/protocol/Messages.java`
- **TDD**:
  1. RED: `MessagesTest::testEncodeHello` — `encodeHello("py-1.0")` 字节正确
  2. RED: `MessagesTest::testEncodeExecWithIntParam` — `encodeExec("SELECT ?", List.of(Param.int64(42)))` 含 type+len+data
  3. RED: `MessagesTest::testDecodeResultDone` — `decodeResultDone(...)` 字段正确
  4. GREEN: 实现 12 个消息的 encode/decode
  5. IMPROVE: 用 Java 16 records 替代 class
- **Interfaces**: 静态方法 `encodeHello/Ok/...` + `decodeFrame`
- **Depends on**: T-5.1
- **Acceptance**: `mvn test -Dtest=MessagesTest` 全绿

#### T-5.3 Java 端 SQLSTATE mapper
- **File**: `jdbc/src/main/java/org/tinydb/jdbc/protocol/ErrorCode.java` + `TinySQLException.java`
- **TDD**:
  1. RED: `ErrorCodeTest::testMapSqlstate` — `mapSqlstate("08000")` 返回 `SQLNonTransientConnectionException`
  2. RED: `ErrorCodeTest::testMapSqlstateUnknown` — `"99999"` 返回 `SQLException`
  3. GREEN: 实现 5 类映射
  4. IMPROVE: 映射表用 enum
- **Interfaces**: `static SQLException toSqlException(String code, String msg)`
- **Depends on**: —
- **Acceptance**: `mvn test -Dtest=ErrorCodeTest` 全绿

#### T-5.4 Java 端 TinyTypes (Types ↔ wire type code)
- **File**: `jdbc/src/main/java/org/tinydb/jdbc/TinyTypes.java`
- **TDD**:
  1. RED: `TinyTypesTest::testJdbcToWireInt` — `Types.INTEGER` → wire type `INT64` (0x01)
  2. RED: `TinyTypesTest::testWireToJdbcString` — wire type `STRING` → `Types.VARCHAR`
  3. GREEN: 实现 5 类映射
  4. IMPROVE: 默认 unknown → `Types.NULL`
- **Interfaces**: 静态方法 `jdbcToWireCode(int sqlType) -> byte`、`wireCodeToJdbc(byte code) -> int`
- **Depends on**: —
- **Acceptance**: `mvn test -Dtest=TinyTypesTest` 全绿

---

### Batch 6: JDBC 驱动主体（Java 端）

#### T-6.1 TinyDriver 注册 + URL 解析
- **File**: `jdbc/src/main/java/org/tinydb/jdbc/TinyDriver.java` + `jdbc/src/main/resources/META-INF/services/java.sql.Driver`
- **TDD**:
  1. RED: `TinyDriverTest::testAcceptsUrl` — `driver.acceptsURL("jdbc:tinydb://h:8520/x")` 返回 true
  2. RED: `TinyDriverTest::testRejectsMysqlUrl` — `driver.acceptsURL("jdbc:mysql://...")` 返回 false
  3. RED: `TinyDriverTest::testConnectReturnsConnection` — `DriverManager.getConnection(...)` 返回 `TinyConnection`
  4. GREEN: 实现 `TinyDriver implements Driver` + `META-INF/services` 文件
  5. IMPROVE: 缓存已建连接（按 host:port）
- **Interfaces**: `boolean acceptsURL(String url)`、`Connection connect(String url, Properties info)`
- **Depends on**: T-5.2, T-5.4
- **Acceptance**: `mvn test -Dtest=TinyDriverTest` 全绿

#### T-6.2 TinyConnection
- **File**: `jdbc/src/main/java/org/tinydb/jdbc/TinyConnection.java`
- **TDD**:
  1. RED: `TinyConnectionTest::testAutoCommit` — `setAutoCommit(false)` 后 UPDATE 不持久化到 commit
  2. RED: `TinyConnectionTest::testCommit` — commit 后可见
  3. RED: `TinyConnectionTest::testRollback` — rollback 后不可见
  4. RED: `TinyConnectionTest::testIsValid` — `isValid(1)` 发 PING 验证
  5. RED: `TinyConnectionTest::testCloseIdempotent`
  6. RED: `TinyConnectionTest::testUnsupportedMethodThrows` — `setReadOnly(true)` 抛 `SQLException`
  7. GREEN: 实现 `TinyConnection implements Connection`，所有未实现方法显式抛 `SQLFeatureNotSupportedException`
  8. IMPROVE: 加 `@Override` 注解所有方法
- **Interfaces**: 完整 `Connection` 子集
- **Depends on**: T-5.2, T-6.1
- **Acceptance**: `mvn test -Dtest=TinyConnectionTest` 全绿

#### T-6.3 TinyStatement
- **File**: `jdbc/src/main/java/org/tinydb/jdbc/TinyStatement.java`
- **TDD**:
  1. RED: `TinyStatementTest::testExecuteQuerySelect1` — `executeQuery("SELECT 1, 'a'")` 返回 ResultSet 含 1 行 2 列
  2. RED: `TinyStatementTest::testExecuteUpdateInsert` — 返回 1
  3. RED: `TinyStatementTest::testExecuteReturnsTrueForSelect` — `execute("SELECT 1")` 返回 true
  4. RED: `TinyStatementTest::testQueryTimeout` — `setQueryTimeout(1)` + server 卡住 → 1s 后抛 `SQLException`
  5. GREEN: 实现 `TinyStatement`
  6. IMPROVE: 用 `Future` + `ExecutorService` 实现 timeout
- **Interfaces**: 完整 `Statement` 子集
- **Depends on**: T-6.2
- **Acceptance**: `mvn test -Dtest=TinyStatementTest` 全绿

#### T-6.4 TinyPreparedStatement + 参数绑定
- **File**: `jdbc/src/main/java/org/tinydb/jdbc/TinyPreparedStatement.java`
- **TDD**:
  1. RED: `TinyPreparedStatementTest::testSetString` — `setString(1,"a")` 后 `executeQuery` server 收到 STRING 参数
  2. RED: `TinyPreparedStatementTest::testSetInt` — `setInt(1,42)` 后 server 收到 INT64
  3. RED: `TinyPreparedStatementTest::testSetNull` — `setNull(1, Types.INTEGER)` 后 server 收到 NULL
  4. RED: `TinyPreparedStatementTest::testClearParameters`
  5. GREEN: 实现 `TinyPreparedStatement extends TinyStatement implements PreparedStatement`
  6. IMPROVE: 参数按 wire protocol 格式打包
- **Interfaces**: 完整 `PreparedStatement` 子集
- **Depends on**: T-6.3, T-5.2, T-5.4
- **Acceptance**: `mvn test -Dtest=TinyPreparedStatementTest` 全绿

#### T-6.5 TinyResultSet + 列访问
- **File**: `jdbc/src/main/java/org/tinydb/jdbc/TinyResultSet.java`
- **TDD**:
  1. RED: `TinyResultSetTest::testNext` — `next()` × 2 返回 true/false
  2. RED: `TinyResultSetTest::testGetIntByIndex` — `getInt(1)` 返回正确值
  3. RED: `TinyResultSetTest::testGetStringByName` — `getString("name")`（大小写不敏感）
  4. RED: `TinyResultSetTest::testWasNull` — getString 返回 null 后 wasNull()=true
  5. RED: `TinyResultSetTest::testTypeCoercion` — INT 列 `getLong` 返回 long 表示
  6. GREEN: 实现 `TinyResultSet`
  7. IMPROVE: 列名查找用 TreeMap（O(log n)）
- **Interfaces**: 完整 `ResultSet` 子集
- **Depends on**: T-6.3
- **Acceptance**: `mvn test -Dtest=TinyResultSetTest` 全绿

#### T-6.6 TinyDatabaseMetaData
- **File**: `jdbc/src/main/java/org/tinydb/jdbc/TinyDatabaseMetaData.java`
- **TDD**:
  1. RED: `TinyDatabaseMetaDataTest::testGetDatabaseProductVersion` — 返回 server 版本
  2. RED: `TinyDatabaseMetaDataTest::testGetTables` — 返回 ResultSet 含所有表
  3. RED: `TinyDatabaseMetaDataTest::testSupportsTransactionsTrue`
  4. GREEN: 实现 `TinyDatabaseMetaData`
  5. IMPROVE: 缓存 tables/columns 查询结果
- **Interfaces**: 完整 `DatabaseMetaData` 子集
- **Depends on**: T-6.5
- **Acceptance**: `mvn test -Dtest=TinyDatabaseMetaDataTest` 全绿

#### T-6.7 pom.xml + JaCoCo
- **File**: `jdbc/pom.xml`
- **TDD**: 直接编辑
  1. `<sourceDirectory>1.8</sourceDirectory>` + `<target>1.8</target>`
  2. JUnit Jupiter 5.10.0（test scope）
  3. JaCoCo 0.8.11 插件
  4. 配置 `<execution>` 强制覆盖率 ≥70%
- **Acceptance**: `mvn -f jdbc/pom.xml clean verify` 通过 + JaCoCo 报告 ≥70%

---

### Batch 7: 端到端集成 + spec-merge + push

#### T-7.1 Python client ↔ Python server e2e
- **File**: `tests/integration/test_e2e_python.py`
- **TDD**:
  1. RED: `test_e2e_python_create_table_insert_select` — spawn server → client 建表 → 插 10 行 → SELECT 返回 10 行
  2. RED: `test_e2e_python_transaction_commit_rollback`
  3. RED: `test_e2e_python_concurrent_clients` — 4 个 client 并发插入 250 行无丢失
  4. GREEN: 用 pytest fixture spawn server
  5. IMPROVE: fixture 自动清理 server 进程
- **Interfaces**: 用 `tests/conftest.py` 的 `tinydb_server` fixture
- **Depends on**: B2, B3
- **Acceptance**: `pytest tests/integration -v -m network` 全绿

#### T-7.2 Java JDBC ↔ Python server e2e
- **File**: `jdbc/src/test/java/org/tinydb/jdbc/EndToEndTest.java`
- **TDD**:
  1. RED: `EndToEndTest::testFullCrudWithTransaction`
  2. RED: `EndToEndTest::testPreparedStatementCrud`
  3. RED: `EndToEndTest::testDatabaseMetaDataGetTables`
  4. GREEN: 用 `ProcessBuilder` 启动 `tinydb-server`
  5. IMPROVE: JUnit `@BeforeAll`/`@AfterAll` 管理 server 生命周期
- **Interfaces**: spawn server + JDBC CRUD
- **Depends on**: B6
- **Acceptance**: `mvn -f jdbc/pom.xml test -Dtest=EndToEndTest` 全绿

#### T-7.3 文档
- **File**: `docs/NETWORK.md`、`docs/JDBC.md`、`README.md`
- **TDD**: 直接编写
  1. NETWORK.md: 协议格式 + server 启动示例 + Client API 示例
  2. JDBC.md: URL 格式 + 5 分钟 Hello World + 支持的方法清单
  3. README.md: 新增 "C/S Architecture" 与 "JDBC" 章节
- **Acceptance**: 文档可读且示例可运行

#### T-7.4 spec-merge
- **File**: `specs/`（顶层）
- **TDD**:
  1. 把 `changes/tinydb-v0.3/specs/*.md` reorganize 到 `specs/<cap>/spec.md`
     - `network-server.md` → `specs/network-server/spec.md`
     - `network-client.md` → `specs/network-client/spec.md`
     - `wire-protocol.md` → `specs/wire-protocol/spec.md`
     - `cli-cs.md` → `specs/cli/spec.md`（追加 v0.3 ADDED Requirements）
     - `jdbc-driver.md` → `specs/jdbc-driver/spec.md`
  2. 与 v0.2 specs/ 无冲突（v0.3 是纯 ADDED）
  3. 删除 `changes/tinydb-v0.3/specs/`
- **Acceptance**: `tree specs/` 显示新增 5 个 cap + v0.2 已有 cap 完整

#### T-7.5 release
- **File**: git 操作
- **TDD**:
  1. 跑全量 pytest + 全量 mvn test
  2. 覆盖率：Python ≥80% + Java ≥70%
  3. scope audit（v0.3 proposal > Out 无违反）
  4. `git add -A && git commit -m "feat(v0.3): C/S architecture + protocol + CLI dual-mode + JDBC driver"`
  5. `git tag tinydb-v0.3.0 && git push origin master --tags`
- **Acceptance**: `git ls-remote --tags origin | grep v0.3.0` 存在