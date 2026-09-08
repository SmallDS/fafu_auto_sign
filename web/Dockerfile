FROM node:22-alpine AS frontend-builder
WORKDIR /build
COPY web/frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY web/frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/app/web/backend \
    FAFU_DATA_DIR=/data
WORKDIR /app
COPY pyproject.toml README.md LICENSE.md ./
COPY src/ ./src/
COPY web/backend/requirements.txt ./web/backend/requirements.txt
RUN pip install --no-cache-dir . -r web/backend/requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 fafu \
    && useradd --uid 10001 --gid fafu --no-create-home --shell /usr/sbin/nologin fafu
COPY web/backend/ ./web/backend/
COPY --from=frontend-builder /build/dist/ ./web/frontend/dist/
COPY web/docker-entrypoint.sh /usr/local/bin/docker-entrypoint
RUN mkdir -p /data/images/library /data/images/latest /data/logs \
    && chown -R fafu:fafu /app /data \
    && sed -i 's/\r$//' /usr/local/bin/docker-entrypoint \
    && chmod 0755 /usr/local/bin/docker-entrypoint
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import json,urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3))" || exit 1
WORKDIR /app/web/backend
ENTRYPOINT ["/usr/local/bin/docker-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
