# tinydb v0.1 — 功能测试报告

**生成时间**: 2026-07-14
**测试工具**: `python -m tinydb` REPL（手动跑真实 SQL，捕获 stdout）
**全量 pytest**: `python -m pytest tests/ -q` → **826 passed**
**通过率**: **41/41 (100.0%)** ✅

---

## 一、总览

| 类别 | 通过率 | 用例数 | 状态 |
|------|--------|--------|------|
| DDL（数据定义） | 100% (3/3) | 3 | ✅ |
| DML（数据操作） | 100% (7/7) | 7 | ✅ |
| Filter（过滤） | 100% (4/4) | 4 | ✅ |
| Ordering（排序） | 100% (3/3) | 3 | ✅ |
| Aggregate（聚合） | 100% (3/3) | 3 | ✅ |
| Index（索引） | 100% (4/4) | 4 | ✅ |
| Transactions（事务） | 100% (2/2) | 2 | ✅ |
| Types（类型系统） | 100% (11/11) | 11 | ✅ |
| Persistence（持久化） | 100% (1/1) | 1 | ✅ |
| CLI（命令行） | 100% (3/3) | 3 | ✅ |
| **总计** | **100% (41/41)** | **41** | ✅ |

---

## 二、DDL — CREATE / DROP TABLE（建表 / 删表）

```
$ python -m tinydb --db test.db
tinydb v0.1 REPL — enter SQL, or '.help' for commands
tinydb> create table demo (x int, y text);
OK
tinydb> select x from demo;
(0 rows)
tinydb> drop table demo;
OK
tinydb> .exit
bye.
```

---

## 三、DML — INSERT / SELECT / UPDATE / DELETE（增 / 查 / 改 / 删）

```
$ python -m tinydb --db test.db
tinydb v0.1 REPL — enter SQL, or '.help' for commands
tinydb> create table users (id int primary key, name text not null, age int);
OK
tinydb> insert into users values (1, 'alice', 30);
1 row(s)
tinydb> insert into users values (2, 'bob', 25);
1 row(s)
tinydb> insert into users values (3, 'carol', 35);
1 row(s)
tinydb> insert into users values (4, 'dave', 18);
1 row(s)
tinydb> select * from users;
id name  age
1  alice 30 
2  bob   25 
3  carol 35 
4  dave  18 
tinydb> select * from users where age > 25;
id name  age
1  alice 30 
3  carol 35 
tinydb> update users set age = 31 where id = 1;
1 row(s)
tinydb> select * from users where id = 1;
id name  age
1  alice 31 
tinydb> delete from users where id = 4;
1 row(s)
tinydb> select * from users;
id name  age
2  bob   25 
3  carol 35 
1  alice 31 
tinydb> .exit
bye.
```

---

## 四、Filter — WHERE / AND / OR / IS NULL（条件过滤）

```
$ python -m tinydb --db test.db
tinydb v0.1 REPL — enter SQL, or '.help' for commands
tinydb> create table users (id int primary key, name text not null, age int);
OK
tinydb> insert into users values (1, 'alice', 30);
1 row(s)
tinydb> insert into users values (2, 'bob', 25);
1 row(s)
tinydb> insert into users values (3, 'carol', 35);
1 row(s)
tinydb> insert into users values (4, 'eve', NULL);
1 row(s)
tinydb> select * from users where age > 25 and name != 'carol';
id name  age
1  alice 30 
tinydb> select * from users where name = 'bob' or name = 'carol';
id name  age
2  bob   25 
3  carol 35 
tinydb> select * from users where age is null;
id name age 
4  eve  None
tinydb> select * from users where age is not null;
id name  age
1  alice 30 
2  bob   25 
3  carol 35 
tinydb> .exit
bye.
```

---

## 五、Ordering — ORDER BY / LIMIT / OFFSET（排序 / 分页）

```
$ python -m tinydb --db test.db
tinydb v0.1 REPL — enter SQL, or '.help' for commands
tinydb> create table users (id int primary key, name text not null, age int);
OK
tinydb> insert into users values (1, 'alice', 10);
1 row(s)
tinydb> insert into users values (2, 'bob', 20);
1 row(s)
tinydb> insert into users values (3, 'carol', 30);
1 row(s)
tinydb> insert into users values (4, 'dave', 40);
1 row(s)
tinydb> select name from users order by age asc limit 2;
name 
alice
bob  
tinydb> select name from users order by age desc limit 2;
name 
dave 
carol
tinydb> select name from users order by age asc limit 1 offset 2;
name 
carol
tinydb> .exit
bye.
```

---

## 六、Aggregate — COUNT / SUM / AVG / MIN / MAX / GROUP BY（聚合函数）

```
$ python -m tinydb --db test.db
tinydb v0.1 REPL — enter SQL, or '.help' for commands
tinydb> create table users (id int primary key, name text not null, age int);
OK
tinydb> insert into users values (1, 'alice', 30);
1 row(s)
tinydb> insert into users values (2, 'bob', 25);
1 row(s)
tinydb> insert into users values (3, 'carol', 35);
1 row(s)
tinydb> insert into users values (4, 'dave', 18);
1 row(s)
tinydb> select count(*) from users;
COUNT(*)
4       
tinydb> select min(age), max(age), sum(age), avg(age) from users;
MIN(age) MAX(age) SUM(age) AVG(age)
18       35       108      27.0    
tinydb> select count(*) from users group by name;
name  COUNT(*)
alice 1       
bob   1       
carol 1       
dave  1       
tinydb> .exit
bye.
```

---

## 七、Index — B-tree Index + UNIQUE 约束（B 树索引 / 唯一约束）

```
$ python -m tinydb --db test.db
tinydb v0.1 REPL — enter SQL, or '.help' for commands
tinydb> create table users (id int primary key, name text not null, age int);
OK
tinydb> insert into users values (1, 'alice', 30);
1 row(s)
tinydb> insert into users values (2, 'bob', 25);
1 row(s)
tinydb> create unique index idx_users_name on users (name);
OK
tinydb> select * from users where name = 'alice';
id name  age
1  alice 30 
tinydb> insert into users values (99, 'alice', 99);
ConstraintViolation: UNIQUE constraint violated on 'users.name'
tinydb> insert into users (id, age) values (100, 99);
NotNullViolation: NOT NULL constraint violated: 'users.name'
tinydb> .exit
bye.
```

---

## 八、Transactions — 事务（autocommit 模式）

```
$ python -m tinydb --db test.db
tinydb v0.1 REPL — enter SQL, or '.help' for commands
tinydb> create table users (id int primary key, name text not null, age int);
OK
tinydb> insert into users values (1, 'alice', 30);
1 row(s)
tinydb> insert into users values (200, 'tx1', 1);
1 row(s)
tinydb> select * from users where id = 200;
id  name age
200 tx1  1  
tinydb> .exit
bye.
```

> **说明**：在 `db.execute()` API 层，`tinydb` 支持完整 BEGIN / COMMIT / ROLLBACK 事务（见 `scripts/functional_tests.py` 的 Transactions 类别 100% 通过）。REPL 单条 SQL 路径走 autocommit 模式——事务由 `with db.transaction():` 块 API 触发，不是 REPL 内联 SQL。

---

## 九、Types — 10 种类型 round-trip（类型系统）

```
$ python -m tinydb --db test.db
tinydb v0.1 REPL — enter SQL, or '.help' for commands
tinydb> create table type_test (a_int int, a_float float, a_text text, a_bool bool, a_date date, a_time time, a_dt datetime, a_dec decimal, a_blob blob, a_json json);
OK
tinydb> insert into type_test values (42, 3.14, 'hello', true, date '2024-01-15', time '13:45:00', datetime '2024-01-15 13:45:00', decimal '12345.6789', blob '000102', json '{"k":1}');
1 row(s)
tinydb> select * from type_test;
a_int a_float a_text a_bool a_date     a_time   a_dt                a_dec      a_blob          a_json  
42    3.14    hello  True   2024-01-15 13:45:00 2024-01-15 13:45:00 12345.6789 b'\x00\x01\x02' {'k': 1}
tinydb> .exit
bye.
```

---

## 十、CLI — `-c` 一次性命令行模式

```
$ python -m tinydb --db test.db -c "create table cli_demo (n int); insert into cli_demo values (1), (2), (3); select * from cli_demo"
OK
3 row(s)
n
1
2
3
```

---

## 十一、Persistence — 关闭 + 重开 + 恢复（持久化）

```
$ python -m tinydb --db test.db
tinydb v0.1 REPL — enter SQL, or '.help' for commands
tinydb> create table persist_demo (id int primary key, val text);
OK
tinydb> insert into persist_demo values (1, 'first');
1 row(s)
tinydb> insert into persist_demo values (2, 'second');
1 row(s)
tinydb> .exit
bye.

# --- 数据库文件已关闭并落盘 ---

$ python -m tinydb --db test.db
tinydb v0.1 REPL — enter SQL, or '.help' for commands
tinydb> select * from persist_demo order by id;
id val   
1  first
2  second
tinydb> .exit
bye.
```

---

## 十二、关键观察

- **每条 SQL 一条回显** — REPL 用 `tinydb> <SQL>` 提示 + 响应表 + `(0 rows)` 标识空 SELECT
- **CLI 真实回显** — 所有 SQL 在 `python -m tinydb` REPL 中实际执行
- **100% 通过** — 41/41 用例全部通过
- **测试覆盖** — 9 大功能类别 + CLI 一次性模式 + 持久化场景
- **真实列名** — `SELECT *` 显示真实列名（POLISH-CLI 修复后），不再是 `col0`/`col1`
- **NULL 显示** — 空值显示为 `None`（Python 风格）
