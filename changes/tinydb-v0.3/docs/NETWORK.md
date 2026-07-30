# tinydb Network & Wire Protocol (v0.3)

## Overview

Starting with v0.3, tinydb ships with a **client-server architecture** so that
Python and Java applications can connect to a remote tinydb instance the same
way they connect to MySQL, PostgreSQL, or GaussDB. The architecture reuses
the v0.2 single-file storage, SQL parser, executor, and transaction stack
without modification — only a thin transport layer has been added.

## Components

| Component | Path | Purpose |
|-----------|------|---------|
| **tinydb-server** | `src/tinydb/server/` | asyncio TCP server; binds `host:port`, services a single `.db` file |
| **Python Client** | `src/tinydb/client/` | `Client` (sync), `AsyncClient` (asyncio), `Pool` (connection pool) |
| **Wire Protocol** | `src/tinydb/protocol/` | Frame codec, message types, SQLSTATE mapping |
| **CLI dual-mode** | `src/tinydb/cli/` | `--file` (embedded) or `--uri tinydb://...` (remote) |
| **JDBC Driver** | `jdbc/` | Java 8 / JDBC 4.2 Type-4 driver, `<200KB` JAR |

## Wire Protocol

### Frame Format

```
+--------+--------+--------+---------------------+
| LEN    | TYPE   | FLAGS  | PAYLOAD             |
| 4B BE  | 1B     | 1B     | LEN bytes           |
+--------+--------+--------+---------------------+
```

- **LEN** — payload length, 4 bytes big-endian, max `0xFFFFFF` (16 MiB - 1)
- **TYPE** — message type code (see table below)
- **FLAGS** — reserved, must be `0x00`
- **PAYLOAD** — message-specific UTF-8 / binary body

### Message Types

| TYPE | Name | Direction | Payload |
|------|------|-----------|---------|
| `0x01` | HELLO | C→S | `[client_len(1B)][client_utf8]` |
| `0x02` | OK | S→C | `[version_len(1B)][version_utf8]` |
| `0x03` | ERR | S→C | `[code(5B)][msg_len(2B)][msg_utf8]` |
| `0x10` | QUERY | C→S | `[sql_utf8]` |
| `0x11` | EXEC | C→S | `[sql_len(4B)][sql][param_count(2B)][param...]` |
| `0x20` | RESULT_HEADER | S→C | `[col_count(2B)][col_name_len(1B)][col_name][col_type(1B)]...` |
| `0x21` | RESULT_ROW | S→C | `[col_count(2B)][col_value...]` |
| `0x22` | RESULT_DONE | S→C | `[rowcount(8B)][last_insert_id(8B)][flags(1B)]` |
| `0x23` | RESULT_ERROR | S→C | `[code(5B)][msg_len(2B)][msg_utf8]` |
| `0x30` | PING | C↔S | `[ts(8B)]` |
| `0x31` | PONG | S↔C | `[ts(8B)]` (echoes PING timestamp) |
| `0xFE` | QUIT | C→S | empty |

### EXEC Parameters

Each parameter is encoded as:
```
[TYPE(1B)][LEN(4B BE)][VALUE(LEN bytes)]
```

| TYPE | JDBC Type | Python type | Encoding |
|------|-----------|-------------|----------|
| `0x00` | NULL | None | empty (LEN=0) |
| `0x01` | BIGINT | int | 8-byte big-endian signed |
| `0x02` | DOUBLE | float | 8-byte IEEE-754 big-endian |
| `0x03` | VARCHAR | str | UTF-8 bytes |
| `0x04` | BOOLEAN | bool | 1 byte (`0x00` / `0x01`) |

### SQLSTATE Codes

| Code | Meaning | Example |
|------|---------|---------|
| `08000` | Connection exception | HELLO missing, server shutdown |
| `22000` | Data exception | type mismatch, UNIQUE violation |
| `25000` | Invalid transaction state | COMMIT outside transaction |
| `42000` | Syntax error | parse failure |
| `HY000` | General error | everything else |

### RESULT_DONE flags

| Bit | Meaning |
|-----|---------|
| `0x01` | autocommit is on |
| `0x02` | inside transaction |
| `0x04` | no result set (INSERT/UPDATE/DELETE) |

## Quick Start

### Start the server

```bash
$ tinydb-server --db-path /var/lib/tinydb/data.db -H 0.0.0.0 -p 8520
[server] 2026-07-31T10:00:00Z INFO listening on 0.0.0.0:8520
```

### Connect from Python (sync)

```python
from tinydb.client import Client

with Client("127.0.0.1", 8520) as c:
    result = c.execute("SELECT id, name FROM users WHERE id = ?", [42])
    print(result.rows)        # [[42, "Alice"]]
    print(result.rowcount)   # 1
    print(result.columns)    # ["id", "name"]
```

### Connect from Python (async)

```python
import asyncio
from tinydb.client import AsyncClient

async def main():
    async with AsyncClient("127.0.0.1", 8520) as c:
        result = await c.execute("SELECT 1")
        print(result.rows)    # [[1]]

asyncio.run(main())
```

### Connect via the CLI (remote mode)

```bash
$ tinydb --uri tinydb://user:pw@db.example.com:8520/mydb
tinydb> .status
mode=remote uri=tinydb://db.example.com:8520 state=connected rtt=1.2ms
tinydb> SELECT 1;
┌───┐
│ 1 │
├───┤
│ 1 │
└───┘
1 row in set (2.3ms)
tinydb> .connect tinydb://other:8527
tinydb> .quit
```

### Connect from Java (JDBC)

```java
import java.sql.*;
import org.tinydb.jdbc.TinyDriver;

Class.forName("org.tinydb.jdbc.TinyDriver");
try (Connection conn = DriverManager.getConnection(
        "jdbc:tinydb://db.example.com:8520/mydb")) {
    try (PreparedStatement ps = conn.prepareStatement(
            "SELECT id, name FROM users WHERE id = ?")) {
        ps.setInt(1, 42);
        try (ResultSet rs = ps.executeQuery()) {
            while (rs.next()) {
                System.out.println(rs.getInt(1) + " " + rs.getString(2));
            }
        }
    }
}
```

## Configuration

### tinydb-server flags

| Flag | Default | Description |
|------|---------|-------------|
| `--db-path` / `-d` | required | `.db` file to service |
| `--host` / `-H` | `127.0.0.1` | bind host |
| `--port` / `-p` | `8520` | bind port (1..65535) |
| `--max-conns` | `64` | concurrent connection cap |
| `--idle-timeout` | `1800` | seconds before idle conn is closed |
| `--heartbeat-interval` | `30` | seconds between server-initiated PONG |
| `--heartbeat-misses` | `3` | missed PONG count before death cleanup |

### Connection lifecycle

1. TCP connect
2. Client sends HELLO (must happen within 5 seconds)
3. Server replies OK with version string
4. Client sends QUERY/EXEC; server replies RESULT_HEADER + ROWs + DONE (or RESULT_ERROR)
5. Either side can send PING/PONG anytime
6. Client sends QUIT to disconnect gracefully; server replies OK and closes

## Operational notes

- **v0.3 has no authentication.** Bind to `127.0.0.1` or use network ACL.
- The wire protocol is text-on-top-of-binary for SQL, binary for params. Use `tcpdump -X port 8520` to debug.
- All Python `tinydb.client.Client.execute(...)` calls can be retried; on connection drop the client reconnects with exponential backoff (100 → 200 → 400 → 800 → 1600 ms, max 5 attempts).
- The JDBC driver uses one Java thread per connection. Use an external pool (HikariCP, c3p0) for high concurrency.

See `jdbc/README.md` (when generated) for more JDBC usage examples.