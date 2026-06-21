FROM python:3.11-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY app/ ./app/
COPY examples/ ./examples/

# Run as non-root
RUN adduser --system --no-create-home appuser
USER appuser

# stops Python from writing .pyc bytecode cache files to disk
# forces stdout/stderr to flush immediately instead of buffering
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Cannot use "uv run uvicorn" because appuser has no home dir so uv can't write its cache to $HOME/.cache/uv
# At runtime we don't need uv at all — the packages are already installed in the venv
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
