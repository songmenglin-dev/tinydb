# Spec: 存储引擎

## ADDED Requirements

### REQ-STO-1: 单文件持久化
The system MUST 将所有数据库状态 (schema、行、索引、WAL) 持久化到一个由调用方指定的 `.db` 文件中。

#### Scenario: 写入新数据库文件
- WHEN 调用 `tinydb.open("/tmp/x.db")` 在不存在的路径上
- THEN 系统创建该文件并返回可用的 `Database` 句柄

#### Scenario: 重新打开数据库
- WHEN 进程退出后再次调用 `tinydb.open("/tmp/x.db")` 同一路径
- THEN 先前写入的表与数据在重新打开后可见

### REQ-STO-2: 页式存储
The system MUST 将数据库文件组织为定长页面 (page)，所有 I/O 以页为单位。

#### Scenario: 默认页大小
- WHEN 打开数据库
- THEN 默认页大小为 4096 字节
- AND 该值在文件头记录

#### Scenario: 跨页记录
- WHEN 插入的记录大于单页剩余空间
- THEN 系统支持跨页溢出 (overflow page) 存储记录

### REQ-STO-3: 缓冲池
The system MUST 维护一个固定容量的页缓冲池 (buffer pool)，缓存最近使用的页以减少磁盘 I/O。

#### Scenario: 命中缓冲池
- WHEN 同一页被连续两次读取
- THEN 第二次读取不触发磁盘 I/O

#### Scenario: 缓冲池满时驱逐
- WHEN 缓冲池已满且需要载入新页
- THEN 系统按最近最少使用 (LRU) 策略驱逐一页

#### Scenario: 默认缓冲池大小
- WHEN 打开数据库未指定 `buffer_pool_size`
- THEN 默认缓冲池大小为 64 页

### REQ-STO-4: 页面原语
The system MUST 提供页的读取、写入、分配、释放原语。

#### Scenario: 分配新页
- WHEN 调用 `pager.allocate_page()`
- THEN 系统从空闲页链表或文件末尾分配新页
- AND 返回新页的 `page_id`

#### Scenario: 释放页
- WHEN 调用 `pager.free_page(pid)`
- THEN 该页加入空闲链表
- AND 文件长度不立即缩减

### REQ-STO-5: 表堆存储
The system MUST 为每张表维护一个堆文件 (heap) 存储记录，记录以槽位 (slot) 形式组织在页内。

#### Scenario: 插入记录
- WHEN 向表 `users` 插入一条记录
- THEN 系统在堆文件中分配槽位并写入记录
- AND 返回新记录的 `rid`

#### Scenario: 按 rid 读取
- WHEN 给定有效 `rid` 调用 `read(rid)`
- THEN 返回该记录原始字节

#### Scenario: 删除记录
- WHEN 给定 `rid` 调用 `delete(rid)`
- THEN 槽位标记为空
- AND 该 rid 后续读取返回 `None`

### REQ-STO-6: 表元数据
The system MUST 持久化表 schema (列名、类型、约束) 至系统目录页。

#### Scenario: 创建表
- WHEN `CREATE TABLE` 成功
- THEN 表的 schema 写入目录页
- AND 进程重启后表依然存在

#### Scenario: 删除表
- WHEN `DROP TABLE` 成功
- THEN 表的 schema 从目录页移除
- AND 表的堆文件标记为可重用空间

### REQ-STO-7: 空闲空间管理
The system MUST 跟踪每页的剩余可用字节数，并优先将新记录写入剩余空间足够的页。

#### Scenario: 写入到有空余的页
- WHEN 插入一条较小记录
- THEN 系统优先选择剩余空间足够的页写入

#### Scenario: 所有页均无足够空间
- WHEN 没有现有页能容纳新记录
- THEN 系统分配新页并写入

### REQ-STO-8: 刷盘
The system MUST 在事务 COMMIT 时强制将脏页与 WAL 刷盘以保证持久性。

#### Scenario: COMMIT 刷盘
- WHEN 事务 COMMIT
- THEN 关联的脏页与 WAL 尾部被 fsync

#### Scenario: 进程崩溃
- WHEN 进程在 COMMIT 前崩溃
- THEN 数据库在重启后能恢复到最近一次成功 COMMIT 后的状态
