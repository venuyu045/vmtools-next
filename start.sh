#!/usr/bin/env bash
# VMTools Next — 一键启动脚本
# 用法: chmod +x start.sh && ./start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================="
echo " VMTools Next — 快速部署"
echo "=============================="

# ── 0. 前置检查 ──
if ! command -v docker &>/dev/null; then
    echo "[错误] 请先安装 Docker: https://docs.docker.com/engine/install/"
    exit 1
fi

if ! command -v docker &>/dev/null && ! docker compose version &>/dev/null 2>&1; then
    echo "[错误] 请安装 Docker Compose 插件"
    exit 1
fi

# ── 1. 环境变量 ──
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "[提示] 已从 .env.example 创建 .env，请编辑并设置 VMT_SECRET_KEY"
        echo "        按 Enter 使用默认值继续，或 Ctrl+C 先编辑..."
        read -r
    else
        echo "[错误] 未找到 .env 或 .env.example"
        exit 1
    fi
fi

set -a; source .env; set +a

if [ "${VMT_SECRET_KEY:-change-me}" = "change-me-to-a-random-string-at-least-32-chars" ]; then
    echo "[警告] VMT_SECRET_KEY 未修改，将自动生成随机密钥"
    export VMT_SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/^VMT_SECRET_KEY=.*/VMT_SECRET_KEY=$VMT_SECRET_KEY/" .env
fi

# ── 2. 构建并启动 ──
echo ""
echo "[1/2] 构建 Docker 镜像（首次较慢）..."
docker compose build

echo ""
echo "[2/2] 启动服务..."
docker compose up -d

echo ""
echo "=============================="
echo " 部署完成！"
echo " 访问地址: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):${VMT_PORT:-8080}"
echo ""
echo " 常用命令:"
echo "   docker compose logs -f    查看日志"
echo "   docker compose down       停止服务"
echo "   docker compose restart    重启服务"
echo "=============================="
