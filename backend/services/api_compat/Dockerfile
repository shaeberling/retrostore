FROM ghcr.io/astral-sh/uv:0.12.1 AS uv
FROM python:3.14.6-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY retrostore ./retrostore
COPY services ./services

CMD ["sh", "-c", "exec gunicorn --bind :${PORT:-8080} --workers 2 --threads 8 --timeout 60 'services.api_compat.app:create_app()'"]
