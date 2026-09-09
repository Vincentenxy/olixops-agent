FROM python:3.14.7-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY scripts/install_pulumi.py ./scripts/install_pulumi.py
RUN python scripts/install_pulumi.py --directory /opt/pulumi-cli

FROM python:3.14.7-slim AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:/opt/pulumi-cli/pulumi:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OLIXOPS_MODE=release \
    OLIXOPS_DOCS_ENABLED=false
RUN groupadd --system app && useradd --system --gid app --no-create-home app \
    && mkdir -p /app/runtime && chown app:app /app/runtime
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /opt/pulumi-cli /opt/pulumi-cli
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/pub/health', timeout=2).close()"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
