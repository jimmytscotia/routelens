# RouteLens — built by Coolify on vps-01 (dockerfile buildpack).
# Two targets from one image:
#   web        -> gunicorn dashboard (Coolify target: web)
#   aggregator -> RIS Live websocket aggregator (Coolify target: aggregator)
# The repo has no [build-system], so `uv sync` installs deps only; the package
# itself runs via PYTHONPATH=/app/src (same quirk as local dev).
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    ROUTELENS_DATABASE=/var/lib/routelens/routelens.db

FROM base AS web
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "60", "routelens.app:create_app()"]

FROM base AS aggregator
CMD ["python", "-m", "routelens.aggregator"]
