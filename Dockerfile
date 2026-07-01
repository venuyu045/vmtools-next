# VMTools Next — Dockerfile (self-contained)
# Multi-stage: Frontend (Node) → Python app
# Build from VMTools_NEXT/ root: docker compose up -d

# ── Stage 0: Build Vue 3 frontend ──
FROM node:22-alpine AS frontend-builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --legacy-peer-deps 2>/dev/null || npm install --legacy-peer-deps

COPY frontend/ ./
RUN npm run build

# ── Stage 1: Python FastAPI backend ──
FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy backend source
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src/ src/
COPY backend/config/ config/
COPY backend/alembic.ini ./
COPY backend/alembic/ alembic/

# Copy built frontend from Stage 0
COPY --from=frontend-builder /build/dist/ static/

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]"

RUN mkdir -p /app/data /app/logs

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" || exit 1

CMD ["python", "-m", "vmtools_next.main"]
