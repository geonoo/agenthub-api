# AgentHub API — multi-stage: build → test → runtime
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


FROM builder AS test

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    API_KEY=test-api-key-agenthub \
    MASTER_API_KEY=test-master-key \
    DART_API_KEY=dummy-dart-key \
    RATE_LIMIT_ENABLED=false \
    DATABASE_URL=sqlite:////tmp/agenthub-test.db \
    ENVIRONMENT=test

WORKDIR /app
COPY app ./app
COPY static ./static
COPY tests ./tests
COPY pytest.ini .

RUN pytest -q


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DATABASE_URL=sqlite:////app/data/agenthub.db

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser --home-dir /app --shell /sbin/nologin appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data

COPY --from=builder /opt/venv /opt/venv
COPY --from=test --chown=appuser:appuser /app/app ./app
COPY --from=test --chown=appuser:appuser /app/static ./static

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
