FROM python:3.11-slim

# Install tzdata for proper timezone setting
RUN apt-get update && apt-get install -y tzdata && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv
RUN pip install uv

# Copy only dependency files first to leverage Docker layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Set default execution command (paper-trading mode by default)
CMD ["uv", "run", "python", "main.py", "start"]
