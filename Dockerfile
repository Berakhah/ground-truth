# Ground Truth app image. Phase 1 has no external services: DuckDB is an
# embedded local .duckdb file (no server) and the provider gateway is
# shimmed (ground_truth/_bok_shim.py, no real network calls in Phase 1) --
# so this is the only image this project needs.
#
# `docker compose up`'s default command runs the test suite as the
# fresh-machine smoke test (00-SHARED-FOUNDATION.md R5), which needs
# pytest/pytest-cov -- both live in [dependency-groups] dev, so the venv
# built below keeps the dev group installed, not a slim --no-dev runtime
# venv that couldn't run its own smoke test.
#
# Multi-stage (00 security baseline, Task 52 item 1): the `builder` stage
# holds `uv` itself and the full `uv sync` build cache; the final stage
# copies only the resulting venv and the source tree, so `uv` and its
# resolver/download cache never ship in the image that runs untrusted-ish
# test input.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Lockfile first for layer caching: this layer is cached until
# pyproject.toml/uv.lock change, independent of source edits below.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY . .

FROM python:3.12-slim AS runtime

RUN groupadd --gid 1000 groundtruth \
    && useradd --uid 1000 --gid groundtruth --create-home --shell /usr/sbin/nologin groundtruth

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder --chown=groundtruth:groundtruth /app /app

# Read-only rootfs (docker-compose.yml sets `read_only: true`): the app
# never writes outside /app/data and /tmp, both mounted as writable
# tmpfs/volumes by the compose file, so no further writable paths are
# declared here.
USER groundtruth

# Invoke pytest directly from the venv, not via `uv run`: the runtime stage never copies the
# `uv`/`uvx` binaries in (deliberately -- they're a build tool, not a runtime dependency, see
# the multi-stage comment above), so `uv run ...` would fail with "executable file not found
# in $PATH" on a fresh `docker compose up`. PATH already puts /app/.venv/bin first (line 41),
# and `uv sync --frozen` in the builder stage installed every [dependency-groups] dev tool
# (including pytest itself) straight into that venv, so the venv's own `pytest` is already the
# complete, correct one to run -- no `uv` needed at runtime at all.
CMD ["pytest", "--cov=ground_truth", "--cov-report=term-missing", "--cov-fail-under=75"]
