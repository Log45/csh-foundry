FROM python:3.12.16-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.5@sha256:f459f6f73a8c4ef5d69f4e6fbbdb8af751d6fa40ec34b39a1ab469acd6e289b7 /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev
# Keep the dependency installer and its cache out of the production runtime.
FROM python:3.12.16-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS runtime
WORKDIR /app
COPY --from=build /app /app
# Container mounts are managed by the host; no runtime mount command is required.
RUN apt-get purge -y mount && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 foundry && useradd --uid 10001 --gid 10001 --create-home foundry
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER foundry
EXPOSE 8000
CMD ["uvicorn", "ontology_platform.main:create_app", "--factory", "--host", "0.0.0.0", "--no-proxy-headers", "--no-access-log", "--limit-concurrency", "64", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "30"]
