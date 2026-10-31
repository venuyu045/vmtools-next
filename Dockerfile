# VMTools Next — Dockerfile (self-contained)
# Multi-stage: Frontend (Node) → Python app
# Build from VMTools_NEXT/ root: docker compose up -d

# ── Stage 0: Build Vue 3 frontend ──
FROM node:22-alpine AS frontend-builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --legacy-peer-deps 2>/dev/null || npm install --legacy-peer-deps

COPY frontend/ ./
ENV VITE_OUT_DIR=dist
RUN npm run build

# ── Stage 1: Python FastAPI backend ──
FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy backend source
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src/ src/
# ⚠️ 2026-10-20 审查修复（严重·真实密钥被打进镜像层）：
#   原为 `COPY backend/config/ config/` —— 会把 backend/config/config.yaml
#   （含真实 QQ app_id / app_key / redirect_uri；虽被 .gitignore 忽略，但存在于
#   构建上下文）一并写入镜像层，docker history / 层解包可直接读出。
#   改为只拷贝**模板**与无密钥的日志配置；真实配置由运行时通过 VMT_* 环境变量
#   （见 docker-compose.yml）或挂载文件提供。配合新增的 .dockerignore 双重保险。
COPY backend/config/config.yaml.example config/
COPY backend/config/logging.yaml config/
# 运行时若无 config.yaml，以模板为底（密钥等敏感项一律由环境变量覆盖）
RUN cp config/config.yaml.example config/config.yaml

COPY backend/alembic.ini ./
COPY backend/alembic/ alembic/

# Copy built frontend from Stage 0
COPY --from=frontend-builder /build/dist/ static/

# Install Python dependencies
# 时装包 Ed25519 签名需要 `cryptography`（可选 extra `signing`）。审计 v1.2 P1-2：
# 这里之前只装 `.[dev]`，生产镜像里 `_ed25519_signer` 会 ImportError → `/packs`
# 永远不带 signature（客户端严格模式不可用）。显式带上 `signing`。
RUN pip install --no-cache-dir -e ".[dev,signing]"

RUN mkdir -p /app/data /app/logs

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" || exit 1

CMD ["python", "-m", "vmtools_next.main"]
