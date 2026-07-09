# Spec: CLI / REPL

## ADDED Requirements

### REQ-CLI-1: 启动与数据库路径
The system MUST 提供 `tinydb` 命令行入口，接受可选的数据库文件路径参数。

#### Scenario: 打开指定数据库
- WHEN `tinydb /path/to/data.db`
- THEN REPL 启动并打开该数据库
- AND 提示符显示当前数据库路径

#### Scenario: 不带参数启动
- WHEN `tinydb` 不带参数
- THEN REPL 启动，使用 `:memory:` 或临时数据库
- AND 修改在退出时不持久化 (除非显式保存)

### REQ-CLI-2: SQL 输入与执行
The system MUST 在 REPL 提示符下接受 SQL 输入并执行。

#### Scenario: 单行 SQL
- WHEN 用户输入 `SELECT * FROM users;` 并按回车
- THEN 执行该 SQL 并显示结果

#### Scenario: 提示符
- WHEN REPL 等待输入
- THEN 显示类似 `tinydb>` 的提示符

### REQ-CLI-3: 结果展示
The system MUST 以表格形式展示 SELECT 结果。

#### Scenario: 表格输出
- WHEN SELECT 返回 N 行 M 列
- THEN 输出包含表头 (列名) 与 N 行数据
- AND 列宽根据内容自适应

#### Scenario: 空结果
- WHEN SELECT 返回 0 行
- THEN 显示 `0 rows` 或等效提示，不显示空表

#### Scenario: 非 SELECT 语句
- WHEN 执行 DDL/DML
- THEN 显示受影响行数或操作成功的提示

### REQ-CLI-4: 错误显示
The system MUST 将解析错误、执行错误、约束错误以人类可读的方式打印至 stderr (或 REPL 中可见)。

#### Scenario: 解析错误
- WHEN 输入不符合语法
- THEN 显示 `ParseError: <message>` 包含行/列位置

#### Scenario: 约束错误
- WHEN INSERT 违反 UNIQUE
- THEN 显示 `ConstraintViolation: <message>`

### REQ-CLI-5: 内置元命令
The system MUST 支持至少以下元命令：`.exit`, `.quit`, `.help`, `.tables`, `.schema <table>`。

#### Scenario: 退出 REPL
- WHEN 用户输入 `.exit` 或 `.quit`
- THEN 正常退出 (退出码 0)
- AND 若有打开的数据库，先关闭

#### Scenario: 列出表
- WHEN 用户输入 `.tables`
- THEN 显示当前数据库中所有表名

#### Scenario: 查看 schema
- WHEN 用户输入 `.schema users`
- THEN 显示 `users` 表的列定义

#### Scenario: 帮助
- WHEN 用户输入 `.help`
- THEN 显示可用元命令列表

### REQ-CLI-6: 多行输入
The system MUST 允许 SQL 语句跨越多行，以 `;` 作为语句结束符。

#### Scenario: 多行 SELECT
- WHEN 用户输入未以 `;` 结尾的多行文本
- THEN REPL 显示续行提示符
- AND 在收到 `;` 时执行整条语句

### REQ-CLI-7: 命令行参数
The system MUST 支持 `-h` / `--help` 显示用法。

#### Scenario: 查看帮助
- WHEN `tinydb --help`
- THEN 输出到 stdout，包含用法、参数与示例

#### Scenario: 未知选项
- WHEN `tinydb --unknown`
- THEN 输出错误信息并以非零退出码退出

### REQ-CLI-8: 一次性执行
The system MUST 支持 `-c "<SQL>"` 或 `--command "<SQL>"` 执行单条 SQL 并退出。

#### Scenario: 一次性查询
- WHEN `tinydb data.db -c "SELECT * FROM users"`
- THEN 执行 SQL，将结果输出到 stdout
- AND 进程退出码为 0
