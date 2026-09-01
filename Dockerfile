# Ground Truth app image. Phase 1 has no external services: DuckDB is an
# embedded local .duckdb file (no server) and the provider gateway is
# shimmed (ground_truth/_bok_shim.py, no real network calls in Phase 1) --
# so this is the only image this project needs.
#
# `docker compose up`'s default command runs the test suite as the
# fresh-machine smoke test (00-SHARED-FOUNDATION.md R5), which needs
# pytest/pytest-cov -- both live in [dependency-groups] dev, so this stays
# one stage with the dev group installed, not a slim --no-dev runtime image
# that couldn't run its own smoke test.
FROM python:3.12-slim

RUN groupadd --gid 1000 groundtruth \
    && useradd --uid 1000 --gid groundtruth --create-home --shell /usr/sbin/nologin groundtruth

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Lockfile first for layer caching: this layer is cached until
# pyproject.toml/uv.lock change, independent of source edits below.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY . .

RUN chown -R groundtruth:groundtruth /app
USER groundtruth

CMD ["uv", "run", "pytest", "--cov=ground_truth", "--cov-report=term-missing", "--cov-fail-under=75"]
