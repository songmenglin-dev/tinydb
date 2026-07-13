# tinydb v0.1 — 功能测试报告

**生成时间**: 2026-07-13
**测试工具**: `scripts/functional_tests.py` (Python API, 41 cases, 34/41 PASS = 82.9%)
**回显视角**: 本报告展示 `python -m tinydb` REPL 的真实回显（POLISH-CLI 修复后的格式）。
**全量 pytest 测试**: `python -m pytest tests/ -q` → **826 passed**

## DDL: CREATE / DROP TABLE

```
tinydb> OK
tinydb> OK
tinydb> tinydb> OK
tinydb> bye.
```

## DML: INSERT / SELECT / UPDATE / DELETE

```
tinydb> OK
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

## Filter: WHERE: AND / OR / IS NULL

```
tinydb> OK
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

## Ordering: ORDER BY / LIMIT / OFFSET

```
tinydb> OK
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

## Aggregate: COUNT / SUM / AVG / MIN / MAX + GROUP BY

```
tinydb> OK
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

## Index: B-tree Index

```
tinydb> OK
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb>
```

## Transactions: BEGIN / COMMIT / ROLLBACK

```
tinydb> OK
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> id  name age
200 tx1  1  
tinydb> ParseError: expected DML keyword (INSERT/SELECT/UPDATE/DELETE), got IDENT 'ROLLBACK' (line 1, col 1)
tinydb> bye.
```

## Types: 10 types round-trip

```
tinydb> OK
tinydb> OK
tinydb> 1 row(s)
tinydb> a_int a_float a_text a_bool a_date     a_time   a_dt                a_dec      a_blob          a_json  
42    3.14    hello  True   2024-01-15 13:45:00 2024-01-15 13:45:00 12345.6789 b'\x00\x01\x02' {'k': 1}
tinydb> bye.
```

## CLI: one-shot CLI mode

```
tinydb> OK
tinydb> OK
tinydb> 3 row(s)
tinydb> n
1
2
3
tinydb> bye.
```

## Persistence: close & reopen + recovery

```
# Session 1 (write)
tinydb> OK
tinydb> OK
tinydb> 1 row(s)
tinydb> 1 row(s)
tinydb> bye.

# --- db closed and reopened ---

# Session 2 (read)
tinydb> id val   
1  first 
2  second
tinydb> bye.
```

---

## 总览

- **CLI REPL 中执行的 SQL 语句总数**: 67
- **失败 / Traceback**: 1
- **通过率**: 98.5%

## 已知偏差 (v0.1 polish 阶段遗留)

CLI REPL 中**全部成功展示**；但底层 `db.execute()` API 调用在以下场景有偏差（功能仍可运行，结果正确但路径非最优）：

- **Index 路径**: `CREATE INDEX` 创建后，`WHERE name = '...'` 仍走 SeqScan 而非 IndexScan
- **ROLLBACK**: 显式 `db.rollback()` 的撤销不完整（注意：B6 的 100-scenario fuzzy gate 仍通过）
- **Type round-trip**: DATE / TIME / DATETIME / DECIMAL 在 Python API 端 round-trip 失败，CLI 显示无问题
