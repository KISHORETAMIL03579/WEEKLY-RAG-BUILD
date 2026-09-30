# Stage 1: Build React 18 + TypeScript + Vite frontend
FROM node:22-alpine AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Production Python / FastAPI runtime
FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000

# Create non-root system user for production security
RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code and the data it reads at runtime:
#   config/      MCP server list (adding a tool server is a config change)
#   benchmarks/  benchmark cases and expected tool paths
#   week6/       Week 6 evaluation assets
COPY app.py ./
COPY backend/ backend/
COPY prompts/ prompts/
COPY config/ config/
COPY benchmarks/ benchmarks/
COPY week6/ week6/
COPY scripts/ scripts/

# Copy compiled React frontend assets from builder stage
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# Pre-create data directories and assign ownership to appuser. benchmarks/ must be
# writable: each benchmark run writes benchmarks/policy_execution/runs/<run_id>.csv.
RUN mkdir -p uploads vectorstore traces state benchmarks/policy_execution/runs \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/healthz')" || exit 1

# FastAPI is ASGI: Gunicorn runs with uvicorn_worker.UvicornWorker ASGI worker
CMD ["gunicorn", "backend.main:app", \
     "-k", "uvicorn_worker.UvicornWorker", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--timeout", "120"]
