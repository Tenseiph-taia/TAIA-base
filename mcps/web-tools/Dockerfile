FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# 1. Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app

# 2. Copy ONLY dependency files FIRST
# This allows Docker to cache the 'heavy' installation layers
COPY pyproject.toml uv.lock ./

# 3. Heavy lifting: Install Python libs and Chromium
# This layer will now be cached and skipped unless you change pyproject.toml
RUN uv sync --frozen --no-dev
RUN uv run playwright install chromium

ENV PATH="/app/.venv/bin:$PATH"

# 4. Copy your source code LAST
# Now, when you change main.py, ONLY this layer and below will re-run.
# Rebuilds will take 2 seconds instead of 5 minutes.
COPY main.py .

EXPOSE 8000

CMD ["uv", "run", "python", "main.py"]