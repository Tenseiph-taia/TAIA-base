# ── Stage 1: dependency layer ──────────────────────────────────────────────
FROM python:3.11-slim AS deps

# Create non-root user for security
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# System packages required by Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first (layer cache optimisation)
COPY pyproject.toml .

# Install Python dependencies into /app/.venv
RUN uv venv .venv && \
    uv pip install --python .venv/bin/python -e "." 2>/dev/null || \
    uv pip install --python .venv/bin/python \
        "mcp[cli]>=1.0.0" \
        "playwright>=1.44.0" \
        "Pillow>=10.0.0" \
        "playwright-stealth>=1.0.0"

# Install Playwright system dependencies + Chromium browser
# Set browsers path to a shared location accessible by all users
ENV PLAYWRIGHT_BROWSERS_PATH=/playwright-browsers
RUN .venv/bin/python -m playwright install --with-deps chromium

# Fix ownership for non-root user
RUN chown -R appuser:appgroup /app
# Ensure browser cache directory is accessible
RUN mkdir -p /home/appuser/.cache && chown -R appuser:appgroup /home/appuser/.cache

# ── Stage 2: runtime image ─────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Create non-root user (must match user in deps stage)
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# Playwright system deps must also exist in the runtime stage
RUN apt-get update && apt-get install -y --no-install-recommends \
        # Chromium shared libraries
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libpango-1.0-0 \
        libcairo2 \
        libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy venv + installed Playwright browsers from deps stage
COPY --from=deps /app/.venv /app/.venv
COPY --from=deps /playwright-browsers /playwright-browsers

# Fix ownership for non-root user
RUN chown -R appuser:appgroup /app
RUN mkdir -p /playwright-browsers && chown -R appuser:appgroup /playwright-browsers

# Copy application source (changes most often — last layer)
COPY browser/ ./browser/
COPY server.py .

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8005

# Switch to non-root user
USER appuser

CMD ["python", "server.py"]
