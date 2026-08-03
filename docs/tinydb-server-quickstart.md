# tinydb-server 部署指南

> 本文档面向运维与集成开发者，介绍 tinydb 服务端的安装、启动、停止与数据
> 维护流程。内容与操作系统无关，所有命令假定在源码 clone 的根目录中执行，
> 文本 `$VAR` 形式的环境变量可在 shell 中提前导出。

---

## 1. 安装

```bash
git clone <repo-url> tinydb
cd tinydb

# 核心运行时 + REPL（依赖 prompt_toolkit）
pip install -e ".[cli]"

# 同时安装测试依赖
pip install -e ".[cli,test]"

# 验证安装
python -c "import tinydb; print(tinydb.__version__)"
```

可发行到 PyPI 二进制包后（roadmap 项），可改用 `pip install tinydb`。

---

## 2. 启动服务端

### 2.1 命令格式

```
python3 -m tinydb.server --db-path <path> [--host HOST] [--port PORT]
                                                  [--max-conns N]
                                                  [--heartbeat-interval S]
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `--db-path` | path | 必填 | 数据库文件路径，文件不存在时自动创建 |
| `--host` | str | `127.0.0.1` | 监听地址 |
| `--port` | int | `8520` | TCP 端口（1–65535） |
| `--max-conns` | int | `64` | 最大并发连接数 |
| `--heartbeat-interval` | float | `30.0` | 心跳间隔（秒）|

### 2.2 本机启动（开发默认）

```bash
mkdir -p /var/lib/tinydb
python3 -m tinydb.server --db-path /var/lib/tinydb/data
```

服务监听 `127.0.0.1:8520`，仅本机访问可用。

### 2.3 监听全局（生产 / 跨主机）

将 `--host` 设为 `0.0.0.0` 即可接受来自任意地址的 TCP 连接：

```bash
python3 -m tinydb.server \
    --db-path /var/lib/tinydb/data \
    --host 0.0.0.0 \
    --port 8520
```

服务监听 `0.0.0.0:8520`，同一网络内的其它主机可通过本机 IP 访问。
生产环境建议配合防火墙规则限制可信 IP 段。

---

## 3. 停止 / 重启

### 3.1 查找进程

```bash
pgrep -f "tinydb.server"
# 或
ss -tlunp 'sport = :8520'
```

### 3.2 优雅停止

```bash
kill <pid>                       # 默认 SIGTERM，server 走 graceful shutdown
```

### 3.3 重启

```bash
kill <pid> && \
python3 -m tinydb.server --db-path /var/lib/tinydb/data --host 0.0.0.0 --port 8520
```

避免使用 `kill -9`：未刷盘的 commit 可能丢失。

---

## 4. 数据目录与备份

### 4.1 文件结构

启动一次后，`--db-path` 指向的位置会产生两个文件：

```
<db-path>           # 主数据文件
<db-path>.wal       # 写前日志（crash recovery 依赖）
```

### 4.2 在线备份

由于 WAL 持续追加，**在服务运行时直接拷贝** 不保证一致性。建议：

```bash
# 1) 停服
kill <pid>

# 2) 拷贝
cp /var/lib/tinydb/data /var/lib/tinydb/data.wal /backup/$(date +%Y%m%d)/

# 3) 恢复
cp /backup/20260803/data /backup/20260803/data.wal /var/lib/tinydb/
```

未来版本将提供 `BACKUP` 在线一致性快照命令。

---

## 5. 进程管理脚本

将以下内容保存为 `scripts/run_server.sh` 并 `chmod +x`：

```bash
#!/usr/bin/env bash
# tinydb-server 的进程管理封装。
set -euo pipefail

DB_PATH=${TINYDB_DB_PATH:-/var/lib/tinydb/data}
HOST=${TINYDB_HOST:-0.0.0.0}
PORT=${TINYDB_PORT:-8520}
PIDFILE=${TINYDB_PIDFILE:-/var/run/tinydb.server.pid}
LOGFILE=${TINYDB_LOGFILE:-/var/log/tinydb/server.log}

case "${1:-start}" in
  start)
    if [[ -f "$PIDFILE" ]] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; then
      echo "already running (pid=$(cat $PIDFILE))"; exit 0
    fi
    mkdir -p "$(dirname $DB_PATH)" "$(dirname $LOGFILE)"
    nohup python3 -m tinydb.server \
        --db-path "$DB_PATH" --host "$HOST" --port "$PORT" \
        >>"$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "started pid=$!  db=$DB_PATH  $HOST:$PORT"
    ;;
  stop)   kill "$(cat $PIDFILE)" 2>/dev/null || true; rm -f "$PIDFILE"; echo "stopped" ;;
  status) ss -tlunp "sport = :$PORT" || true ;;
  *)      echo "usage: $0 {start|stop|status}"; exit 2 ;;
esac
```

使用方式：

```bash
./scripts/run_server.sh start
./scripts/run_server.sh status
./scripts/run_server.sh stop
```

---

## 6. 常见故障

| 症状 | 原因 | 处置 |
|---|---|---|
| 客户端 `Connection refused` | 监听绑定 127.0.0.1，跨主机不可达 | 改用 `--host 0.0.0.0` 启动 |
| INSERT 报"列数不匹配" | 服务端表是旧 schema，与客户端 DDL 不一致 | drop 后重建，或引入 schema migration |
| `port already in use` | 旧进程未干净退出 | `pkill -f tinydb.server` 后重启 |
| 客户端无响应 / 频繁超时 | 心跳断开 / `max_conns` 触顶 | 调整 `--heartbeat-interval` 与 `--max-conns` |
| 进程退出后 commit 丢失 | 上一次使用了 `kill -9` | 改用 `SIGTERM` 让 graceful shutdown 跑完 |

---

## 7. 集成示例（Java / JDBC）

```java
// application.yml
spring:
  datasource:
    url: ${TINYDB_JDBC_URL:jdbc:tinydb://<server-host>:8520/}
    driver-class-name: org.tinydb.jdbc.TinyDriver
    username: ""
    password: ""
```

```python
# Python 客户端
import tinydb
db = tinydb.connect("<server-host>", 8520)
result = db.execute("SELECT * FROM users")
```

---

**版本**：v0.3.x · **维护**：tinydb 团队
