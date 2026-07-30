# Spec: Wire Protocol（v0.3）

## ADDED Requirements

### REQ-PROTO-1: 帧格式
The system MUST 使用长度前缀帧：每个帧由 `[LEN(4B BE)][TYPE(1B)][FLAGS(1B)][PAYLOAD(LEN-2 字节)]` 组成；最大帧长度 `16777215`（`0xFFFFFF`）；超过限制的帧视为协议错误并关闭连接。

#### Scenario: 正常帧
- WHEN 客户端发帧 `LEN=0x00000005 TYPE=0x10 FLAGS=0x00 PAYLOAD="hello"`
- THEN server 解析为长度 5、类型 0x10、标志 0、负载 5 字节
- AND 不抛错

#### Scenario: 超长帧
- WHEN 客户端发 `LEN=0xFFFFFF`
- THEN server 关闭连接
- AND 客户端收到 `RESULT_ERROR`（如已建立）或 EOF
- AND 错误码 `08000`（连接异常）

#### Scenario: 长度不匹配
- WHEN 客户端发 `LEN=10` 但 socket 提前关闭
- THEN server 关闭连接
- AND 抛出 `ProtocolError`（日志记录）

### REQ-PROTO-2: 消息类型与方向
The system MUST 定义以下消息类型（`TYPE` 字段）：

| TYPE | 名称 | 方向 | 说明 |
|------|------|------|------|
| `0x01` | HELLO | C→S | 客户端握手 |
| `0x02` | OK | S→C | 握手/命令成功应答 |
| `0x03` | ERR | S→C | 错误应答 |
| `0x10` | QUERY | C→S | 单条 SQL（透传） |
| `0x11` | EXEC | C→S | SQL + 参数列表 |
| `0x20` | RESULT_HEADER | S→C | 结果集元数据（列名、类型） |
| `0x21` | RESULT_ROW | S→C | 单行数据 |
| `0x22` | RESULT_DONE | S→C | 结果集结束（含 rowcount/last_insert_id） |
| `0x23` | RESULT_ERROR | S→C | 结果级错误 |
| `0x30` | PING | C↔S | 心跳请求 |
| `0x31` | PONG | S↔C | 心跳应答 |
| `0xFE` | QUIT | C→S | 优雅关闭 |

#### Scenario: 消息类型校验
- WHEN 客户端发 `TYPE=0x99`（未知）
- THEN server 回 `ERR`（type=0x03, code=`08000`）后关闭连接

### REQ-PROTO-3: HELLO 握手（无认证占位）
The system MUST 在客户端建立 TCP 连接后第一个帧发 `HELLO`；server 收到后回 `OK`（含 server 版本字符串）；HELLO 携带 client 标识（任意 UTF-8 字符串，最大 64 字节）；v0.3 阶段不校验认证信息，留作 v0.4 接口。

#### Scenario: 正常 HELLO
- WHEN 客户端发 HELLO `client="py-tinydb-1.0"`
- THEN server 回 OK `version="tinydb-0.3.0"`
- AND 进入命令循环

#### Scenario: 缺失 HELLO
- WHEN 客户端直接发 QUERY
- THEN server 回 ERR `code=08000 msg="HELLO required"`
- AND 关闭连接

#### Scenario: HELLO 超长
- WHEN 客户端 HELLO `client` 字段 > 64 字节
- THEN server 回 ERR `code=08000 msg="HELLO client too long"` 后关闭连接

### REQ-PROTO-4: QUERY 消息
The system MUST 支持 QUERY 帧：PAYLOAD 为 UTF-8 SQL 字符串；长度受帧上限约束；空 SQL 视为错误（code=`42000`）。

#### Scenario: 简单查询
- WHEN 客户端发 QUERY `SELECT 1`
- THEN server 回 RESULT_HEADER（1 列 `?column?` 类型 INT）+ RESULT_ROW `[1]` + RESULT_DONE `rowcount=1`

#### Scenario: 空 SQL
- WHEN 客户端发 QUERY ``（空字符串）
- THEN server 回 RESULT_ERROR `code=42000 msg="empty SQL"`

#### Scenario: SQL 含 UTF-8
- WHEN 客户端发 QUERY `SELECT '你好'`
- THEN server 回包含中文字符串的行
- AND 不抛 Unicode 错误

### REQ-PROTO-5: EXEC 消息（带参数）
The system MUST 支持 EXEC 帧：PAYLOAD = `[SQL_LEN(4B BE)][SQL(N bytes)][PARAM_COUNT(2B BE)][PARAM_i_TYPE(1B)][PARAM_i_LEN(4B BE)][PARAM_i_DATA]`；参数类型至少支持 NULL/INT64/FLOAT64/STRING/BOOL；STRING 按 UTF-8；参数数量受 `max_params`（默认 `1024`）约束。

#### Scenario: 带参数 EXEC
- WHEN 客户端发 EXEC `SQL="SELECT * FROM t WHERE id=?"` + 参数 `[INT64, 42]`
- THEN server 用 `42` 替换 `?` 后执行
- AND 返回对应结果集

#### Scenario: 参数类型不匹配
- WHEN 客户端发 EXEC 参数类型声明 `BOOL` 但 SQL 比较 INT 列
- THEN server 回 RESULT_ERROR `code=22000 msg="type mismatch"`
- AND 事务回滚（如已开启）

#### Scenario: 超多参数
- WHEN 客户端发 EXEC 参数数 `2000`（超过 `max_params=1024`）
- THEN server 回 RESULT_ERROR `code=08000 msg="too many params"`

### REQ-PROTO-6: RESULT_HEADER / RESULT_ROW / RESULT_DONE 序列
The system MUST 在成功查询时按以下顺序响应：
1. `RESULT_HEADER`：列数 (2B BE) + 列名（每列 `[NAME_LEN(1B)][NAME(N UTF-8)][TYPE(1B)]`）+ SQLSTATE（如为命令）
2. `RESULT_ROW` × N：每行 `[COL_COUNT][COL_i_TYPE][COL_i_VALUE]`
3. `RESULT_DONE`：`rowcount(8B BE) + last_insert_id(8B BE) + status_flags(1B)`

`RESULT_DONE` 的 `status_flags` 位定义：
- `0x01` AUTOCOMMIT
- `0x02` IN_TRANSACTION
- `0x04` NO_RESULT（如 INSERT/UPDATE）

#### Scenario: SELECT 返回
- WHEN 执行 `SELECT id, name FROM t` 返回 2 行
- THEN server 发 RESULT_HEADER（2 列）+ 2 个 RESULT_ROW + 1 个 RESULT_DONE `rowcount=2`

#### Scenario: INSERT 返回
- WHEN 执行 `INSERT INTO t VALUES (1,'a')` 影响 1 行
- THEN server 发 RESULT_DONE `rowcount=1 last_insert_id=1 status_flags=0x05`（AUTOCOMMIT + NO_RESULT）
- AND 不发 RESULT_HEADER/ROW

### REQ-PROTO-7: 错误码（SQLSTATE 对齐）
The system MUST 在 `RESULT_ERROR` / `ERR` 帧 PAYLOAD = `[CODE(5B ASCII)][MSG_LEN(2B BE)][MSG(N UTF-8)]`，至少支持以下 code：

| Code | 含义 |
|------|------|
| `08000` | 连接异常 |
| `22000` | 数据异常（类型不匹配、除零、约束冲突） |
| `25000` | 事务状态非法（未开启事务时 COMMIT） |
| `42000` | 语法错误 |
| `HY000` | 通用错误 |

#### Scenario: 语法错误
- WHEN 客户端发 `SELECT FROM`
- THEN server 回 RESULT_ERROR `code=42000 msg="syntax error at 'FROM'"`

#### Scenario: 唯一约束冲突
- GIVEN 表 t(id PRIMARY KEY) 已有 id=1
- WHEN 客户端发 `INSERT INTO t VALUES (1, 'x')`
- THEN server 回 RESULT_ERROR `code=22000 msg="UNIQUE constraint violated"`

### REQ-PROTO-8: 心跳帧 PING/PONG
The system MUST 支持 PING/PONG 帧；PAYLOAD 可携带客户端纳秒时间戳（8B BE）；PONG 回显相同时间戳便于 RTT 计算。

#### Scenario: PING RTT
- WHEN 客户端发 PING（timestamp=T）
- THEN server 回 PONG（timestamp=T）
- AND 客户端计算 RTT = now - T

### REQ-PROTO-9: QUIT 优雅关闭
The system MUST 支持 QUIT 帧；server 收到 QUIT 后回 OK 然后关闭 socket；QUIT 不必等待响应（fire-and-forget）。

#### Scenario: 优雅关闭
- WHEN 客户端发 QUIT
- THEN server 回 OK 后关闭 socket
- AND 客户端在下一次 recv 时收到 EOF
---

> **合并说明**：本 spec 是 `changes/tinydb-v0.3/specs/wire-protocol/spec.md`（v0.3 ADDED 要求）的合并版本，作为主 spec 的权威版本。原始 delta 仍保留在各自 change 目录作为归档。

