# Spec: JDBC Driver 兼容 JAR（v0.3）

## ADDED Requirements

### REQ-JDBC-1: Driver 注册
The system MUST 提供 `org.tinydb.jdbc.TinyDriver` 实现 `java.sql.Driver`；通过 `META-INF/services/java.sql.Driver` 文件自动注册；URL 前缀 `jdbc:tinydb://` 触发本驱动处理。

#### Scenario: 自动注册
- GIVEN classpath 包含 `tinydb-jdbc-0.3.0.jar`
- WHEN `DriverManager.getConnection("jdbc:tinydb://127.0.0.1:8520/")`
- THEN 自动选择 `TinyDriver`
- AND 返回 `TinyConnection`

#### Scenario: URL 解析
- WHEN URL `jdbc:tinydb://192.168.1.10:9527/mydb`
- THEN 解析为 host=`192.168.1.10`、port=`9527`、database=`mydb`（v0.3 忽略）

#### Scenario: 非法 URL
- WHEN URL `jdbc:mysql://...`
- THEN `getConnection` 抛出 `SQLException("No suitable driver")`

### REQ-JDBC-2: TinyConnection
The system MUST 提供 `TinyConnection implements java.sql.Connection`，实现：
- `close()`
- `isClosed() -> boolean`
- `isValid(int timeout) -> boolean`（发 PING 验证）
- `getAutoCommit() / setAutoCommit(boolean)`
- `commit() / rollback()`
- `getCatalog() / setCatalog(String)`（v0.3 阶段仅 getter 返回 URL 中的 database 名）
- `createStatement() / prepareStatement(String sql)`
- `getMetaData() -> TinyDatabaseMetaData`
- `nativeSQL(String sql) -> String`（透传）
- `close()` 幂等

未实现方法必须显式抛 `SQLException("not supported in v0.3")`，不得静默 no-op。

#### Scenario: autoCommit true → false
- WHEN `setAutoCommit(false)`
- THEN 后续 execute 在显式 commit 前不持久化

#### Scenario: commit
- GIVEN autoCommit=false
- WHEN `executeUpdate("INSERT...")` 然后 `commit()`
- THEN row 持久化

#### Scenario: rollback
- GIVEN autoCommit=false
- WHEN `executeUpdate("INSERT...")` 然后 `rollback()`
- THEN row 不持久化

#### Scenario: close 幂等
- WHEN `close()` 两次
- THEN 不抛错
- AND 第二次 `isClosed() == true`

### REQ-JDBC-3: TinyStatement
The system MUST 提供 `TinyStatement implements java.sql.Statement`，实现：
- `executeQuery(String sql) -> ResultSet`
- `executeUpdate(String sql) -> int`
- `execute(String sql) -> boolean`
- `getResultSet() -> ResultSet`
- `getUpdateCount() -> int`
- `getConnection() -> Connection`
- `close()`
- `setQueryTimeout(int seconds)` / `getQueryTimeout()`

#### Scenario: executeQuery
- WHEN `executeQuery("SELECT 1, 'a'")`
- THEN 返回 `ResultSet` 含 1 行 2 列
- AND `rs.next() == true`，`rs.getInt(1) == 1`，`rs.getString(2) == "a"`

#### Scenario: executeUpdate
- WHEN `executeUpdate("INSERT INTO t VALUES (1,'x')")`
- THEN 返回 `1`
- AND `getResultSet() == null`

#### Scenario: query timeout
- GIVEN `setQueryTimeout(1)`
- WHEN 执行卡住
- THEN 1s 后抛 `SQLException("query timeout")`

### REQ-JDBC-4: TinyPreparedStatement
The system MUST 提供 `TinyPreparedStatement extends TinyStatement implements java.sql.PreparedStatement`，实现：
- `setString(int parameterIndex, String x)`
- `setInt(int parameterIndex, int x)` / `setLong(parameterIndex, long x)` / `setDouble(parameterIndex, double x)` / `setBoolean(parameterIndex, boolean x)`
- `setNull(int parameterIndex, int sqlType)`
- `setObject(int parameterIndex, Object x)`
- `executeQuery() / executeUpdate() / execute()`
- `clearParameters()`
- `close()`

通过 wire protocol 的 `EXEC` 帧携带参数；参数类型编码与 `REQ-PROTO-5` 对齐。

#### Scenario: PreparedStatement
- WHEN `ps = conn.prepareStatement("SELECT ? + ? AS s")`
- AND `ps.setInt(1, 1)` / `ps.setInt(2, 2)`
- AND `rs = ps.executeQuery()`
- THEN `rs.next()` → `rs.getInt("s") == 3`

#### Scenario: 参数 NULL
- WHEN `ps.setNull(1, Types.INTEGER)`
- THEN server 收到 NULL 参数并按 NULL 处理

#### Scenario: clearParameters 复用
- WHEN 同一 ps 先 setString(1,"a") 然后 clearParameters() 然后 setInt(1,1)
- THEN 参数以 [1] 执行，不含旧值

### REQ-JDBC-5: TinyResultSet
The system MUST 提供 `TinyResultSet implements java.sql.ResultSet`，实现：
- `next() -> boolean`
- `close()`
- `wasNull() -> boolean`
- `getString(int|String) / getInt(int|String) / getLong / getDouble / getBoolean / getObject`
- `getMetaData() -> ResultSetMetaData`（列名、类型）
- `findColumn(String) -> int`

#### Scenario: getXxx 按列号
- WHEN `rs.getInt(1)` / `rs.getString(2)`
- THEN 返回正确值

#### Scenario: getXxx 按列名
- WHEN `rs.getString("name")`
- THEN 返回该列值（大小写不敏感）

#### Scenario: 类型转换兼容
- WHEN `rs.getLong(int)` 用于 INT 列
- THEN 返回 long 表示（精度无损）

#### Scenario: wasNull
- WHEN 当前行某列 NULL
- THEN `rs.getString(col)` 返回 null
- AND `rs.wasNull() == true`

### REQ-JDBC-6: TinyDatabaseMetaData
The system MUST 提供 `TinyDatabaseMetaData implements java.sql.DatabaseMetaData`，实现最小子集：
- `getURL() -> String`
- `getUserName() -> String`（v0.3 返回 `"tinydb"`）
- `getDatabaseProductName() -> String`（返回 `"tinydb"`）
- `getDatabaseProductVersion() -> String`（返回 server 版本）
- `getDriverName() -> String`（返回 `"tinydb-jdbc"`）
- `getDriverVersion() -> String`（返回 `"0.3.0"`）
- `supportsTransactions() -> true`
- `supportsResultSetConcurrency(int, int)` → `(FORWARD_ONLY, READ_ONLY) = true`
- `getTables(catalog, schema, pattern, types)` → 返回系统表元数据 ResultSet
- `getColumns(...)` → 返回列元数据 ResultSet

未实现方法必须抛 `SQLException("not supported in v0.3")`。

#### Scenario: getDatabaseProductVersion
- WHEN `conn.getMetaData().getDatabaseProductVersion()`
- THEN 返回 server 版本字符串（如 `"0.3.0"`）

#### Scenario: getTables
- WHEN `meta.getTables(null, null, "%", null)`
- THEN 返回 ResultSet 含所有用户表名

### REQ-JDBC-7: 异常映射
The system MUST 将 server 端 SQLSTATE 映射到 `java.sql.SQLException` 子类：
- `08000` → `SQLNonTransientConnectionException`
- `22000` → `SQLIntegrityConstraintViolationException`（如约束）/ `SQLDataException`（其他数据异常）
- `25000` → `SQLTransactionRollbackException` / `SQLInvalidTransactionStateException`
- `42000` → `SQLSyntaxErrorException`
- `HY000` → `SQLException`

每条 `SQLException` 携带 server 返回的 msg 作为消息，server `SQLSTATE` 作为 `SQLState`。

#### Scenario: 语法错误
- WHEN server 返回 42000
- THEN 客户端抛 `SQLSyntaxErrorException`

#### Scenario: 约束冲突
- WHEN server 返回 22000 (UNIQUE)
- THEN 客户端抛 `SQLIntegrityConstraintViolationException`

### REQ-JDBC-8: JAR 打包
The system MUST 通过 Maven 生成 `tinydb-jdbc-0.3.0.jar`；`pom.xml` 配置 Java 8 source/target；测试用 `junit-jupiter:5.10.0`；JAR 体积 `<200KB`（无依赖 jar）。

#### Scenario: mvn package
- WHEN `mvn -f jdbc/pom.xml clean package`
- THEN 生成 `jdbc/target/tinydb-jdbc-0.3.0.jar`
- AND 体积 `<200KB`

#### Scenario: 单元测试
- WHEN `mvn -f jdbc/pom.xml test`
- THEN 全部 JUnit 测试通过
- AND 覆盖率 ≥70%（JaCoCo）

### REQ-JDBC-9: 端到端集成测试
The system MUST 在 JUnit 测试套件中提供 `EndToEndTest`，通过 `ProcessBuilder` 启动 `tinydb-server` 进程，初始化测试 schema，跑完整 CRUD + 事务后清理。

#### Scenario: e2e 启动 server
- WHEN `EndToEndTest.setUp()`
- THEN spawn `tinydb-server --db-path /tmp/e2e.db --port <random>`
- AND 等待 server 就绪（TCP connect 成功）
- AND 建表 + 插入 100 行测试数据

#### Scenario: e2e 完整流程
- WHEN JDBC 客户端跑 SELECT/INSERT/UPDATE/DELETE/COMMIT/ROLLBACK
- THEN 所有断言通过
- AND tearDown 关闭 server 进程 + 删除临时 db
---

> **合并说明**：本 spec 是 `changes/tinydb-v0.3/specs/jdbc-driver/spec.md`（v0.3 ADDED 要求）的合并版本，作为主 spec 的权威版本。原始 delta 仍保留在各自 change 目录作为归档。

