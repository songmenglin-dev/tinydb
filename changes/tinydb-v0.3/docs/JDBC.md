# tinydb JDBC Driver (v0.3)

## What this is

`tinydb-jdbc-0.3.0.jar` is a **Type-4** JDBC driver for tinydb v0.3+. It speaks
the native tinydb wire protocol over TCP directly — no ODBC bridge, no
middleware. Drop the JAR into your application's classpath and connect with
the standard `java.sql.DriverManager` API.

## Requirements

- **Java 8 or newer** (JDBC 4.2 baseline)
- **`tinydb-server` running** on a reachable host (start with `tinydb-server --db-path data.db`)
- **JAR `< 200 KB`** — no third-party runtime dependencies

## Installation

### Maven

```xml
<dependency>
    <groupId>org.tinydb</groupId>
    <artifactId>tinydb-jdbc</artifactId>
    <version>0.3.0</version>
</dependency>
```

### Gradle

```groovy
implementation 'org.tinydb:tinydb-jdbc:0.3.0'
```

### Manual

Download `tinydb-jdbc-0.3.0.jar` and add it to the classpath.

The driver is registered automatically via `META-INF/services/java.sql.Driver`.

## Connection URL

```
jdbc:tinydb://[host][:port]/[database]
```

| Component | Default | Notes |
|-----------|---------|-------|
| `host` | `127.0.0.1` | tinydb-server host |
| `port` | `8520` | tinydb-server port |
| `database` | (ignored in v0.3) | accepted for forward-compat with v0.4 multi-DB |

Examples:

```
jdbc:tinydb://localhost:8520
jdbc:tinydb://db.example.com:9527/mydb
jdbc:tinydb://192.168.1.10:8520/
```

## Supported API (JDBC 4.2 minimum subset)

| Interface | Methods implemented |
|-----------|---------------------|
| `Connection` | `close`, `isClosed`, `isValid`, `getAutoCommit`, `setAutoCommit`, `commit`, `rollback`, `getCatalog`, `setCatalog`, `createStatement`, `prepareStatement`, `getMetaData`, `nativeSQL` |
| `Statement` | `executeQuery`, `executeUpdate`, `execute`, `getResultSet`, `getUpdateCount`, `getConnection`, `setQueryTimeout`, `getQueryTimeout`, `close` |
| `PreparedStatement` | `setString`, `setInt`, `setLong`, `setDouble`, `setBoolean`, `setNull`, `setObject`, `clearParameters`, `executeQuery`, `executeUpdate`, `execute` |
| `ResultSet` | `next`, `close`, `wasNull`, `getString/Int/Long/Double/Boolean/Object` by column index AND name, `getMetaData`, `findColumn` |
| `DatabaseMetaData` | `getURL`, `getUserName`, `getDatabaseProductName`, `getDatabaseProductVersion`, `getDriverName`, `getDriverVersion`, `supportsTransactions`, `getTables`, `getColumns` |

**Anything else throws `SQLException("not supported in v0.3")`** rather than
silently no-op. This is deliberate: application code that relies on the
exception behaviour (e.g. `setReadOnly`) fails loudly instead of silently
producing wrong results.

## 5-minute Hello World

```java
import java.sql.*;
import org.tinydb.jdbc.TinyDriver;

public class Hello {
    public static void main(String[] args) throws Exception {
        // 1. Load the driver (optional with JDBC 4.0+, but explicit is fine)
        Class.forName("org.tinydb.jdbc.TinyDriver");

        // 2. Connect
        try (Connection conn = DriverManager.getConnection(
                "jdbc:tinydb://127.0.0.1:8520/")) {

            // 3. Create schema (autoCommit is true by default)
            try (Statement s = conn.createStatement()) {
                s.executeUpdate(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, " +
                    "name VARCHAR(64), age INTEGER)");
                s.executeUpdate(
                    "INSERT INTO users VALUES (1, 'Alice', 30)");
                s.executeUpdate(
                    "INSERT INTO users VALUES (2, 'Bob', 25)");
            }

            // 4. Query via PreparedStatement
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT id, name FROM users WHERE age >= ?")) {
                ps.setInt(1, 18);
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        System.out.printf("%d %s%n",
                                rs.getInt("id"),
                                rs.getString("name"));
                    }
                }
            }

            // 5. Transaction
            conn.setAutoCommit(false);
            try (PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO users VALUES (?, ?, ?)")) {
                ps.setInt(1, 3);
                ps.setString(2, "Carol");
                ps.setInt(3, 40);
                ps.executeUpdate();
                conn.commit();
            } catch (SQLException e) {
                conn.rollback();
                throw e;
            }
        }
    }
}
```

Expected output:

```
1 Alice
2 Bob
```

## SQLSTATE → JDBC Exception Mapping

The wire-protocol SQLSTATE codes map to JDBC exception subclasses:

| Server SQLSTATE | JDBC Exception |
|-----------------|----------------|
| `08000` | `SQLNonTransientConnectionException` |
| `22000` (constraint) | `SQLIntegrityConstraintViolationException` |
| `22000` (other) | `SQLDataException` |
| `25000` | `SQLInvalidTransactionStateException` |
| `42000` | `SQLSyntaxErrorException` |
| `HY000` | `SQLException` |

Application code can catch the most specific exception class to handle each
category properly.

## Pooling

The driver does **not** ship an internal connection pool (one Java thread per
connection; matches the wire-protocol session model). For high-concurrency
applications, use an external pool:

- **HikariCP** — `https://github.com/brettwooldridge/HikariCP`
- **c3p0** — `https://github.com/swaldman/c3p0`

Example with HikariCP:

```java
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

HikariConfig cfg = new HikariConfig();
cfg.setJdbcUrl("jdbc:tinydb://db.example.com:8520/");
cfg.setMaximumPoolSize(20);
cfg.setMinimumIdle(2);
cfg.setConnectionTimeout(5_000);
HikariDataSource ds = new HikariDataSource(cfg);
```

## Limitations (v0.3)

- **No TLS.** Connection is plaintext. Use SSH tunnel or VPN for production.
- **No authentication.** HELLO is currently a no-op handshake. Bind to localhost or use network ACL until v0.4.
- **No savepoints.** `setSavepoint` throws `SQLException`.
- **No `executeBatch()`.** Use individual `executeUpdate()` calls, or `tinydb.client.execute_many` from Python.
- **No scrollable ResultSets.** Forward-only.
- **No type metadata in ResultSet.** `getMetaData().getColumnType(i)` returns `Types.OTHER` for some columns.
- **JSON columns / arrays / vectors** not supported (deferred to v0.4+).
- **Single database per server** in v0.3. The `/database` URL segment is accepted but ignored.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `No suitable driver found for jdbc:tinydb://...` | JAR not on classpath | Add `tinydb-jdbc-0.3.0.jar` to classpath |
| `SQLNonTransientConnectionException: Connection refused` | `tinydb-server` not running or wrong port | Start server: `tinydb-server --db-path /tmp/x.db` |
| `SQLException: not supported in v0.3` | Calling an unsupported JDBC method | Check the supported API table above; refactor or upgrade |
| `SQLSyntaxErrorException` | Server-side SQL parse error | Check `getMessage()` for the line/column hint |
| `SQLIntegrityConstraintViolationException` | UNIQUE/FOREIGN KEY violation | Inspect the constraint on the server |

## Building from source

```bash
mvn -f jdbc/pom.xml clean package
# produces jdbc/target/tinydb-jdbc-0.3.0.jar
```

Run tests:

```bash
mvn -f jdbc/pom.xml test
# runs all unit tests + EndToEndTest (which spawns tinydb-server)
```

Coverage report:

```bash
mvn -f jdbc/pom.xml verify
# target/site/jacoco/index.html — must show ≥70% line coverage
```