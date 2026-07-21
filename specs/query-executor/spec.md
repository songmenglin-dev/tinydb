# Spec: 查询执行

## ADDED Requirements

### REQ-QEX-1: 全表扫描
The system MUST 在没有合适索引时以全表扫描方式执行 SELECT / UPDATE / DELETE。

#### Scenario: 无索引的全表扫描
- WHEN 对表 `t` 执行 `SELECT * FROM t`
- THEN 扫描器顺序访问表的堆文件中所有非空槽位
- AND 返回所有存活记录

### REQ-QEX-2: WHERE 过滤
The system MUST 在执行时按 WHERE 表达式对记录求值，仅保留结果为真的记录。

#### Scenario: 等值过滤
- WHEN `SELECT * FROM t WHERE id = 5`
- THEN 结果仅包含 `id` 等于 5 的记录

#### Scenario: 范围过滤
- WHEN `SELECT * FROM t WHERE age >= 18`
- THEN 结果仅包含 `age >= 18` 的记录

#### Scenario: 复合条件
- WHEN `WHERE a = 1 AND (b = 2 OR c = 3)`
- THEN 结果严格按布尔表达式求值

### REQ-QEX-3: 索引加速
The system MUST 当 WHERE 条件命中索引列时使用索引代替全表扫描。

#### Scenario: 等值索引查找
- WHEN 列 `id` 存在 B-tree 索引且 `WHERE id = 5`
- THEN 执行器通过索引定位 rid 集合
- AND 不进行全表扫描

#### Scenario: 范围索引扫描
- WHEN 列 `score` 存在索引且 `WHERE score BETWEEN 80 AND 100`
- THEN 执行器通过索引范围扫描得到 rid 集合

### REQ-QEX-4: ORDER BY 排序
The system MUST 对结果集按 ORDER BY 指定的列与方向排序。

#### Scenario: 单列升序
- WHEN `SELECT * FROM t ORDER BY id ASC`
- THEN 结果按 `id` 升序返回

#### Scenario: 多列混合方向
- WHEN `SELECT * FROM t ORDER BY dept ASC, salary DESC`
- THEN 先按 `dept` 升序，再按 `salary` 降序

#### Scenario: 默认方向
- WHEN 仅指定 `ORDER BY id` 未指定方向
- THEN 默认 `ASC`

### REQ-QEX-5: LIMIT / OFFSET
The system MUST 应用 LIMIT 与 OFFSET 对结果集分页。

#### Scenario: 应用 LIMIT
- WHEN `LIMIT 10`
- THEN 最多返回 10 行

#### Scenario: 应用 OFFSET
- WHEN `OFFSET 5 LIMIT 10`
- THEN 跳过前 5 行，最多返回接下来的 10 行

### REQ-QEX-6: INSERT/UPDATE/DELETE 写入
The system MUST 支持 INSERT、UPDATE、DELETE 的执行与索引维护。

#### Scenario: INSERT 写入
- WHEN `INSERT INTO t VALUES (...)`
- THEN 记录写入堆
- AND 表上所有索引同步更新

#### Scenario: UPDATE 修改
- WHEN `UPDATE t SET a = 1 WHERE id = 5`
- THEN 命中记录就地更新 (in-place)
- AND 涉及索引的列被更新或删除再插入

#### Scenario: DELETE 标记
- WHEN `DELETE FROM t WHERE id = 5`
- THEN 命中记录标记为已删除
- AND 索引对应条目移除

### REQ-QEX-7: 结果格式
The system MUST 将 SELECT 结果返回为 `list[dict]`，每条 dict 的键为列名，值为已类型化的 Python 值。

#### Scenario: 列名作为键
- WHEN `SELECT id, name FROM users`
- THEN 返回 `[{"id": 1, "name": "alice"}, ...]`

#### Scenario: 类型转换
- WHEN 数据库中 INT 列存了 `42`
- THEN 返回的 dict 中该值为 Python `int(42)`

### REQ-QEX-8: 聚合函数
The system MUST 支持 `COUNT(*)`, `COUNT(col)`, `SUM(col)`, `AVG(col)` 的执行。

#### Scenario: COUNT 星号
- WHEN `SELECT COUNT(*) FROM t`
- THEN 返回一行一列，结果为 `int`，等于表中存活记录数

#### Scenario: COUNT 跳过 NULL
- WHEN `SELECT COUNT(x) FROM t` 且存在 `x IS NULL` 的行
- THEN NULL 不计入

#### Scenario: SUM/AVG
- WHEN `SELECT SUM(amount), AVG(amount) FROM t`
- THEN 返回数值合计与算术平均
- AND 对空集合返回 NULL/0 (按 SQL 约定)

### REQ-QEX-9: GROUP BY 分组
The system MUST 按 GROUP BY 列对记录分组，并对每组应用聚合。

#### Scenario: 分组计数
- WHEN `SELECT dept, COUNT(*) FROM emp GROUP BY dept`
- THEN 每行包含 `dept` 与该组计数

#### Scenario: 多列分组
- WHEN `GROUP BY dept, team`
- THEN 按 `(dept, team)` 元组分组
