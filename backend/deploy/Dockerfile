# VMTools Next — Dockerfile
# Multi-stage build: Frontend (Node) → Python app + Nginx

# Stage 0: Build frontend
FROM node:22-alpine AS frontend-builder

WORKDIR /frontend
COPY vmtools-frontend/package.json vmtools-frontend/package-lock.json* ./
RUN npm ci --legacy-peer-deps 2>/dev/null || npm install --legacy-peer-deps

COPY vmtools-frontend/ ./
RUN npm run build

# Stage 1: Python application
FROM python:3.11-slim AS app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ src/
COPY config/ config/
COPY alembic.ini ./
COPY alembic/ alembic/

# Copy built frontend from Stage 0
COPY --from=frontend-builder /frontend/dist/ static/

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Create data directory
RUN mkdir -p /app/data /app/logs

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" || exit 1

# Run
CMD ["python", "-m", "vmtools_next.main"]


# Stage 2: Nginx reverse proxy
FROM nginx:alpine AS nginx

COPY deploy/nginx/vmtools-next.conf /etc/nginx/conf.d/default.conf

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]
