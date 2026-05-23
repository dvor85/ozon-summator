FROM python:3.13-slim AS base
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tini wget \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /usr/local/share/ca-certificates/Yandex && \
    wget "https://storage.yandexcloud.net/cloud-certs/RootCA.pem" -O /usr/local/share/ca-certificates/Yandex/RootCA.crt && \
    wget "https://storage.yandexcloud.net/cloud-certs/IntermediateCA.pem" -O /usr/local/share/ca-certificates/Yandex/IntermediateCA.crt && \
    update-ca-certificates

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN useradd -m -u 1001 app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

FROM base AS deps
COPY --chown=app:app pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

FROM base AS app
COPY --chown=app:app src ./src
COPY --chown=app:app main.py ./
COPY --from=deps --chown=app:app /app/.venv /app/.venv

USER app

# Если у вас есть порт, объявите:
#EXPOSE 8000

ENTRYPOINT ["tini","--"]
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8000", "--access-log", "main:app"]