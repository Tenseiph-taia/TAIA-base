FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libatomic1 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first
COPY pyproject.toml ./
COPY uv.lock* ./

# Install Python dependencies
RUN uv lock && uv sync --no-dev

RUN uv pip install --python /app/.venv/bin/python setuptools>=68.0.0 --no-deps

RUN /app/.venv/bin/python -c "import setuptools; print('[OK] setuptools', setuptools.__version__)"

# Copy application code
COPY . ./

ENV PATH="/app/.venv/bin:$PATH"
ENV OMP_NUM_THREADS=1

RUN chmod +x start.sh

EXPOSE 8003 8004

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

CMD ["./start.sh"]