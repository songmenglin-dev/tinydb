# Spec: SQL JOIN（v0.2）

## ADDED Requirements

### REQ-JOIN-1: INNER JOIN 语法解析
The system MUST parse `SELECT ... FROM t1 INNER JOIN t2 ON <expr>` into a valid JoinPlan AST.

#### Scenario: 两表 INNER JOIN
- WHEN 解析 `SELECT u.id, o.total FROM users u INNER JOIN orders o ON u.id = o.user_id`
- THEN AST 包含 LeftPlan(users)、RightPlan(orders)、JoinKind=INNER、ON=`u.id = o.user_id`
- AND 不抛错

#### Scenario: INNER JOIN 可省略 INNER 关键字
- WHEN 解析 `SELECT * FROM a JOIN b ON a.id = b.aid`
- THEN JoinKind 推断为 INNER
- AND 不抛错

#### Scenario: 缺少 ON 条件报错
- WHEN 解析 `SELECT * FROM a INNER JOIN b`
- THEN 抛出 `ParseError`，错误信息指明 "JOIN requires ON or USING clause"

### REQ-JOIN-2: LEFT JOIN 语法解析
The system MUST parse `LEFT JOIN` 并在 AST 中标记 JoinKind=LEFT。

#### Scenario: 显式 LEFT JOIN
- WHEN 解析 `SELECT * FROM users LEFT JOIN orders ON users.id = orders.user_id`
- THEN JoinKind=LEFT，RightPlan(orders) 标记 nullable=True
- AND 不抛错

#### Scenario: LEFT OUTER JOIN 等价
- WHEN 解析 `SELECT * FROM users LEFT OUTER JOIN orders ON ...`
- THEN JoinKind=LEFT
- AND 不抛错

### REQ-JOIN-3: USING 子句
The system MUST parse `JOIN t USING (col1, col2)` 并生成等价的 ON 条件 `t1.col1 = t2.col1 AND t1.col2 = t2.col2`，投影时去除重复列。

#### Scenario: 单列 USING
- WHEN 解析 `SELECT * FROM users JOIN orders USING (user_id)`
- THEN JoinPlan 的 on_expr 等价于 `users.user_id = orders.user_id`
- AND 投影阶段去除 user_id 重复列

#### Scenario: 多列 USING
- WHEN 解析 `SELECT * FROM t1 JOIN t2 USING (a, b)`
- THEN on_expr 包含两列相等比较
- AND 不抛错

### REQ-JOIN-4: 表别名
The system MUST 接受 `FROM table_name alias` 形式，且后续引用全部通过别名解析。

#### Scenario: 别名引用
- WHEN 解析 `SELECT u.name FROM users u WHERE u.age > 18`
- THEN ColumnRef 节点中所有 `u.*` 解析为 users 表的列
- AND 不抛错

#### Scenario: 别名与原名混用报错
- WHEN 解析 `SELECT users.name FROM users u`
- THEN 抛出 `ParseError`，错误信息 "table users not aliased; use u.name instead"

### REQ-JOIN-5: 嵌套 JOIN（最多 5 层）
The system MUST 支持 JOIN 表达式嵌套解析，深度上限 5。

#### Scenario: 三表 INNER JOIN
- WHEN 解析 `SELECT * FROM a JOIN b ON a.id=b.aid JOIN c ON b.id=c.bid`
- THEN AST 为 LeftPlan=JoinPlan(a,b)，RightPlan=c（深度 2）
- AND 物理计划生成顺序为 (a ⋈ b) ⋈ c

#### Scenario: 超过 5 层报错
- WHEN 解析 6 层嵌套 JOIN
- THEN 抛出 `ParseError`，错误信息 "JOIN nesting depth exceeds 5"

### REQ-JOIN-6: NestedLoopJoin 执行
The system MUST 实现 NestedLoopJoin 算子：对左输入的每一行，扫描右输入并应用 ON 条件；对 LEFT JOIN，未匹配的右行以 NULL 填充。

#### Scenario: INNER JOIN 基础执行
- GIVEN users=[(1,'Alice'),(2,'Bob')]; orders=[(1,100),(1,200),(3,50)]
- WHEN 执行 `SELECT * FROM users u INNER JOIN orders o ON u.id = o.user_id`
- THEN 返回 3 行（id=1 两条 + id=2 零条）
- AND 每行包含 users.* + orders.* 两组列

#### Scenario: LEFT JOIN 保留左表
- GIVEN 同上
- WHEN 执行 `SELECT * FROM users u LEFT JOIN orders o ON u.id = o.user_id`
- THEN 返回 3 行：id=1 两条 + id=2 一条（orders.* 全 NULL）
- AND 不抛错

### REQ-JOIN-7: IndexedNestedLoopJoin 优化
当连接条件的左列有 B-tree 索引且外层表小于内层表时，Planner MUST 选择 IndexedNestedLoopJoin 替代 NestedLoopJoin。

#### Scenario: 索引可用时选择 INLJ
- GIVEN users.id 有 B-tree 索引；users 100 行；orders 10k 行
- WHEN Planner 优化 `SELECT * FROM users u JOIN orders o ON u.id = o.user_id`
- THEN PhysicalPlan 包含 IndexedNestedLoopJoin
- AND 外层为 users（驱动表），内层为 orders（被探测）

#### Scenario: 无索引回退 NestedLoop
- GIVEN orders.user_id 无索引
- WHEN Planner 处理相同 SQL
- THEN PhysicalPlan 包含 NestedLoopJoin
- AND 不抛错

### REQ-JOIN-8: JOIN 列投影去歧义
The system MUST 在投影阶段去除 USING/JOIN 引入的重复列，并对未限定的列名报错。

#### Scenario: SELECT * 去重
- WHEN 执行 `SELECT * FROM users JOIN orders USING (user_id)`
- THEN 返回列仅包含 user_id 一次，加 users.name + orders.total
- AND 不抛错

#### Scenario: 未限定列名报错
- WHEN 执行 `SELECT name FROM users JOIN orders ON ...`（两表均有 name）
- THEN 抛出 `AmbiguousColumnError`，提示 `users.name` 或 `orders.name`

### REQ-JOIN-9: JOIN 与 WHERE 共存
The system MUST 先执行 JOIN，再对连接结果应用 WHERE 过滤。

#### Scenario: WHERE 作用于连接后
- GIVEN 三行 orders 中 user_id=2 一行
- WHEN 执行 `SELECT * FROM users u JOIN orders o ON u.id=o.user_id WHERE o.total > 100`
- THEN 返回仅 user_id=1 的 2 条订单
- AND 不抛错

### REQ-JOIN-10: 兼容 v0.1 单表 SELECT
The system MUST 保持 v0.1 单表 `SELECT ... FROM t` 行为不变，所有 826 个现有测试通过。

#### Scenario: 单表 SELECT 不变
- WHEN 执行 v0.1 任何 `SELECT ... FROM single_table` 形式
- THEN 结果与 v0.1 完全一致（字节级）
- AND Planner 不为单表生成 JoinPlan