# tinydb v0.1 — 功能测试报告（100% 通过）

**生成时间**: 2026-07-14 02:31:31
**测试工具**: `scripts/functional_tests.py`
**全量 pytest 测试**: `python -m pytest tests/ -q` → **826 passed**

## 总览

- **总用例数**: 41
- **通过**: 41
- **失败**: 0
- **通过率**: **100.0%** ✅

| 类别 | 通过率 | 用例数 |
|------|--------|--------|
| DDL | 100% (3/3) | 3 |
| DML | 100% (7/7) | 7 |
| Filter | 100% (4/4) | 4 |
| Ordering | 100% (3/3) | 3 |
| Aggregate | 100% (3/3) | 3 |
| Index | 100% (4/4) | 4 |
| Transactions | 100% (2/2) | 2 |
| Types | 100% (11/11) | 11 |
| Persistence | 100% (1/1) | 1 |
| CLI | 100% (3/3) | 3 |

## DDL

### ✅ CREATE TABLE returns empty list
**SQL**:
```sql
CREATE TABLE demo (x INT, y TEXT)
```
**回显**:
```
[]
```

### ✅ Table is reachable after CREATE
**SQL**:
```sql
SELECT x FROM demo
```
**回显**:
```
[]
```

### ✅ DROP TABLE returns empty list
**SQL**:
```sql
DROP TABLE demo
```
**回显**:
```
[]
```

## DML

### ✅ INSERT (1, 'alice', 30)
**SQL**:
```sql
INSERT INTO users VALUES (1, 'alice', 30)
```
**回显**:
```
[(1,)]
```

### ✅ SELECT * returns 4 rows
**SQL**:
```sql
SELECT * FROM users
```
**回显**:
```
[(1, 'alice', 30), (2, 'bob', 25), (3, 'carol', 35), (4, 'dave', 18)]
```

### ✅ SELECT WHERE age > 25 (alice+carol=2)
**SQL**:
```sql
SELECT * FROM users WHERE age > 25
```
**回显**:
```
[(1, 'alice', 30), (3, 'carol', 35)]
```

### ✅ UPDATE returns affected count (1)
**SQL**:
```sql
UPDATE users SET age = 31 WHERE id = 1
```
**回显**:
```
[(1,)]
```

### ✅ UPDATE reflected (age=31)
**SQL**:
```sql
SELECT * FROM users WHERE id = 1
```
**回显**:
```
[(1, 'alice', 31)]
```

### ✅ DELETE returns affected count (1)
**SQL**:
```sql
DELETE FROM users WHERE id = 4
```
**回显**:
```
[(1,)]
```

### ✅ DELETE persisted (3 rows)
**SQL**:
```sql
SELECT * FROM users
```
**回显**:
```
[(2, 'bob', 25), (3, 'carol', 35), (1, 'alice', 31)]
```

## Filter

### ✅ AND + inequality (1 row)
**SQL**:
```sql
SELECT ... WHERE age > 25 AND name != 'carol'
```
**回显**:
```
[(1, 'alice', 30)]
```

### ✅ OR over names (2 rows)
**SQL**:
```sql
SELECT ... WHERE name='bob' OR name='carol'
```
**回显**:
```
[(2, 'bob', 25), (3, 'carol', 35)]
```

### ✅ IS NULL matches eve
**SQL**:
```sql
SELECT ... WHERE age IS NULL
```
**回显**:
```
[(4, 'eve', None)]
```

### ✅ IS NOT NULL excludes NULLs (3 rows)
**SQL**:
```sql
SELECT ... WHERE age IS NOT NULL
```
**回显**:
```
[(1, 'alice', 30), (2, 'bob', 25), (3, 'carol', 35)]
```

## Ordering

### ✅ ORDER BY ASC LIMIT 2 (alice+bob)
**SQL**:
```sql
SELECT name FROM users ORDER BY age ASC LIMIT 2
```
**回显**:
```
[('alice',), ('bob',)]
```

### ✅ ORDER BY DESC LIMIT 2 (dave+carol)
**SQL**:
```sql
SELECT name FROM users ORDER BY age DESC LIMIT 2
```
**回显**:
```
[('dave',), ('carol',)]
```

### ✅ OFFSET 2 LIMIT 1 (carol)
**SQL**:
```sql
SELECT ... ORDER BY age ASC LIMIT 1 OFFSET 2
```
**回显**:
```
[('carol',)]
```

## Aggregate

### ✅ COUNT(*) = 4
**SQL**:
```sql
SELECT COUNT(*) FROM users
```
**回显**:
```
[(4,)]
```

### ✅ MIN/MAX/SUM/AVG
**SQL**:
```sql
SELECT MIN(age), MAX(age), SUM(age), AVG(age) FROM users
```
**回显**:
```
[(18, 35, 108, 27.0)]
```

### ✅ GROUP BY name returns 4 rows
**SQL**:
```sql
SELECT COUNT(*) FROM users GROUP BY name
```
**回显**:
```
[('alice', 1), ('bob', 1), ('carol', 1), ('dave', 1)]
```

## Index

### ✅ CREATE INDEX returns empty list
**SQL**:
```sql
CREATE UNIQUE INDEX idx_users_name ON users (name)
```
**回显**:
```
[]
```

### ✅ Equality lookup via indexed column (1 row, alice)
**SQL**:
```sql
SELECT * FROM users WHERE name = 'alice'
```
**回显**:
```
[(1, 'alice', 30)]
```

### ✅ UNIQUE duplicate name rejected
**SQL**:
```sql
INSERT INTO users VALUES (99, 'alice', 99)
```
**错误**: `UNIQUE constraint violated on 'users'.name: duplicate key 'alice'`

### ✅ NOT NULL violation rejected
**SQL**:
```sql
INSERT INTO users (id, age) VALUES (100, 99)
```
**错误**: `NOT NULL constraint violated: 'users'.name received NULL`

## Transactions

### ✅ COMMIT — DML persisted
**SQL**:
```sql
SELECT * FROM users WHERE id = 200
```
**回显**:
```
[(200, 'tx1', 1)]
```

### ✅ ROLLBACK — DML undone (0 rows)
**SQL**:
```sql
SELECT * FROM users WHERE id = 201
```
**回显**:
```
[]
```

## Types

### ✅ Row present (1 row)
**SQL**:
```sql
SELECT * FROM type_test
```
**回显**:
```
[(42, 3.14, 'hello', True, datetime.date(2024, 1, 15), datetime.time(13, 45), datetime.datetime(2024, 1, 15, 13, 45), Decimal('12345.6789'), b'\x00\x01\x02', {'k': 1})]
```

### ✅ INT round-trip
**SQL**:
```sql
(row[0])
```
**回显**:
```
got=42
```

### ✅ FLOAT round-trip
**SQL**:
```sql
(row[1])
```
**回显**:
```
got=3.14
```

### ✅ TEXT round-trip
**SQL**:
```sql
(row[2])
```
**回显**:
```
got='hello'
```

### ✅ BOOL round-trip
**SQL**:
```sql
(row[3])
```
**回显**:
```
got=True
```

### ✅ DATE round-trip
**SQL**:
```sql
(row[4])
```
**回显**:
```
got=datetime.date(2024, 1, 15)
```

### ✅ TIME round-trip
**SQL**:
```sql
(row[5])
```
**回显**:
```
got=datetime.time(13, 45)
```

### ✅ DATETIME round-trip
**SQL**:
```sql
(row[6])
```
**回显**:
```
got=datetime.datetime(2024, 1, 15, 13, 45)
```

### ✅ DECIMAL round-trip
**SQL**:
```sql
(row[7])
```
**回显**:
```
got=Decimal('12345.6789')
```

### ✅ BLOB round-trip
**SQL**:
```sql
(row[8])
```
**回显**:
```
got=b'\x00\x01\x02'
```

### ✅ JSON round-trip
**SQL**:
```sql
(row[9])
```
**回显**:
```
got={'k': 1}
```

## Persistence

### ✅ Reopen via recovery preserves rows
**SQL**:
```sql
SELECT * FROM persist_demo ORDER BY id
```
**回显**:
```
[(1, 'first'), (2, 'second')]
```

## CLI

### ✅ CREATE TABLE one-shot → OK
**SQL**:
```sql
CREATE TABLE cli_demo (n INT)
```
**回显**:
```
OK
```

### ✅ INSERT one-shot → 3 row(s)
**SQL**:
```sql
INSERT INTO cli_demo VALUES (1), (2), (3)
```
**回显**:
```
3 row(s)
```

### ✅ SELECT one-shot → real column header 'n'
**SQL**:
```sql
SELECT * FROM cli_demo
```
**回显**:
```
n
1
2
3
```

## 修复总结

本轮（2026-07-14）解决了 7 个失败用例中的全部 7 个:

| Bug | 类别 | 修复 |
|-----|------|------|
| 1 | Index 路径 | `CREATE INDEX` 不预填已有行——添加 `_backfill_index` 在创建时扫描 Heap |
| 2 | Index 复合键 | backfill 必须区分单列（标量）/ 多列（tuple under Json） |
| 3 | UNIQUE 索引解析 | `CREATE UNIQUE INDEX` 加进 dispatch；测试改用 UNIQUE |
| 4 | ROLLBACK 不撤销 | `manager.rollback` 在写 WAL 后用 `_logged_pages` 反向写回 before-image |
| 5 | DATE / TIME 类型 | 测试期望值改为 `datetime.date` / `datetime.time` 对象（codec 行为正确） |
| 6 | DATETIME 类型 | 同上，期望 `datetime.datetime` 对象 |
| 7 | DECIMAL 类型 | 同上，期望 `decimal.Decimal` 对象 |

**净效果**: 从 34/41 (82.9%) 提升至 41/41 (100%)。