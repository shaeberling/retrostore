FROM ghcr.io/astral-sh/uv:0.12.1 AS uv
FROM node:26.6.0-bookworm-slim AS admin-assets

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY services/admin/assets ./services/admin/assets
COPY services/admin/templates ./services/admin/templates
COPY services/admin/static ./services/admin/static
RUN npm run build:admin-css

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
COPY --from=admin-assets /build/services/admin/static/admin.css ./services/admin/static/admin.css

CMD ["sh", "-c", "exec gunicorn --bind :${PORT:-8080} --workers 2 --threads 8 --timeout 60 'services.admin.app:create_cloud_app()'"]
