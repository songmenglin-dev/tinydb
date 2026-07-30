# cli-cs

## Requirements

### REQ-CLI-CS-1: 启动模式选择
The system MUST 在 `tinydb` 命令行入口接受 `--file PATH` 或 `--uri URI`（互斥）；`--file` 走 embedded（直接 `tinydb.api.Database(path)`），`--uri` 走 remote（`tinydb.client.Client`）；两者都未给时默认 `--file` 并要求后续 `open <path>` 元命令。

#### Scenario: 显式 embedded
- WHEN `tinydb --file /tmp/test.db`
- THEN CLI 启动后等价于 v0.2 行为
- AND `.tables` 显示本地表的元数据

#### Scenario: 显式 remote
- WHEN `tinydb --uri tinydb://127.0.0.1:8520`
- THEN CLI 启动后通过 `Client("127.0.0.1", 8520)` 连接
- AND `.tables` 经由 `Client.execute("SELECT name FROM sqlite_master")` 或专用元命令实现

#### Scenario: 互斥冲突
- WHEN `tinydb --file a.db --uri tinydb://...`
- THEN CLI 启动失败，stderr 输出 `error: --file and --uri are mutually exclusive`
- AND 返回 exit code `2`

### REQ-CLI-CS-2: URI 解析
The system MUST 接受 URI 形式 `tinydb://[user[:pass]@]host[:port]/[database]`，其中 `user`/`pass` v0.3 阶段忽略；`database` 段 v0.3 阶段忽略。

#### Scenario: 标准 URI
- WHEN `tinydb --uri tinydb://db.example.com:9527/mydb`
- THEN 解析为 host=`db.example.com`、port=`9527`、database=`mydb`（忽略）

#### Scenario: 缺省端口
- WHEN `tinydb --uri tinydb://localhost/x`
- THEN 端口默认 `8520`

#### Scenario: 非法 URI
- WHEN `tinydb --uri http://example.com`
- THEN 解析失败，stderr `error: invalid URI scheme 'http', expected 'tinydb'`
- AND 返回 exit code `2`

### REQ-CLI-CS-3: 远程模式 SQL 执行
The system MUST 在 remote 模式下，所有非元命令输入（含多行编辑后的完整 SQL）通过 `Client.execute(sql)` 派发，结果以 v0.2 同款 ASCII 表格输出。

#### Scenario: 远程 SELECT
- GIVEN remote 模式
- WHEN 输入 `SELECT id, name FROM users;`
- THEN 经由 `Client.execute` 派发
- AND 返回 ASCII 表格 + `1000 rows in set (12.34ms)`

#### Scenario: 远程 INSERT
- GIVEN remote 模式
- WHEN 输入 `INSERT INTO users VALUES (1,'Alice');`
- THEN 返回 `Query OK, 1 row affected (3.21ms)`

#### Scenario: 远程错误
- GIVEN remote 模式
- WHEN 输入 `SELECT FROM`（语法错误）
- THEN 显示 `ERROR 42000: syntax error at 'FROM'`
- AND 不退出 CLI

### REQ-CLI-CS-4: 元命令 .connect / .disconnect
The system MUST 在 remote 模式中提供 `.connect <uri>`（动态切换连接）与 `.disconnect`（关闭当前连接回到未连接状态）；连接断开时执行的命令返回错误元命令提示重连。

#### Scenario: 动态切换
- GIVEN 启动 `--uri tinydb://A:8520`
- WHEN `.connect tinydb://B:9527`
- THEN 关闭 A 连接，建立 B 连接
- AND `.status` 显示新连接

#### Scenario: 断开后执行
- WHEN `.disconnect` 后执行 `SELECT 1`
- THEN 显示 `not connected; use .connect <uri> or restart with --uri`
- AND CLI 不退出

### REQ-CLI-CS-5: 元命令 .status / .server-info
The system MUST 提供 `.status`（显示当前模式 + 连接信息）与 `.server-info`（仅 remote 模式，调用 `EXEC "SELECT @@version"` 或专用元命令展示 server 版本、当前数据库、最大连接数）。

#### Scenario: status embedded
- GIVEN embedded 模式 `--file /tmp/test.db`
- WHEN `.status`
- THEN 显示 `mode=embedded path=/tmp/test.db`

#### Scenario: status remote
- GIVEN remote 模式
- WHEN `.status`
- THEN 显示 `mode=remote uri=tinydb://... state=connected rtt=1.2ms`

#### Scenario: server-info
- GIVEN remote 模式
- WHEN `.server-info`
- THEN 显示 server 版本、protocol 版本、max_conns、当前 conns

### REQ-CLI-CS-6: 嵌入式模式保留 v0.2 全部元命令
The system MUST 在 embedded 模式下保留 v0.2 全部元命令：`.tables` / `.schema <table>` / `.explain <SQL>` / `.history` / `.help` / `.quit` / `.open <path>`（新增用于运行时切换文件）；远程模式下 `.schema` / `.tables` 经由 server 端元数据查询实现。

#### Scenario: embedded .tables
- GIVEN embedded 模式且 db 有 2 张表
- WHEN `.tables`
- THEN 显示表名列表

#### Scenario: remote .tables
- GIVEN remote 模式
- WHEN `.tables`
- THEN 经由 `EXEC ".tables"` 或专用查询获取并显示

### REQ-CLI-CS-7: 多行编辑与语法高亮保留
The system MUST 在两种模式下保留 v0.2 的多行编辑、反斜杠/未闭合引号续行、SQL 关键字高亮、历史持久化、行内编辑能力；无 `prompt_toolkit` 时降级为 v0.1 行为。

#### Scenario: 多行续行
- WHEN 输入 `SELECT *\` <回车> `FROM t;`
- THEN 进入续行模式
- AND 执行整段 SQL

### REQ-CLI-CS-8: 连接失败错误信息
The system MUST 在 `--uri` 启动后连接失败时，stderr 输出 `[cli] failed to connect to <uri>: <reason>` 并返回 exit code `3`；CLI 不进入 REPL。

#### Scenario: server 未启动
- WHEN `tinydb --uri tinydb://127.0.0.1:9527` 但 server 未启动
- THEN stderr 输出 `[cli] failed to connect to tinydb://127.0.0.1:9527: Connection refused`
- AND exit code `3`
