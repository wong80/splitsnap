# syntax=docker/dockerfile:1.7

# ---- build: resolve dependencies with uv into /app/.venv ----
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev
RUN DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_SECRET_KEY=collectstatic-only \
    /app/.venv/bin/python manage.py collectstatic --noinput

# ---- runtime: slim image, non-root ----
FROM python:3.12-slim AS runtime
ARG GIT_SHA=unknown
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    MEDIA_ROOT=/data/media \
    SERVICE_VERSION=$GIT_SHA
RUN useradd --system --uid 10001 --home /app app \
    && mkdir -p /data/media /app && chown -R app /data /app
WORKDIR /app
COPY --from=build --chown=app /app /app
USER app
EXPOSE 8000
VOLUME ["/data/media"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--config", "docker/gunicorn.conf.py"]
