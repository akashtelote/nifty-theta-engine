FROM python:3.11-slim

# Install tzdata for proper timezone setting
RUN apt-get update && apt-get install -y tzdata && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv directly from astral's official image (much faster than pip)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files first
COPY pyproject.toml uv.lock ./

# Sync dependencies (creates /app/.venv)
RUN uv sync --frozen --no-dev

# Inject the virtual environment into the system path
ENV PATH="/app/.venv/bin:$PATH"

# Copy the rest of the application
COPY . .

# Raw python execution for graceful SIGTERM handling
CMD ["python", "main.py", "start"]