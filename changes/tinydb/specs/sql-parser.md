# Spec: SQL 解析

## ADDED Requirements

### REQ-SQL-1: DDL 解析
The system MUST parse `CREATE TABLE` and `DROP TABLE` statements into a validated AST.

#### Scenario: 创建带列定义与约束的表
- WHEN 解析 `CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)`
- THEN 生成的 AST 包含表名 `users`、列 `id` (类型 INT, PRIMARY KEY 约束)、列 `name` (类型 TEXT, NOT NULL 约束)
- AND 不抛错

#### Scenario: 解析 DROP TABLE
- WHEN 解析 `DROP TABLE users`
- THEN 生成的 AST 表示对 `users` 的删除操作
- AND 不抛错

#### Scenario: 非法 DDL 报错
- WHEN 解析 `CREATE TABLE` 缺少表名
- THEN 抛出 `ParseError`，错误信息含近似 token 位置

### REQ-SQL-2: DML 解析
The system MUST parse `INSERT`, `SELECT`, `UPDATE`, `DELETE` into a validated AST.

#### Scenario: 解析 INSERT
- WHEN 解析 `INSERT INTO users (id, name) VALUES (1, 'a')`
- THEN AST 包含目标表、列名列表、值列表
- AND 不抛错

#### Scenario: 解析 SELECT 全列
- WHEN 解析 `SELECT * FROM users`
- THEN AST 标记为通配列选择
- AND 不抛错

#### Scenario: 解析 UPDATE
- WHEN 解析 `UPDATE users SET name = 'b' WHERE id = 1`
- THEN AST 包含目标表、SET 子句、WHERE 子句
- AND 不抛错

#### Scenario: 解析 DELETE
- WHEN 解析 `DELETE FROM users WHERE id = 1`
- THEN AST 包含目标表、WHERE 子句
- AND 不抛错

### REQ-SQL-3: WHERE 条件过滤解析
The system MUST parse WHERE clauses with `AND` / `OR` 布尔组合与比较运算符 (`=`, `!=`, `<`, `<=`, `>`, `>=`)。

#### Scenario: 单条件 WHERE
- WHEN 解析 `WHERE age >= 18`
- THEN AST 包含二元比较 `age >= 18`

#### Scenario: AND 组合
- WHEN 解析 `WHERE age >= 18 AND status = 'active'`
- THEN AST 表达两个比较的逻辑与

#### Scenario: OR 组合
- WHEN 解析 `WHERE a = 1 OR b = 2`
- THEN AST 表达两个比较的逻辑或

#### Scenario: 混合 AND/OR
- WHEN 解析 `WHERE (a = 1 OR b = 2) AND c = 3`
- THEN AST 保留显式括号优先级

### REQ-SQL-4: ORDER BY、LIMIT、OFFSET 解析
The system MUST parse `ORDER BY <column> [ASC|DESC]`, `LIMIT <n>`, `OFFSET <n>` 子句。

#### Scenario: 升序排序
- WHEN 解析 `SELECT * FROM t ORDER BY id ASC`
- THEN AST 包含按 `id` 升序的排序规范

#### Scenario: 降序排序
- WHEN 解析 `SELECT * FROM t ORDER BY created DESC`
- THEN AST 包含按 `created` 降序的排序规范

#### Scenario: 分页
- WHEN 解析 `SELECT * FROM t LIMIT 10 OFFSET 20`
- THEN AST 包含 `limit=10, offset=20`

#### Scenario: 缺省方向
- WHEN 解析 `ORDER BY id` 未指定方向
- THEN 默认方向为 `ASC`

### REQ-SQL-5: 列约束解析
The system MUST parse `PRIMARY KEY`, `NOT NULL`, `UNIQUE` 列约束。

#### Scenario: 单列主键
- WHEN 解析 `id INT PRIMARY KEY`
- THEN AST 列定义中 `primary_key=True`

#### Scenario: 多列 UNIQUE
- WHEN 解析 `email TEXT UNIQUE`
- THEN AST 列定义中 `unique=True`

#### Scenario: NOT NULL
- WHEN 解析 `name TEXT NOT NULL`
- THEN AST 列定义中 `not_null=True`

### REQ-SQL-6: 聚合函数与 GROUP BY 解析
The system MUST parse `COUNT(*)`, `COUNT(col)`, `SUM(col)`, `AVG(col)`, 以及 `GROUP BY <column_list>`。

#### Scenario: COUNT 星号
- WHEN 解析 `SELECT COUNT(*) FROM users`
- THEN AST 聚合为 `count_star`

#### Scenario: SUM
- WHEN 解析 `SELECT SUM(amount) FROM orders`
- THEN AST 聚合为 `sum(amount)`

#### Scenario: GROUP BY
- WHEN 解析 `SELECT dept, COUNT(*) FROM emp GROUP BY dept`
- THEN AST 包含按 `dept` 分组的规范

### REQ-SQL-7: 错误报告
The system MUST raise `ParseError` 包含行号与列号 (近似 token 位置) 当 SQL 不符合语法。

#### Scenario: 缺少 FROM 关键字
- WHEN 解析 `SELECT * users`
- THEN 抛出 `ParseError`，错误信息含 token 位置

#### Scenario: 未闭合引号
- WHEN 解析 `INSERT INTO t VALUES ('abc)`
- THEN 抛出 `ParseError`

### REQ-SQL-8: 数据类型字面量
The system MUST 识别 SQL 字面量为 INT / FLOAT / TEXT / BOOL / NULL。

#### Scenario: 整数字面量
- WHEN 解析 `WHERE id = 42`
- THEN 字面量类型识别为 INT，值为 `42`

#### Scenario: 浮点字面量
- WHEN 解析 `WHERE price = 9.99`
- THEN 字面量类型识别为 FLOAT

#### Scenario: 字符串字面量
- WHEN 解析 `WHERE name = 'alice'`
- THEN 字面量类型识别为 TEXT，值去掉引号

#### Scenario: 布尔字面量
- WHEN 解析 `WHERE active = TRUE`
- THEN 字面量类型识别为 BOOL，值 `True`

#### Scenario: NULL 字面量
- WHEN 解析 `WHERE x IS NULL`
- THEN 字面量类型识别为 NULL
