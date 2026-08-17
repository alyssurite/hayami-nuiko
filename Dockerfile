# syntax=docker/dockerfile:1

FROM python:3.13-trixie AS base

# Setup env
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    POETRY_VERSION=2.1.1 \
    POETRY_VIRTUALENVS_CREATE=false

# Set working directory
WORKDIR /app

# Set default shell to bash with pipefail
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Create non-root user
RUN useradd -m bot

# Install poetry
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

# Copy dependency definition files first (layer caching optimization)
COPY pyproject.toml poetry.lock* ./

# Install project dependencies
RUN poetry install --without dev --no-root --no-interaction --no-ansi

# Copy application source code
COPY --chown=bot:bot . .

# Switch to non-root user
USER bot

# Run application
CMD ["python3", "main.py"]
