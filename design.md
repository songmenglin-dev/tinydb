# Design: tinydb

## Context

- **起点**: 空仓库，仅 `proposal.md` + `specs/`(7 文件, 61 REQ)
- **目标产物**: 可嵌入 Python 包 `tinydb` + CLI `tinydb` REPL
- **使用模型**: 进程内单连接，单写入者；不要求多线程/多进程安全（与 `proposal.md > Out` 一致）
- **持久化模型**: 单文件 `.db`，内部按 4KB 页组织
- **硬约束**（来自 `dp_0_decisions`）: Python 3.10+、零外部依赖、单 `.db` 文件、B-tree 索引、WAL 事务、pytest 80%+
- **目标用户**: 教学者、想自顶向下理解 RDB 内核的工程师、需要可读嵌入式 RDB 的小项目作者
- **非目标**（来自 `proposal.md > Out`）: JOIN、并发、ALTER/视图/触发器/外键、客户端-服务器

## Goals

1. **可读性优先**: 每个模块 200-400 行，关键路径带 docstring 解释"为什么"
2. **可测试性**: 所有 capability 都先写 pytest 用例（RED→GREEN→IMPROVE）
3. **正确性**: ACID 语义经得起断电/崩溃场景测试
4. **教学完整**: 涵盖存储→解析→执行→索引→事务→类型→CLI 完整 RDB 知识链
5. **零依赖**: 仅 Python stdlib（`struct`, `os`, `decimal`, `datetime`, `json`, `base64`, `cmd`, `argparse`）
6. **接口简洁**: `tinydb.open(path)` → `Database`，核心方法 `db.execute(sql) -> list[dict]`

## Decisions

### D-1: SQL 解析器使用手写递归下降
- **Choice**: 在 `tinydb/sql/parser.py` 手工实现 tokenizer + recursive-descent parser
- **Rationale**:
  - 零外部依赖（PLY/lark/pyparsing 都需要安装）
  - SQL 子集小（DDL + DML + WHERE/ORDER/GROUP），手写可行
  - 教学价值高：可见完整解析过程
  - 错误位置精确（行/列）
- **Alternatives considered**:
  - **PLY**: 成熟但增加构建步骤（PLY 需先生成 LEX/YACC 表）
  - **lark**: 强大但依赖外部库
  - **pyparsing**: 灵活但运行慢、可读性反而差
- **Trade-off**: 解析器约 600-800 行 vs 几十行 PLY；接受代码量换可控性

### D-2: 页式存储（4KB 固定页）
- **Choice**: 在 `tinydb/storage/pager.py` 实现 4KB 固定页，文件头记录 magic + version + page_size
- **Rationale**:
  - 符合"真实 RDB"心智模型
  - B-tree 节点天然按页对齐
  - 缓冲池替换单位清晰
  - 单文件持久化天然契合
- **Alternatives considered**:
  - **变长页**: 灵活但元数据管理复杂
  - **in-memory dict + pickle**: 简单但无法演示真实存储引擎
  - **mmap**: 性能好但掩盖 I/O 细节，不利于教学
- **Trade-off**: 实现成本 vs 教学价值，倾向教学

### D-3: LRU 缓冲池（默认 64 页 = 256KB）
- **Choice**: `tinydb/storage/buffer_pool.py` 使用 `collections.OrderedDict` 实现 LRU
- **Rationale**:
  - Python stdlib 即够
  - 单进程下 LRU 命中率足够
  - 易于测试和可视化
- **Alternatives considered**:
  - **Clock-sweep**: 略复杂，常数更小
  - **ARC**: 强大但对单进程过设计

### D-4: 索引使用经典 B-tree（不分离 B+tree）
- **Choice**: `tinydb/index/btree.py` 实现 order=64 的 B-tree，叶子存 (key, rid) 对
- **Rationale**:
  - `proposal.md` 明确写 "B-tree"
  - 叶子存 rid 而非完整记录 → 索引紧凑
  - 范围扫描天然支持（叶子链表可有可无，先做"顺序叶子"）
  - 比 B+tree 简单一档
- **Alternatives considered**:
  - **Hash 索引**: 等值快但无范围扫描
  - **B+tree**: 范围扫描更优但实现复杂
  - **Skip list**: 简单但需更多层

### D-5: 事务使用 Write-Ahead Log (WAL)
- **Choice**: `tinydb/tx/wal.py` 实现 append-only WAL + `recovery.py` 实现 REDO/UNDO
- **Rationale**:
  - 写日志顺序 I/O，性能较好
  - 崩溃恢复路径清晰（重做 + 撤销）
  - 业界标准（PostgreSQL/SQLite 均用 WAL）
- **Alternatives considered**:
  - **影子分页 (Shadow paging)**: 简单但 I/O 加倍，不适合频繁写
  - **整文件重写**: 太慢

### D-6: 单写者锁（`threading.RLock` 但不强制多线程）
- **Choice**: `tinydb/tx/lock.py` 提供 `WriteLock` 上下文管理器；同一进程内仅允许一个活动事务
- **Rationale**:
  - 与 `proposal.md > Out: 并发控制` 一致
  - 简化事务实现，避免死锁
  - 接口允许将来扩展为多线程
- **Alternatives considered**:
  - **MVCC**: 强大但对教学项目过重
  - **纯无锁**: 难以保证正确性

### D-7: 序列化采用 1 字节 tag + payload
- **Choice**: `tinydb/types/codec.py` 定义 `TypeTag` 枚举（`INT=0x01`, `FLOAT=0x02`, `TEXT=0x03`, `BOOL=0x04`, `NULL=0x00`, `DATE=0x05`, `TIME=0x06`, `DATETIME=0x07`, `DECIMAL=0x08`, `BLOB=0x09`, `JSON=0x0A`），定长类型直接 pack，变长类型用 `length-prefix`
- **Rationale**:
  - 灵活支持 10 种类型
  - 易于扩展（加新 tag）
  - TEXT/BLOB/JSON/DECIMAL 自然处理变长
  - 页内连续字节，对齐良好
- **Alternatives considered**:
  - **struct 固定布局**: 紧凑但变长难处理
  - **JSON 通用序列化**: 简单但 INT/FLOAT/DECIMAL 不如原生高效

### D-8: CLI 使用 stdlib `cmd.Cmd`
- **Choice**: `tinydb/cli/repl.py` 继承 `cmd.Cmd`；参数解析用 `argparse`
- **Rationale**:
  - 零外部依赖
  - 提示符/历史/多行都由 `cmd` 提供
- **Alternatives considered**:
  - **prompt_toolkit**: 体验好但需外部依赖
  - **自己手写 readline 循环**: 重复造轮子

### D-9: 项目布局 `src/tinydb/`
- **Choice**: `src/tinydb/{sql,storage,index,tx,types,cli}/`，测试在 `tests/`
- **Rationale**:
  - 标准 Python 包布局
  - 强制通过 `pip install -e .` 验证导入路径
  - 测试与源码分离
- **Alternatives considered**:
  - **flat layout**: 更简单但容易污染命名空间
  - **单文件库**: 不适合 5000+ 行的 RDB

### D-10: 测试策略 — pytest + TDD 每 capability
- **Choice**: `tests/` 镜像 `src/tinydb/` 目录结构；每个 REQ 至少一个集成测试
- **Rationale**:
  - 满足 80%+ 覆盖率硬要求
  - 符合 `coding-style.md` 的 TDD 强制流程
- **Alternatives considered**:
  - **unittest**: 同样能力但 pytest fixture 更简洁
  - **doctest**: 适合文档但 ACID 场景难表达

### D-11: DECIMAL 使用 `decimal.Decimal` 存储为字符串
- **Choice**: 在 codec 中以 `str` 形式存 `Decimal`，读取时 `Decimal(s)`
- **Rationale**:
  - 零依赖
  - 任意精度
  - 序列化稳定（无浮点误差）
- **Alternatives considered**:
  - **二进制十进制 (BID)**: 标准但 Python 无原生支持
  - **int × 10^scale**: 紧凑但调用方处理 scale

### D-12: JSON 解析使用 stdlib `json`
- **Choice**: 写入校验合法性，存储为 `repr` 形式，读取反序列化
- **Rationale**:
  - 零依赖
  - 严格规范
- **Alternatives considered**:
  - **simplejson**: 性能好但外部依赖

### D-13: BLOB 字面量用 base64
- **Choice**: SQL 字面量 `BLOB '...'` 接受 base64 字符串
- **Rationale**:
  - SQL 文本可打印
  - stdlib `base64` 即够
- **Alternatives considered**:
  - **hex**: 可读但 base64 更紧凑

## Risks And Trade-Offs

### R-1: 性能
- **Risk**: 纯 Python I/O 与 B-tree 比较，10w 行以上表会明显慢
- **Mitigation**:
  - 缓冲池 + LRU 减少磁盘访问
  - 索引在 WHERE 命中时跳过全表扫描
  - 文档明确"教学用"定位
  - 不做性能基准作为 acceptance

### R-2: B-tree 重新平衡复杂度
- **Risk**: 节点删除时的合并/重分配 bug 率高
- **Mitigation**:
  - 采用"先标记为墓碑，定期重建"或"经典合并"二选一，先做经典
  - 大量 pytest 用例覆盖边界（连续删除、删除最左/最右、级联）
  - 独立 PR 聚焦 B-tree，配 review

### R-3: WAL 恢复正确性
- **Risk**: 崩溃恢复时的 REDO/UNDO 顺序、LSN 检查点最容易出错
- **Mitigation**:
  - 先写"模糊测试"：随机序列操作 → 强杀进程 → 重启验证
  - `tests/recovery/` 独立目录
  - 关键路径加大量日志断言

### R-4: SQL 解析边界
- **Risk**: 注释、大小写、引号转义、Unicode 标识符
- **Mitigation**:
  - `specs/sql-parser.md` 已定义错误报告（行/列）
  - 解析器 `tests/sql/` 覆盖 50+ 句子
  - 不支持的语法明确报清晰错误而非静默

### R-5: 覆盖率
- **Risk**: CLI、异常路径、WAL 恢复容易漏测
- **Mitigation**:
  - `pytest --cov=tinydb --cov-fail-under=80` 加入 CI/本地门禁
  - `tests/cli/` 用 subprocess + 临时 db 文件跑端到端
  - WAL 恢复用 fixture 模拟崩溃（写入脏页 + 不刷日志）

### R-6: 范围漂移
- **Risk**: 实现过程中不自觉引入 JOIN/外键等 Out 范围功能
- **Mitigation**:
  - `execution-contract.md` 写明范围护栏
  - 每次 PR/批次前对照 `proposal.md > Out` 清单
  - Code reviewer 检查

### R-7: 依赖渗透
- **Risk**: 第三方类型（如 `numpy.int64`）意外传入
- **Mitigation**:
  - `tinydb.types.coerce()` 严格白名单（只接受 `int/float/str/bool/bytes/Decimal/date/time/datetime/dict/list/None`）
  - 其他类型抛 `TypeError` 而非静默转换

## Architecture Sketch

```
+----------------------------------------------------------+
|  CLI (tinydb.cli.repl + __main__)                        |
+----------------------------------------------------------+
|  Public API: tinydb.open() → Database.execute(sql)      |
+----------------------------------------------------------+
|  Query Executor (planner + ops)                          |
+----------------------------------------------------------+
|  SQL Parser → AST        |  Type System / Catalog        |
+--------------------------+-------------------------------+
|  B-tree Index  |  Heap Storage  |  Buffer Pool           |
+----------------------------------------------------------+
|  Transaction Manager (WAL + recovery)                    |
+----------------------------------------------------------+
|  Pager (4KB pages, single .db file)                      |
+----------------------------------------------------------+
```
