# syntax=docker/dockerfile:1

# --- Stage 1: Build & Dependency Compilation ---
FROM debian:trixie-slim AS builder

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    POETRY_VERSION=2.4.2 \
    POETRY_VIRTUALENVS_CREATE=false \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /build

# Set default shell to bash with pipefail
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy uv executable
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Provision free-threaded Python and create virtual environment
RUN uv venv /opt/venv --python 3.14t

# Install Poetry into /opt/venv using uv pip
RUN uv pip install "poetry==$POETRY_VERSION"

# Install project dependencies
COPY pyproject.toml poetry.lock* ./
RUN poetry install --without dev --no-root --no-interaction --no-ansi


# --- Stage 2: Production Runtime ---
FROM debian:trixie-slim AS runner

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Set default shell to bash with pipefail
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install minimal runtime certificates
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m bot

# Copy pre-built CPython binaries and compiled virtualenv from builder stage
COPY --from=builder /opt/python /opt/python
COPY --from=builder --chown=bot:bot /opt/venv /opt/venv

# Copy application source code
COPY --chown=bot:bot . .

# Switch to non-root user
USER bot

# Run application
CMD ["python3", "main.py"]
