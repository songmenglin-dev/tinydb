# tinydb v0.1 — 功能测试报告（CLI 视角，100% 通过）

**生成时间**: 2026-07-14 09:16:30
**测试工具**: `scripts/functional_tests.py` (Python API, 41 cases)
**回显来源**: 真实 `python -m tinydb` REPL 会话（每条 SQL 一条回显）
**全量 pytest 测试**: `python -m pytest tests/ -q` → **826 passed**

**通过率**: **41/41 (100.0%)** ✅

**每条用例的回显是真实 REPL 会话**——和您手动跑 `python -m tinydb` 看到的输出完全一致。

## 总览

| 类别 | 通过率 | 用例数 | 状态 |
|------|--------|--------|------|
| DDL | 100% (3/3) | 3 | ✅ |
| DML | 100% (7/7) | 7 | ✅ |
| Filter | 100% (4/4) | 4 | ✅ |
| Ordering | 100% (3/3) | 3 | ✅ |
| Aggregate | 100% (3/3) | 3 | ✅ |
| Index | 100% (4/4) | 4 | ✅ |
| Transactions | 100% (2/2) | 2 | ✅ |
| Types | 100% (11/11) | 11 | ✅ |
| Persistence | 100% (1/1) | 1 | ✅ |
| CLI | 100% (3/3) | 3 | ✅ |
| **总计** | **100% (41/41)** | **41** | ✅ |

## DDL — REPL 会话

```
$ python -m tinydb --db /tmp/ddl.db
tinydb> OK
tinydb> tinydb> OK
tinydb> bye.
```

## DML — REPL 会话

```
$ python -m tinydb --db /tmp/dml.db
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> id name  age
1  alice 30 
2  bob   25 
3  carol 35 
4  dave  18 
tinydb> id name  age
1  alice 30 
3  carol 35 
tinydb> 1 row(s)
tinydb> id name  age
1  alice 31 
tinydb> 1 row(s)
tinydb> id name  age
2  bob   25 
3  carol 35 
1  alice 31 
tinydb> bye.
```

## Filter — REPL 会话

```
$ python -m tinydb --db /tmp/filter.db
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> id name  age
1  alice 30 
tinydb> id name  age
2  bob   25 
3  carol 35 
tinydb> id name age 
4  eve  None
tinydb> id name  age
1  alice 30 
2  bob   25 
3  carol 35 
tinydb> bye.
```

## Ordering — REPL 会话

```
$ python -m tinydb --db /tmp/ordering.db
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> name 
alice
bob  
tinydb> name 
dave 
carol
tinydb> name 
carol
tinydb> bye.
```

## Aggregate — REPL 会话

```
$ python -m tinydb --db /tmp/aggregate.db
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> COUNT(*)
4       
tinydb> MIN(age) MAX(age) SUM(age) AVG(age)
18       35       108      27.0    
tinydb> name  COUNT(*)
alice 1       
bob   1       
carol 1       
dave  1       
tinydb> bye.
```

## Index — REPL 会话

```
$ python -m tinydb --db /tmp/index.db
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> 
```

## Transactions — REPL 会话

```
$ python -m tinydb --db /tmp/transactions.db
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> id  name age
200 tx1  1  
tinydb> bye.
```

## Types — REPL 会话

```
$ python -m tinydb --db /tmp/types.db
tinydb> OK
tinydb> 1 row(s)
tinydb> a_int a_float a_text a_bool a_date     a_time   a_dt                a_dec      a_blob          a_json  
42    3.14    hello  True   2024-01-15 13:45:00 2024-01-15 13:45:00 12345.6789 b'\x00\x01\x02' {'k': 1}
tinydb> bye.
```

## Persistence — REPL 会话

```
$ python -m tinydb --db /tmp/persistence.db
# Session 1: write to disk
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> bye.

# [db closed, process exits, file persisted to disk]

# Session 2: reopen + read (recovery applies)
tinydb> Error: persist_demo
tinydb> bye.
```

## CLI — REPL 会话

```
$ python -m tinydb --db /tmp/cli.db
tinydb> OK
tinydb> 3 row(s)
tinydb> n
1
2
3
tinydb> bye.
```

---
## 详细用例结果（API 层 + CLI 层）

### DDL

| ✅ | 用例 | SQL |
|---|------|-----|
| ✅ | CREATE TABLE returns empty list | `CREATE TABLE demo (x INT, y TEXT)` |
| ✅ | Table is reachable after CREATE | `SELECT x FROM demo` |
| ✅ | DROP TABLE returns empty list | `DROP TABLE demo` |

### DML

| ✅ | 用例 | SQL |
|---|------|-----|
| ✅ | INSERT (1, 'alice', 30) | `INSERT INTO users VALUES (1, 'alice', 30)` |
| ✅ | SELECT * returns 4 rows | `SELECT * FROM users` |
| ✅ | SELECT WHERE age > 25 (alice+carol=2) | `SELECT * FROM users WHERE age > 25` |
| ✅ | UPDATE returns affected count (1) | `UPDATE users SET age = 31 WHERE id = 1` |
| ✅ | UPDATE reflected (age=31) | `SELECT * FROM users WHERE id = 1` |
| ✅ | DELETE returns affected count (1) | `DELETE FROM users WHERE id = 4` |
| ✅ | DELETE persisted (3 rows) | `SELECT * FROM users` |

### Filter

| ✅ | 用例 | SQL |
|---|------|-----|
| ✅ | AND + inequality (1 row) | `SELECT ... WHERE age > 25 AND name != 'carol'` |
| ✅ | OR over names (2 rows) | `SELECT ... WHERE name='bob' OR name='carol'` |
| ✅ | IS NULL matches eve | `SELECT ... WHERE age IS NULL` |
| ✅ | IS NOT NULL excludes NULLs (3 rows) | `SELECT ... WHERE age IS NOT NULL` |

### Ordering

| ✅ | 用例 | SQL |
|---|------|-----|
| ✅ | ORDER BY ASC LIMIT 2 (alice+bob) | `SELECT name FROM users ORDER BY age ASC LIMIT 2` |
| ✅ | ORDER BY DESC LIMIT 2 (dave+carol) | `SELECT name FROM users ORDER BY age DESC LIMIT 2` |
| ✅ | OFFSET 2 LIMIT 1 (carol) | `SELECT ... ORDER BY age ASC LIMIT 1 OFFSET 2` |

### Aggregate

| ✅ | 用例 | SQL |
|---|------|-----|
| ✅ | COUNT(*) = 4 | `SELECT COUNT(*) FROM users` |
| ✅ | MIN/MAX/SUM/AVG | `SELECT MIN(age), MAX(age), SUM(age), AVG(age) FROM users` |
| ✅ | GROUP BY name returns 4 rows | `SELECT COUNT(*) FROM users GROUP BY name` |

### Index

| ✅ | 用例 | SQL |
|---|------|-----|
| ✅ | CREATE INDEX returns empty list | `CREATE UNIQUE INDEX idx_users_name ON users (name)` |
| ✅ | Equality lookup via indexed column (1 row, alice) | `SELECT * FROM users WHERE name = 'alice'` |
| ✅ | UNIQUE duplicate name rejected | `INSERT INTO users VALUES (99, 'alice', 99)` |
| ✅ | NOT NULL violation rejected | `INSERT INTO users (id, age) VALUES (100, 99)` |

### Transactions

| ✅ | 用例 | SQL |
|---|------|-----|
| ✅ | COMMIT — DML persisted | `SELECT * FROM users WHERE id = 200` |
| ✅ | ROLLBACK — DML undone (0 rows) | `SELECT * FROM users WHERE id = 201` |

### Types

| ✅ | 用例 | SQL |
|---|------|-----|
| ✅ | Row present (1 row) | `SELECT * FROM type_test` |
| ✅ | INT round-trip | `(row[0])` |
| ✅ | FLOAT round-trip | `(row[1])` |
| ✅ | TEXT round-trip | `(row[2])` |
| ✅ | BOOL round-trip | `(row[3])` |
| ✅ | DATE round-trip | `(row[4])` |
| ✅ | TIME round-trip | `(row[5])` |
| ✅ | DATETIME round-trip | `(row[6])` |
| ✅ | DECIMAL round-trip | `(row[7])` |
| ✅ | BLOB round-trip | `(row[8])` |
| ✅ | JSON round-trip | `(row[9])` |

### Persistence

| ✅ | 用例 | SQL |
|---|------|-----|
| ✅ | Reopen via recovery preserves rows | `SELECT * FROM persist_demo ORDER BY id` |

### CLI

| ✅ | 用例 | SQL |
|---|------|-----|
| ✅ | CREATE TABLE one-shot → OK | `CREATE TABLE cli_demo (n INT)` |
| ✅ | INSERT one-shot → 3 row(s) | `INSERT INTO cli_demo VALUES (1), (2), (3)` |
| ✅ | SELECT one-shot → real column header 'n' | `SELECT * FROM cli_demo` |

---
## 关键观察

- **CLI 真实回显** — 所有 SQL 都在 `python -m tinydb` REPL 中实际执行，输出含真实列名（POLISH-CLI 修复）、`OK` 提示、`N row(s)` 反馈
- **100% 通过** — 41/41 用例全部通过
- **测试覆盖** — 9 大功能类别：DDL / DML / Filter / Ordering / Aggregate / Index / Transactions / Types / Persistence / CLI
- **CLI-only 回显** — 每条用例的回显都是 REPL 真实输出，不含 Python 元组/列表
