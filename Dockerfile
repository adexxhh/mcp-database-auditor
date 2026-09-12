FROM python:3.10-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY security/ ./security/
COPY core/ ./core/
COPY scripts/ ./scripts/
COPY server.py ./

RUN pip install --no-cache-dir . "asyncpg>=0.29.0"

FROM python:3.10-slim AS runner

WORKDIR /app

# Security Hardening: Create non-root user
RUN useradd -m -u 10001 appuser

COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "server.py", "--transport", "sse", "--host", "0.0.0.0", "--port", "8000"]
