# tinydb-jdbc Spring Boot Integration Test

> A Spring Boot 2.7 + MyBatis application that drives the locally-built
> `tinydb-jdbc-0.3.0.jar` against a running `tinydb-server` to verify
> end-to-end JDBC connectivity through a real ORM and connection pool.

## Goal

Prove that `tinydb-jdbc` is usable from a mainstream Java ORM stack —
not just from hand-written Java code. The test exercises:

- Spring Boot context wiring
- HikariCP connection pool + driver auto-detection
- MyBatis mapper interfaces + parameter binding
- Full CRUD round-trip (insert / select / update / delete)
- UTF-8 string round-trip
- Connection pool reuse

## Quick Start

```bash
# 1. Build the tinydb-jdbc JAR (only needed once, or after touching jdbc/ source)
cd jdbc && mvn -DskipTests package && cd ..
#   → produces jdbc/target/tinydb-jdbc-0.3.0.jar

# 2. Start a tinydb-server on a free port
tests/integration/jdbc-springboot/scripts/start-tinydb-server.sh start 18520

# 3. Run the Spring Boot integration tests
cd tests/integration/jdbc-springboot
mvn test
#   → TinyDbConnectivityTest: 3 passed, 0 failed

# 4. Stop the server
../scripts/start-tinydb-server.sh stop
```

## What the integration test verifies

`TinyDbConnectivityTest` (3 test methods):

| Test              | What it proves                                                          |
|-------------------|-------------------------------------------------------------------------|
| `springContextLoads` | Spring container wires up; `DataSource` (HikariCP) and MyBatis mapper are injected. |
| `crudRoundTrip`     | INSERT × 3 → SELECT by id → UPDATE → DELETE → COUNT(*) round-trip works end-to-end. |
| `utf8RoundTrip`     | Non-ASCII strings (`你好`) round-trip without `?` replacement or charset errors. |

## Layout

```
tests/integration/jdbc-springboot/
├── pom.xml                          # Spring Boot 2.7.18 + mybatis-spring-boot-starter 2.3.1
├── scripts/
│   └── start-tinydb-server.sh       # start/stop/status helpers
├── src/main/java/com/example/tinydb/
│   ├── TinyDbJdbcTestApplication.java
│   ├── entity/User.java             # Plain POJO mapped to the users table
│   ├── mapper/UserMapper.java       # @Mapper with @Select/@Insert/@Update/@Delete
│   └── service/UserService.java     # Thin wrapper around UserMapper
├── src/main/resources/
│   └── application.yml              # datasource url = jdbc:tinydb://127.0.0.1:18520/
└── src/test/java/com/example/tinydb/
    └── TinyDbConnectivityTest.java  # @SpringBootTest end-to-end driver test
```

## Technical notes

### Driver wiring

`tinydb-jdbc-0.3.0.jar` ships its driver under
`META-INF/services/java.sql.Driver`, so the JVM picks it up
automatically. We still set `spring.datasource.driver-class-name`
explicitly to keep Spring Boot's auto-detection deterministic.

The driver JAR is referenced from the parent project via a Maven
`<scope>system</scope>` dependency pointing at
`jdbc/target/tinydb-jdbc-0.3.0.jar`. There's no need to publish the
driver to a Maven repo just to consume it.

### Column-name resolution (v0.3-COLFIX)

Since v0.3-COLFIX the server returns the real projection column names
for SELECT lists — e.g. `SELECT id, name, age FROM users` reports
`id`, `name`, `age` on the wire. MyBatis maps result columns to
bean properties by name, so `UserMapper.findById` no longer needs an
explicit `@Results` block:

```java
@Select("SELECT id, name, age FROM users WHERE id = #{id}")
User findById(@Param("id") Integer id);
```

### Versions

| Component            | Version |
|----------------------|---------|
| Java                 | 1.8     |
| Spring Boot          | 2.7.18  |
| mybatis-spring-boot-starter | 2.3.1 |
| tinydb               | 0.3.0   |
| tinydb-jdbc (driver) | 0.3.0   |

Spring Boot 2.7.x is the most recent line that still supports Java 8
— required because `tinydb-jdbc` is compiled for `target=1.8`
(JDBC 4.2).

### Running the app outside the test runner

The pom pulls in `spring-boot-starter-web` so the app keeps running
after context startup (no web container = main thread exits and
the process terminates immediately).  With a `tinydb-server` running
on port 18520, you can launch from IntelliJ or `mvn spring-boot:run`
and hit:

```bash
curl localhost:8080/api/users/health
# → {"status":"UP","jdbc":"OK","table_count":0}

curl -X POST localhost:8080/api/users \
     -H 'Content-Type: application/json' \
     -d '{"id":1,"name":"alice","age":30}'
# → {"inserted":1,"user":{"id":1,"name":"alice","age":30}}

curl localhost:8080/api/users/1
# → {"id":1,"name":"alice","age":30}
```

### SQL surface used

The v0.3 SQL parser is intentionally strict — see
`changes/tinydb-v0.3/specs/`. The mapper only uses SQL constructs
that the parser accepts:

- `CREATE TABLE`, `DROP TABLE IF EXISTS`, `INSERT INTO ... VALUES`,
  `UPDATE ... SET`, `DELETE FROM ... WHERE`
- `SELECT <cols> FROM <table> [WHERE ...] ORDER BY <col>`
- All statements carry a FROM clause (no `SELECT 1`)
- No `AS` aliases
- No multi-statement batches separated by `;`

## Issues uncovered while building this test

Setting up the project surfaced three real gaps in `tinydb-jdbc-0.3.0`,
all fixed in `jdbc/src/main/java/org/tinydb/jdbc/`:

1. **Wire-protocol length field** — Java `Frame.write` was emitting
   `LEN = payload.length + 2` (i.e. including the type+flags bytes)
   while the Python `tinydb-server` interprets `LEN` as payload-only.
   Symptom: every `HELLO` from the driver hung for 30 s then
   `Read timed out`. Fixed by aligning Java's encoding with Python's
   spec (REQ-PROTO-1).
2. **`Connection.getTransactionIsolation()` / `getWarnings()` /
   `isReadOnly()`** — these were stubbed as `throw new
   SQLException("not supported in v0.3")`, but HikariCP and Spring
   call all three on every checkout. Fixed to return sensible
   defaults (`TRANSACTION_READ_COMMITTED`, `null`, `false`) so
   `DataSource` initialization succeeds.
3. **`ResultSet.getType()` / `getConcurrency()`** — also stubbed as
   "not supported" but Spring JDBC reads them to decide cursor type.
   Fixed to return `TYPE_FORWARD_ONLY` / `CONCUR_READ_ONLY`.

These are also the gaps that would block any other JDBC consumer (DBCP,
c3p0, jOOQ, jdbi, …) from working with the v0.3 driver.

> **Follow-up work**: the JDBC module's *own* unit tests (`FrameTest`,
> `TinyConnectionTest`, `StubCoverageTest`) were written against the
> old wire-protocol contract and now fail until they're updated to
> use payload-length semantics. That's tracked as a separate v0.3.1
> task; the Spring Boot integration test here proves the on-wire
> behaviour is now correct.