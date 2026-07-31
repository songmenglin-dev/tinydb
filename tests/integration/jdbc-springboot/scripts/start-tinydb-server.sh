#!/usr/bin/env bash
# Start a local tinydb-server for the JDBC connectivity test.
#
# Usage:
#   ./scripts/start-tinydb-server.sh start [PORT] [DB_PATH]
#   ./scripts/start-tinydb-server.sh stop
#   ./scripts/start-tinydb-server.sh status
#
# Defaults: PORT=18520, DB_PATH=tests/integration/jdbc-springboot/.tinydb-sb.db

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/../../../.." && pwd)"
PID_FILE="$HERE/.tinydb-server.pid"
LOG_FILE="$HERE/.tinydb-server.log"

DEFAULT_PORT=18520
DEFAULT_DB_PATH="$PROJECT_ROOT/tests/integration/jdbc-springboot/.tinydb-sb.db"

cmd="${1:-start}"
port="${2:-$DEFAULT_PORT}"
db_path="${3:-$DEFAULT_DB_PATH}"

start() {
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "tinydb-server already running (pid $(cat "$PID_FILE"))"
        return 0
    fi

    cd "$PROJECT_ROOT"
    : > "$LOG_FILE"
    nohup python -m tinydb.server \
        --db-path "$db_path" \
        --host 127.0.0.1 \
        --port "$port" \
        > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    # Wait for TCP readiness (up to 5s)
    for _ in $(seq 1 50); do
        if (echo > /dev/tcp/127.0.0.1/"$port") 2>/dev/null; then
            echo "tinydb-server listening on 127.0.0.1:$port (pid $(cat "$PID_FILE"))"
            echo "log: $LOG_FILE"
            return 0
        fi
        sleep 0.1
    done
    echo "ERROR: tinydb-server did not become ready on port $port" >&2
    tail "$LOG_FILE" >&2 || true
    return 1
}

stop() {
    if [[ ! -f "$PID_FILE" ]]; then
        echo "tinydb-server not running (no pid file)"
        return 0
    fi
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        sleep 0.5
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
        echo "tinydb-server stopped (pid $pid)"
    fi
    rm -f "$PID_FILE"
}

status() {
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "tinydb-server running (pid $(cat "$PID_FILE"))"
    else
        echo "tinydb-server not running"
        return 1
    fi
}

case "$cmd" in
    start) start ;;
    stop)  stop  ;;
    status) status ;;
    *)
        echo "Usage: $0 {start [PORT] [DB_PATH] | stop | status}" >&2
        exit 2
        ;;
esac