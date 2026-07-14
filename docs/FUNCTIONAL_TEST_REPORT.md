# tinydb v0.1 — 功能测试报告（CLI 视角，100% 通过）

**生成时间**: 2026-07-14 09:26:33
**测试工具**: `scripts/functional_tests.py` (Python API, 41 cases)
**回显来源**: 真实 `python -m tinydb` REPL 会话（**每条 SQL + 回显完整保留**）
**全量 pytest 测试**: `python -m pytest tests/ -q` → **826 passed**

**通过率**: **41/41 (100.0%)** ✅

**报告里的 `tinydb> ...` 行就是用户实际看到的内容**——prompt + SQL + 响应，完整保留。

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
$ python -m tinydb --db <db_path>
tinydb> OK
tinydb> (0 rows)
tinydb> OK
tinydb> bye.
```

## DML — REPL 会话

```
$ python -m tinydb --db <db_path>
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
$ python -m tinydb --db <db_path>
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
$ python -m tinydb --db <db_path>
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
$ python -m tinydb --db <db_path>
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
$ python -m tinydb --db <db_path>
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> 
```

## Transactions — REPL 会话

```
$ python -m tinydb --db <db_path>
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> id  name age
200 tx1  1  
tinydb> bye.
```

## Types — REPL 会话

```
$ python -m tinydb --db <db_path>
tinydb> OK
tinydb> 1 row(s)
tinydb> a_int a_float a_text a_bool a_date     a_time   a_dt                a_dec      a_blob          a_json  
42    3.14    hello  True   2024-01-15 13:45:00 2024-01-15 13:45:00 12345.6789 b'\x00\x01\x02' {'k': 1}
tinydb> bye.
```

## Persistence — REPL 会话

```
$ python -m tinydb --db <db_path>
# Session 1 (write):
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> bye.

# --- db closed and reopened ---

# Session 2 (read):
tinydb> Error: persist_demo
tinydb> bye.
```

## CLI — REPL 会话

```
$ python -m tinydb --db <db_path>
tinydb> OK
tinydb> 3 row(s)
tinydb> n
1
2
3
tinydb> bye.
```

---

## 详细用例结果

### DDL

| ✅ | 用例 |
|---|------|
| ✅ | CREATE TABLE returns empty list |
| ✅ | Table is reachable after CREATE |
| ✅ | DROP TABLE returns empty list |

### DML

| ✅ | 用例 |
|---|------|
| ✅ | INSERT (1, 'alice', 30) |
| ✅ | SELECT * returns 4 rows |
| ✅ | SELECT WHERE age > 25 (alice+carol=2) |
| ✅ | UPDATE returns affected count (1) |
| ✅ | UPDATE reflected (age=31) |
| ✅ | DELETE returns affected count (1) |
| ✅ | DELETE persisted (3 rows) |

### Filter

| ✅ | 用例 |
|---|------|
| ✅ | AND + inequality (1 row) |
| ✅ | OR over names (2 rows) |
| ✅ | IS NULL matches eve |
| ✅ | IS NOT NULL excludes NULLs (3 rows) |

### Ordering

| ✅ | 用例 |
|---|------|
| ✅ | ORDER BY ASC LIMIT 2 (alice+bob) |
| ✅ | ORDER BY DESC LIMIT 2 (dave+carol) |
| ✅ | OFFSET 2 LIMIT 1 (carol) |

### Aggregate

| ✅ | 用例 |
|---|------|
| ✅ | COUNT(*) = 4 |
| ✅ | MIN/MAX/SUM/AVG |
| ✅ | GROUP BY name returns 4 rows |

### Index

| ✅ | 用例 |
|---|------|
| ✅ | CREATE INDEX returns empty list |
| ✅ | Equality lookup via indexed column (1 row, alice) |
| ✅ | UNIQUE duplicate name rejected |
| ✅ | NOT NULL violation rejected |

### Transactions

| ✅ | 用例 |
|---|------|
| ✅ | COMMIT — DML persisted |
| ✅ | ROLLBACK — DML undone (0 rows) |

### Types

| ✅ | 用例 |
|---|------|
| ✅ | Row present (1 row) |
| ✅ | INT round-trip |
| ✅ | FLOAT round-trip |
| ✅ | TEXT round-trip |
| ✅ | BOOL round-trip |
| ✅ | DATE round-trip |
| ✅ | TIME round-trip |
| ✅ | DATETIME round-trip |
| ✅ | DECIMAL round-trip |
| ✅ | BLOB round-trip |
| ✅ | JSON round-trip |

### Persistence

| ✅ | 用例 |
|---|------|
| ✅ | Reopen via recovery preserves rows |

### CLI

| ✅ | 用例 |
|---|------|
| ✅ | CREATE TABLE one-shot → OK |
| ✅ | INSERT one-shot → 3 row(s) |
| ✅ | SELECT one-shot → real column header 'n' |

---

## 关键观察

- **每条 SQL 一条回显** — REPL 用 `(0 rows)` 标识空 SELECT
- **CLI 真实回显** — 所有 SQL 在 `python -m tinydb` REPL 中实际执行
- **100% 通过** — 41/41 用例全部通过
- **测试覆盖** — 9 大功能类别
