# Spec: 类型系统

## ADDED Requirements

### REQ-TYP-1: 整数类型 INT
The system MUST 支持有符号 64 位整数 (INT)。

#### Scenario: 接受整数字面量
- WHEN `INSERT INTO t (n) VALUES (42)`
- THEN 存储为 INT，读取时返回 Python `int`

#### Scenario: 拒绝浮点字面量到 INT
- WHEN `INSERT INTO t (n) VALUES (3.14)` 且列类型为 INT
- THEN 抛出类型错误 (除非满足强制规则)

### REQ-TYP-2: 浮点类型 FLOAT
The system MUST 支持 IEEE 754 双精度浮点 (FLOAT)。

#### Scenario: 接受浮点字面量
- WHEN `INSERT INTO t (p) VALUES (9.99)`
- THEN 存储为 FLOAT，读取时返回 Python `float`

### REQ-TYP-3: 文本类型 TEXT
The system MUST 支持 UTF-8 变长字符串 (TEXT)。

#### Scenario: 接受字符串字面量
- WHEN `INSERT INTO t (s) VALUES ('hello 世界')`
- THEN 存储为 TEXT，读取时返回 Python `str`

#### Scenario: TEXT 最大长度
- WHEN TEXT 字段超过单页可用空间
- THEN 系统跨页存储记录

### REQ-TYP-4: 布尔类型 BOOL
The system MUST 支持布尔值 (BOOL)，存储为 `TRUE` / `FALSE` 之一。

#### Scenario: 接受布尔字面量
- WHEN `INSERT INTO t (b) VALUES (TRUE)`
- THEN 存储为 BOOL，读取时返回 Python `bool`

#### Scenario: 拒绝任意整数到 BOOL
- WHEN `INSERT INTO t (b) VALUES (1)` 且列类型为 BOOL
- THEN 仅接受 `TRUE` / `FALSE` 字面量，否则抛错

### REQ-TYP-5: NULL 值
The system MUST 支持 NULL 作为可与任何类型共存的特殊值。

#### Scenario: 存储 NULL
- WHEN `INSERT INTO t (x) VALUES (NULL)`
- THEN x 存储为 NULL

#### Scenario: NULL 不参与 NOT NULL
- WHEN 列定义为 `NOT NULL` 且插入 NULL
- THEN 抛出 `NotNullViolation`

#### Scenario: NULL 不参与 UNIQUE
- WHEN 列定义为 UNIQUE
- THEN 多个 NULL 不构成冲突

### REQ-TYP-6: 类型强制规则
The system MUST 允许有限的隐式类型转换，禁止静默丢失精度的强制。

#### Scenario: 整数到浮点的强制
- WHEN `INSERT INTO t (p FLOAT) VALUES (3)` 字面量为整数
- THEN 系统将其强制为浮点 `3.0`

#### Scenario: 浮点到整数的拒绝
- WHEN `INSERT INTO t (n INT) VALUES (3.14)`
- THEN 抛出类型错误

#### Scenario: 字符串到数字的拒绝
- WHEN `INSERT INTO t (n INT) VALUES ('3')`
- THEN 抛出类型错误 (不允许隐式字符串→数字)

### REQ-TYP-7: 比较运算的类型
The system MUST 仅允许同类型 (或 NULL) 之间的比较运算。

#### Scenario: 不同类型比较报错
- WHEN `WHERE int_col = '5'`
- THEN 抛出类型错误

#### Scenario: 任意类型与 NULL 比较
- WHEN `WHERE col IS NULL` / `IS NOT NULL`
- THEN 合法

### REQ-TYP-8: 类型在 schema 中持久化
The system MUST 将列类型持久化在表元数据中，并据此执行类型检查。

#### Scenario: 重启后类型保留
- WHEN 关闭并重新打开数据库
- THEN 表中每列的类型与创建时一致
- AND INSERT / UPDATE 仍按原类型校验

### REQ-TYP-9: 日期类型 DATE
The system MUST 支持 DATE 类型，存储为 ISO-8601 格式 `YYYY-MM-DD` 的日历日期，无时区与时间分量。

#### Scenario: 接受日期字面量
- WHEN `INSERT INTO t (d) VALUES (DATE '2026-07-09')`
- THEN 存储为 DATE，读取时返回 Python `datetime.date`

#### Scenario: 非法日期格式
- WHEN `INSERT INTO t (d) VALUES ('2026-13-40')`
- THEN 抛出类型/格式错误

#### Scenario: DATE 范围比较
- WHEN `WHERE d >= DATE '2026-01-01'`
- THEN 按日历顺序比较

### REQ-TYP-10: 时间类型 TIME
The system MUST 支持 TIME 类型，存储为 `HH:MM:SS[.ffffff]` 一天内的时间，无日期与时区。

#### Scenario: 接受时间字面量
- WHEN `INSERT INTO t (t) VALUES (TIME '14:30:00')`
- THEN 存储为 TIME，读取时返回 Python `datetime.time`

#### Scenario: TIME 范围比较
- WHEN `WHERE t BETWEEN TIME '09:00:00' AND TIME '17:00:00'`
- THEN 按时间顺序比较

### REQ-TYP-11: 日期时间类型 DATETIME
The system MUST 支持 DATETIME 类型，存储为 `YYYY-MM-DD HH:MM:SS[.ffffff]` 的本地日期时间。

#### Scenario: 接受日期时间字面量
- WHEN `INSERT INTO t (ts) VALUES (DATETIME '2026-07-09 14:30:00')`
- THEN 存储为 DATETIME，读取时返回 Python `datetime.datetime`

#### Scenario: DATETIME 字面量缺秒
- WHEN `INSERT INTO t (ts) VALUES (DATETIME '2026-07-09 14:30')`
- THEN 缺省秒为 0

### REQ-TYP-12: 精确小数 DECIMAL
The system MUST 支持 DECIMAL 类型，以定点数 (基于 `decimal.Decimal`) 存储任意精度数值，不引入二进制浮点误差。

#### Scenario: 接受 DECIMAL 字面量
- WHEN `INSERT INTO t (m) VALUES (DECIMAL '1234.56')`
- THEN 存储为 DECIMAL，读取时返回 Python `decimal.Decimal`

#### Scenario: DECIMAL 比较
- WHEN `WHERE m = DECIMAL '0.10'`
- THEN 按精确值 `0.10` 比较，不转为浮点

#### Scenario: DECIMAL 精度与标度
- WHEN 列定义 `DECIMAL(18, 4)` 显式精度
- THEN 超过标度的值四舍五入或拒绝 (实现需文档化)

### REQ-TYP-13: 二进制大对象 BLOB
The system MUST 支持 BLOB 类型，存储原始字节序列。

#### Scenario: 接受字节字面量
- WHEN `INSERT INTO t (b) VALUES (BLOB '...')` (hex 或 base64 编码)
- THEN 存储为 BLOB，读取时返回 Python `bytes`

#### Scenario: BLOB 大小限制
- WHEN BLOB 字段超过单页可用空间
- THEN 系统跨页存储

### REQ-TYP-14: JSON 文档类型 JSON
The system MUST 支持 JSON 类型，存储结构化 JSON 值 (对象/数组/标量) 并在写入时校验合法性。

#### Scenario: 接受 JSON 对象
- WHEN `INSERT INTO t (j) VALUES (JSON '{"k": 1, "arr": [1,2,3]}')`
- THEN 存储为 JSON，读取时返回 Python `dict` / `list` / 标量

#### Scenario: 非法 JSON 拒绝
- WHEN `INSERT INTO t (j) VALUES (JSON '{not valid}')`
- THEN 抛出 JSON 解析错误

#### Scenario: JSON 路径访问 (可选)
- WHEN `SELECT j->>'k' FROM t`
- THEN 提取 JSON 中键 `k` 的值 (若实现支持路径操作符)
