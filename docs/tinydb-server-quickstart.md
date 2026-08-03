# tinydb-server 部署与启动指南

> 本文档记录 tinydb（v0.3）嵌入式关系数据库的 **服务端** 安装 / 启动 / 验证 / 停止
> 流程，所有命令均假定在源码 checkout 的根目录执行。

---

## 1. 安装（一次性）

```bash
git clone <repo-url> tinydb
cd tinydb

# core + REPL（引入 prompt_toolkit）
pip install -e ".[cli]"

# 跑测试用
pip install -e ".[cli,test]"

# 确认
python -c "import tinydb; print(tinydb.__version__)"    # 应打印当前版本
```

---

## 2. 启动服务端

### 2.1 最简单 — 本机回环（单机调试）

```bash
mkdir -p /tmp/test
python3 -m tinydb.server --db-path /tmp/test/db --port 8765
```

启动后看到：

```
[server] 2026-07-31 14:10:11,601 INFO listening on 127.0.0.1:8765
```

### 2.2 跨机器 / WSL2 ← → Windows（推荐生产路径）

`127.0.0.1` 只在同一网络命名空间内可达。WSL2 是个独立的 Hyper-V VM，
从 Windows 端的 Spring Boot / JDBC client 必须通过 WSL2 的真实 IP 访问：

```bash
# 先查 WSL2 的 IP
hostname -I                                # 例：172.29.163.109

# 启动时绑 0.0.0.0，否则只听 loopback
python3 -m tinydb.server \
    --db-path /tmp/test/db \
    --host 0.0.0.0 \
    --port 8765
```

期望输出：

```
[server] ... INFO listening on 0.0.0.0:8765
```

可选参数（部分）：

| 参数 | 默认 | 含义 |
|---|---|---|
| `--host` | `127.0.0.1` | 监听地址；跨主机访问必填 `0.0.0.0` |
| `--port` | `8520` | TCP 端口 |
| `--db-path` | （必填）| 数据文件路径；首次启动自动创建 |
| `--max-conns` | `64` | 并发连接上限 |
| `--heartbeat-interval` | `30.0` | 心跳秒数 |

---

## 3. 验证服务连通

### 3.1 server 侧 — 看监听端口

```bash
ss -tlunp | grep 8765
# 期望：LISTEN 0.0.0.0:8765   ← 表明 socket 真的对所有网卡可达
```

### 3.2 client 侧 — Python smoke test

另开一个 shell：

```bash
PYTHONPATH=src python3 - <<'PY'
import tinydb
db = tinydb.connect("127.0.0.1", 8765)
print(db.execute("SELECT 1"))   # Result(rows=[[1]], rowcount=1)
print(db.ping())                # 毫秒级回显
PY
```

### 3.3 远端（Windows） — TCP 连通性

```powershell
Test-NetConnection 172.29.163.109 -Port 8765
# TcpTestSucceeded: True  ← 通了；False 通常是 WSL2 IP 变了或防火墙拦了
```

### 3.4 远端（Windows 上的应用）

JDBC URL 直指 WSL2 IP，**不要再写 `localhost`**：

```
jdbc:tinydb://172.29.163.109:8765/
```

---

## 4. 停止 / 重启

```bash
# 找 pid（任一方式）
pgrep -f "tinydb.server"         # 命令行匹配
ss -tlunp 'sport = :8765'        # 看监听 socket 所属进程

# 优雅停止
kill <pid>                       # 默认 SIGTERM，server 走 graceful shutdown

# 强杀（不推荐，会跳过未刷盘的 commit）
kill -9 <pid>
```

重启流程：

```bash
pkill -f "tinydb.server"                          # 先停
python3 -m tinydb.server --db-path /tmp/test/db \
    --host 0.0.0.0 --port 8765                    # 再起
```

> **Tip**：每次 WSL2 重启后 IP 都会变；Spring Boot 那边要么读环境变量、要么写
> host 路由表，否则要同步更新 JDBC URL 中的 host。

---

## 5. 数据文件位置 & 备份

- `--db-path` 指向的是 **单一 db 文件**（默认 `<path>`）
- 紧邻处会有一个 **WAL 文件** `<path>.wal`，崩溃恢复依赖它
- 备份 = 把这两个文件一并拷贝（停服时拷贝最稳）：

```bash
# 停服
pkill -f "tinydb.server"

# 拷贝
mkdir -p /tmp/test.bak
cp /tmp/test/db /tmp/test/db.wal /tmp/test.bak/

# 恢复（覆盖即可）
cp /tmp/test.bak/db /tmp/test.bak/db.wal /tmp/test/
```

---

## 6. 一键脚本（可选）

把下面保存为 `scripts/run_server.sh`，`chmod +x` 后就能 `./scripts/run_server.sh start`：

```bash
#!/usr/bin/env bash
# 启停 tinydb server；适用于 WSL2 与 Linux。
set -euo pipefail

DB_PATH=${TINYDB_DB_PATH:-/tmp/test/db}
HOST=${TINYDB_HOST:-0.0.0.0}
PORT=${TINYDB_PORT:-8765}
PIDFILE=${TINYDB_PIDFILE:-/tmp/tinydb.server.pid}

case "${1:-start}" in
  start)
    if [[ -f "$PIDFILE" ]] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; then
      echo "already running (pid=$(cat $PIDFILE))"; exit 0
    fi
    mkdir -p "$(dirname $DB_PATH)"
    nohup python3 -m tinydb.server \
        --db-path "$DB_PATH" --host "$HOST" --port "$PORT" \
        >/tmp/tinydb.server.log 2>&1 &
    echo $! > "$PIDFILE"
    echo "started pid=$!  db=$DB_PATH  $HOST:$PORT"
    ;;
  stop)   kill "$(cat $PIDFILE)" 2>/dev/null || true; rm -f "$PIDFILE"; echo "stopped" ;;
  status) ss -tlunp "sport = :$PORT" || true ;;
  *)      echo "usage: $0 {start|stop|status}"; exit 2 ;;
esac
```

---

## 7. 常见故障

| 症状 | 原因 | 修法 |
|---|---|---|
| 客户端 `Connection refused` | server 绑了 127.0.0.1，跨主机访问不到 | 加 `--host 0.0.0.0` 启动 |
| `Test-NetConnection` False | WSL2 重启后 IP 变了 | `hostname -I` 取新 IP，更新 JDBC URL |
| `port already in use` | 旧进程没干净退出 | `pkill -f "tinydb.server"` 再起 |
| 重启 server 后 INSERT 报"列数不匹配" | 服务端表是旧 schema，mapper 已更新 | 进 server 同进程跑 `DROP TABLE …`；或加一个 `drop+create` 端点 |
| Spring Boot 启动后立即退出 | 没有 web 启动器，main 线程无活儿可干 | 加 `org.springframework.boot:spring-boot-starter-web` 依赖 |

---

## 8. 与本地集成测试（Spring Boot）联调清单

```bash
# WSL
./scripts/run_server.sh start            # 或 python3 -m tinydb.server --host 0.0.0.0 ...
./scripts/run_server.sh status           # 看 0.0.0.0:8765

# Windows
curl http://localhost:9950/api/users/status
#   {"status":"UP","table_count":1,"tables":[{"name":"users","row_count":5}]}
```

整套链路 = 浏览器 / curl → Spring Boot (9950) → tinydb-JDBC → WSL2 上的 tinydb-server (8765) → 文件 `/tmp/test/db`。

---

**版本**：v0.3.0 · **最后更新**：2026-07-31
