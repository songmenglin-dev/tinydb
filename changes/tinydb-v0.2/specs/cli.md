# Spec: CLI 增强（v0.2）

## ADDED Requirements

### REQ-CLI-1: 多行编辑（反斜杠续行）
The system MUST 支持以反斜杠 `\` 结尾的行作为续行，直到遇到非续行结尾的 SQL 语句才执行。

#### Scenario: 单行 SQL 不变
- WHEN 输入 `SELECT * FROM users;` 并回车
- THEN 立即执行该语句并展示结果

#### Scenario: 反斜杠续行
- WHEN 输入 `SELECT *\` <回车> `FROM users;`
- THEN 第一行被识别为续行，提示 `...>`，第二行与第一行拼接为 `SELECT * FROM users;` 后执行
- AND 不抛错

#### Scenario: 多重续行
- WHEN 输入 5 行均以 `\` 结尾加 1 行 `;` 结尾
- THEN 全部 6 行拼接为单个 SQL 语句后执行
- AND 不抛错

### REQ-CLI-2: 未闭合引号自动续行
The system MUST 检测到未闭合的单引号/双引号时自动进入续行模式，无需显式 `\`。

#### Scenario: 未闭合字符串续行
- WHEN 输入 `SELECT * FROM users WHERE name = 'Alice` 并回车
- THEN 检测到未闭合 `'` 后提示 `...>`，继续接收
- AND 直到匹配 `'` 后才执行整个语句

#### Scenario: 双引号同效
- WHEN 输入 `WHERE city = "New ` 并回车
- THEN 进入续行模式
- AND 不抛错

### REQ-CLI-3: 历史导航
The system MUST 支持上/下方向键调用历史命令，并保持命令历史会话内可用。

#### Scenario: 上方向键加载上一条
- GIVEN 历史中存在 3 条命令
- WHEN 在空提示符处按上方向键
- THEN 当前行被替换为最近一条命令
- AND 继续按上方向键依次显示更早的命令

#### Scenario: 下方向键回退
- WHEN 在已加载历史项后按下方向键
- THEN 当前行被替换为更新的命令
- AND 到最新命令后回到空行

### REQ-CLI-4: 行内编辑
The system MUST 支持在当前行内自由移动光标、插入/删除字符，使用 `prompt_toolkit` 的 `PromptSession`。

#### Scenario: 方向键移动光标
- WHEN 在 `SELECT * FROM users;` 行中按左方向键 5 次
- THEN 光标停在 `users` 之后
- AND 继续输入字符插入到该位置

#### Scenario: Ctrl-A 行首 / Ctrl-E 行尾
- WHEN 按 Ctrl-A
- THEN 光标跳到行首
- WHEN 按 Ctrl-E
- THEN 光标跳到行尾

#### Scenario: Backspace 删除前字符
- WHEN 光标在第 5 个字符后按 Backspace
- THEN 删除第 4 个字符，光标回退
- AND 行内容更新

### REQ-CLI-5: ANSI 语法高亮
The system MUST 对 SQL 关键字、字符串字面量、数字字面量、注释分别使用 ANSI 颜色显示。

#### Scenario: 关键字着色
- WHEN 输入 `SELECT * FROM users`
- THEN `SELECT`、`FROM` 显示为蓝色或青色（关键字颜色）
- AND `users` 不着色（标识符）

#### Scenario: 字符串着色
- WHEN 输入 `WHERE name = 'Alice'`
- THEN `'Alice'` 显示为绿色（字符串颜色）
- AND 不抛错

#### Scenario: 数字着色
- WHEN 输入 `WHERE age > 18`
- THEN `18` 显示为黄色或橙色（数字颜色）
- AND 不抛错

#### Scenario: 注释着色
- WHEN 输入 `-- this is a comment`
- THEN `-- this is a comment` 显示为灰色（注释颜色）
- AND 不抛错

### REQ-CLI-6: .explain 命令
The system MUST 支持 `.explain <SQL>` 输出 LogicalPlan 与 PhysicalPlan 的树形可视化。

#### Scenario: 单表 SELECT 计划
- WHEN 执行 `.explain SELECT * FROM users WHERE age > 18`
- THEN 输出包含 LogicalPlan 节（含 Filter, Scan）和 PhysicalPlan 节（含 SeqScan on users）
- AND 树形缩进清晰，每层用 `├──`/`└──` 标识

#### Scenario: JOIN 计划
- WHEN 执行 `.explain SELECT * FROM users u JOIN orders o ON u.id = o.user_id`
- THEN PhysicalPlan 节显示 `IndexedNestedLoopJoin` 或 `NestedLoopJoin`
- AND 标注驱动表与被探测表

#### Scenario: 错误 SQL 报错
- WHEN 执行 `.explain SELECT FROMM users`
- THEN 提示 ParseError，包含行列号
- AND 不输出计划

### REQ-CLI-7: .tables / .schema 元命令
The system MUST 提供 `.tables` 列出当前数据库所有表名，`.schema <table>` 打印建表 DDL。

#### Scenario: .tables 列出表
- GIVEN 数据库中存在 users、orders、products 三张表
- WHEN 执行 `.tables`
- THEN 输出三行：orders / products / users（字母序）
- AND 不抛错

#### Scenario: .schema 输出 DDL
- GIVEN users(id INT PRIMARY KEY, name TEXT NOT NULL, age INT)
- WHEN 执行 `.schema users`
- THEN 输出 `CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL, age INT);`
- AND 格式与原 CREATE 语句语义一致

#### Scenario: .schema 表不存在
- WHEN 执行 `.schema nonexistent`
- THEN 抛出错误信息 `table 'nonexistent' does not exist`
- AND 不抛错

### REQ-CLI-8: .history 命令与持久化
The system MUST 支持 `.history` 显示最近 N 条命令（默认 50），并将会话历史持久化到 `~/.tinydb_history`。

#### Scenario: .history 显示
- GIVEN 会话内执行了 7 条 SQL
- WHEN 执行 `.history`
- THEN 列出 7 条带编号的命令
- AND 不抛错

#### Scenario: 退出时持久化
- WHEN REPL 正常退出（输入 `.quit` 或 EOF）
- THEN 全部历史追加写入 `~/.tinydb_history`
- AND 下次启动 REPL 时历史从该文件加载

#### Scenario: 历史文件不可写降级
- WHEN `~/.tinydb_history` 不可写
- THEN 打印警告但 REPL 继续运行
- AND 不抛错

### REQ-CLI-9: prompt_toolkit 不可用降级
The system MUST 在 `prompt_toolkit` 未安装时回退到 v0.1 的 `cmd` 模块行为，仅多行编辑、行内编辑、语法高亮不可用，其他命令可用。

#### Scenario: 缺失依赖检测
- GIVEN `prompt_toolkit` 未安装
- WHEN 启动 REPL
- THEN 启动时打印 `[tinydb] prompt_toolkit not installed; CLI running in basic mode (no multi-line editing, no syntax highlight).`
- AND 提示符退化为 v0.1 的 `tinydb>`

#### Scenario: 基础模式功能可用
- WHEN 基础模式下输入 `SELECT * FROM users;`
- THEN 单行 SQL 正常执行
- AND `.tables`、`.schema`、`.explain`、`.history` 全部可用

### REQ-CLI-10: Ctrl-C 中断与 .quit 退出
The system MUST 支持 Ctrl-C 中断当前输入，`.quit` 或 EOF 退出 REPL。

#### Scenario: Ctrl-C 清空当前行
- WHEN 在多行编辑中按 Ctrl-C
- THEN 当前未提交的多行缓冲被丢弃
- AND 提示符回到主提示符

#### Scenario: .quit 干净退出
- WHEN 在主提示符输入 `.quit`
- THEN REPL 打印 `Bye.` 并退出进程
- AND 退出码 0

#### Scenario: EOF 退出
- WHEN 在主提示符按 Ctrl-D（发送 EOF）
- THEN REPL 打印 `Bye.` 并退出
- AND 历史已持久化

### REQ-CLI-11: 兼容 v0.1 REPL 命令
The system MUST 保持 v0.1 REPL 所有现有命令工作，所有 727 个 CLI 测试通过。

#### Scenario: 现有命令不变
- WHEN 在 v0.2 REPL 中输入 v0.1 已有的任何 SQL 或元命令
- THEN 行为与 v0.1 完全一致（除已声明的新功能外）
- AND 727 个 v0.1 CLI 测试 100% 通过

### REQ-CLI-12: SELECT 结果 ASCII 表格输出
The system MUST 将 SELECT 查询结果以 MySQL CLI 风格的 ASCII 表格渲染：列头位于 `+---+---+` 边框之间，每行用 `|` 分隔，NULL 显示为字面量 `NULL`。

#### Scenario: 表格渲染
- GIVEN 表 users 含 (1,'Alice',30)、(2,'Bob',25)
- WHEN 执行 `SELECT * FROM users`
- THEN 输出包含 3 行（1 表头 + 2 数据）+ 顶部/中部/底部三道 `+---+---+` 边框
- AND 表头行形如 `| id | name | age |`
- AND 不抛错

#### Scenario: 空结果表格
- WHEN 执行 `SELECT * FROM empty_table`
- THEN 仍输出表头与边框（3 道 `+---+---+`），数据行为空
- AND 在表格下方显示 `Empty set (X.XXs)`
- AND 不抛错

#### Scenario: NULL 显示为字面量
- GIVEN 表含 (1, NULL, 18)
- WHEN 执行 `SELECT * FROM nullable`
- THEN NULL 列显示为 `NULL`，非空列显示实际值
- AND 不抛错

### REQ-CLI-13: 行数与耗时统计
The system MUST 在 SELECT 结果表格下方显示 `N rows in set (X.XXs)`，其中 N 为返回行数，X.XXs 为执行耗时。

#### Scenario: 正常耗时显示
- WHEN 执行 `SELECT * FROM users`
- THEN 表格下方显示 `5 rows in set (0.02s)`（耗时秒数取两位小数）
- AND 不抛错

#### Scenario: 零行结果
- WHEN 执行 `SELECT * FROM empty_table`
- THEN 显示 `Empty set (0.00s)`
- AND 不抛错

#### Scenario: 慢查询阈值
- WHEN 查询耗时超过 1 秒
- THEN 显示 `N rows in set (1.23s)`（保留秒的小数）
- AND 不抛错

#### Scenario: 仅 SELECT 计时
- WHEN 执行 `INSERT`、`UPDATE`、`CREATE TABLE` 等非 SELECT 语句
- THEN 不显示 `rows in set` 文案（只显示成功消息）
- AND 不抛错

### REQ-CLI-14: 列对齐规则
The system MUST 按列类型应用不同对齐：数值（INT/FLOAT/DECIMAL）右对齐，字符串（TEXT/JSON/DATE/TIME/DATETIME）左对齐，BLOB 以十六进制 `0x...` 显示，NULL 字面量 `NULL`。

#### Scenario: 数值右对齐
- GIVEN 列含 (1, 2, 100)
- WHEN 显示结果
- THEN 每列右端对齐（短值左侧填充空格）
- AND 不抛错

#### Scenario: 字符串左对齐
- GIVEN 列含 ('a', 'bb', 'ccc')
- WHEN 显示结果
- THEN 每列左端对齐（短值右侧填充空格）
- AND 不抛错

#### Scenario: BLOB 十六进制
- GIVEN BLOB 值 `\x01\x02\x03`
- WHEN 显示结果
- THEN 显示为 `0x010203`（小写 hex，无空格）
- AND 不抛错

#### Scenario: 列宽自适应
- GIVEN 列含 ('short')、('a-very-long-string')
- WHEN 显示结果
- THEN 列宽 = max(列头宽度, 最长值宽度)
- AND 每行用相同列宽对齐

### REQ-CLI-15: 元命令输出表格化
The system MUST 对 `.tables`/`.schema`/`.explain` 等元命令输出应用 ASCII 表格样式（边框 + 对齐规则）；`.tables` 表格化、`.schema` 表格化单列 DDL 字符串、`.explain` 可选表格化或保留树形（用户偏好）；保留 ANSI 颜色与提示符文案。

#### Scenario: .tables 输出表格
- GIVEN 三张表 orders, products, users
- WHEN 执行 `.tables`
- THEN 输出 ASCII 表格，含单列 `Tables_in_<db>`（或 `Table`），3 行数据
- AND 边框完整
- AND 不抛错

#### Scenario: .schema 输出表格
- GIVEN users 表
- WHEN 执行 `.schema users`
- THEN 输出表格，单列 `DDL`，1 行内容为 `CREATE TABLE users (...);`
- AND 不抛错

#### Scenario: .explain 表格化或树形可切换
- WHEN 执行 `.explain SELECT * FROM users`
- THEN 默认输出树形（v0.2 树形规则）
- AND `.explain --table SELECT * FROM users` 切换为表格输出
- AND 不抛错

#### Scenario: 表格保留 ANSI 颜色
- WHEN 启用 prompt_toolkit 的着色且输出为表格
- THEN 列名仍按 SQL 关键字着色
- AND 不抛错

### REQ-CLI-16: 表格输出可禁用
The system MUST 支持 `.mode line`（默认表格）或 `.mode table` 切换；`line` 模式下每行 `column = value` 形式。

#### Scenario: 切到 line 模式
- WHEN 输入 `.mode line` 后执行 `SELECT * FROM users`
- THEN 每行格式为 `id = 1\nname = 'Alice'\nage = 30`（每行一列）
- AND 不抛错

#### Scenario: 切回 table 模式
- WHEN 输入 `.mode table` 后执行 `SELECT * FROM users`
- THEN 恢复 ASCII 表格输出
- AND 不抛错