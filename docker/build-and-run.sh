#!/bin/sh
# 一键：构建镜像并后台启动。第一次用之前请先 cp .env.example .env 并填好。
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "[ERROR] 还没有 .env。请先：cp .env.example .env 然后编辑它。" >&2
    exit 1
fi

docker compose up -d --build
echo
echo "已启动。查看日志：docker compose logs -f openqq-bridge"
echo "健康检查  ：curl http://127.0.0.1:38999/health"
