# Spec: B-tree 索引

## ADDED Requirements

### REQ-IDX-1: B-tree 结构
The system MUST 实现 B-tree (order ≥ 3) 作为索引结构，每个节点对应一个或多个磁盘页。

#### Scenario: 内部节点与叶子节点
- WHEN B-tree 有非根层
- THEN 内部节点包含 (key, child_page_id) 对
- AND 叶子节点包含 (key, rid) 对并按 key 升序排列

#### Scenario: 节点分裂
- WHEN 插入导致节点键数超过阶数上限
- THEN 节点分裂为两个节点
- AND 父节点插入中间键

#### Scenario: 节点合并
- WHEN 删除导致节点键数低于下限
- THEN 系统尝试与兄弟节点合并或重平衡

### REQ-IDX-2: 等值查找
The system MUST 通过 B-tree 在 O(log n) 时间复杂度内完成等值查找。

#### Scenario: 单条命中
- WHEN `WHERE id = 42` 且 `id` 列存在索引
- THEN 索引返回该键对应的 rid 集合

#### Scenario: 键不存在
- WHEN 索引键不存在
- THEN 返回空 rid 集合

### REQ-IDX-3: 范围扫描
The system MUST 通过 B-tree 支持有序范围扫描。

#### Scenario: 闭区间
- WHEN `WHERE score BETWEEN 80 AND 100`
- THEN 索引从 80 顺序扫描到 100

#### Scenario: 开区间
- WHEN `WHERE score > 80`
- THEN 索引从 80 后第一个键开始扫描

### REQ-IDX-4: 索引维护
The system MUST 在 INSERT / UPDATE / DELETE 数据行时同步维护所有相关索引。

#### Scenario: INSERT 维护索引
- WHEN 向表插入新行
- THEN 该行每个索引列的键被插入对应 B-tree

#### Scenario: UPDATE 维护索引
- WHEN 更新某行的索引列
- THEN 旧键从 B-tree 中删除，新键插入

#### Scenario: DELETE 维护索引
- WHEN 删除某行
- THEN 该行所有索引列的键从对应 B-tree 中删除

### REQ-IDX-5: UNIQUE 约束
The system MUST 将 UNIQUE 约束实现为唯一性索引。

#### Scenario: UNIQUE 拒绝重复
- WHEN 向含 UNIQUE 列的表插入重复键
- THEN 系统抛出 `ConstraintViolation`

#### Scenario: UNIQUE 允许 NULL
- WHEN UNIQUE 列允许多个 NULL
- THEN NULL 不参与唯一性检查

### REQ-IDX-6: 索引持久化
The system MUST 将 B-tree 节点持久化到磁盘，使索引在进程重启后可用。

#### Scenario: 索引节点落盘
- WHEN 缓冲池中的索引节点被驱逐或事务 COMMIT
- THEN 节点内容已写入磁盘

#### Scenario: 重启后可用
- WHEN 进程重启后打开同一数据库
- THEN 索引无需重建即可使用

### REQ-IDX-7: 复合键索引
The system MUST 支持多列复合键的 B-tree 索引。

#### Scenario: 复合键查找
- WHEN 索引为 `(a, b)`，`WHERE a = 1 AND b = 2`
- THEN 通过复合键 `(1, 2)` 命中

#### Scenario: 复合键前缀
- WHEN 索引为 `(a, b)`，`WHERE a = 1` 未指定 b
- THEN 通过复合键前缀 `a=1` 范围扫描
