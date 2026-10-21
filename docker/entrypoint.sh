#!/bin/sh
# 启动前做几项检查，把配置问题在日志里说清楚，而不是直接崩掉。
set -e

DATA_DIR="${OPENQQ_BRIDGE_DATA_DIR:-/data}"
CONFIG_DIR="${OPENQQ_BRIDGE_ROOT:-/config}"
PORT="${OPENQQ_BRIDGE_PORT:-38999}"

mkdir -p "$CONFIG_DIR" "$DATA_DIR"

if [ ! -f "$CONFIG_DIR/bridge_port.txt" ]; then
    printf '%s\n' "$PORT" > "$CONFIG_DIR/bridge_port.txt"
    echo "[init] created $CONFIG_DIR/bridge_port.txt with port $PORT"
fi

if [ ! -f "$CONFIG_DIR/bridge_bindings.json" ]; then
    printf '{}\n' > "$CONFIG_DIR/bridge_bindings.json"
    echo "[init] created $CONFIG_DIR/bridge_bindings.json"
fi

if [ ! -f "$DATA_DIR/data.db" ]; then
    echo "[ERROR] 找不到 $DATA_DIR/data.db" >&2
    echo "        请把海豹的 data/default 目录挂载到 $DATA_DIR（见 README-DOCKER.md）。" >&2
    exit 1
fi
if [ ! -f "$DATA_DIR/data-logs.db" ]; then
    echo "[ERROR] 找不到 $DATA_DIR/data-logs.db" >&2
    echo "        请把海豹的 data/default 目录挂载到 $DATA_DIR（见 README-DOCKER.md）。" >&2
    exit 1
fi

if [ -z "${OPENQQ_BRIDGE_TOKEN:-}" ]; then
    echo "[WARN] 未设置 OPENQQ_BRIDGE_TOKEN。容器已监听 0.0.0.0，任何能访问该端口的人都能发起迁移。"
    echo "[WARN] 建议设置 OPENQQ_BRIDGE_TOKEN，并在海豹插件配置里填同一个令牌。"
fi

echo "[init] data dir   : $DATA_DIR"
echo "[init] config dir : $CONFIG_DIR"

exec python /app/bridge.py \
    --host "0.0.0.0" \
    --port "$PORT" \
    --data-dir "$DATA_DIR"
