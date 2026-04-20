FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install system dependencies for PaddleOCR
RUN apt-get update && apt-get install -y \
    libgomp1 libglib2.0-0 libgl1 libsm6 libxext6 libxrender1 \
    libgfortran5 libopenblas0-pthread libatomic1 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first
COPY pyproject.toml ./
COPY uv.lock* ./

# Install Python dependencies
RUN uv sync --no-dev --frozen

RUN uv pip install --python /app/.venv/bin/python setuptools>=68.0.0 --no-deps

RUN /app/.venv/bin/python -c "import setuptools; print('[OK] setuptools', setuptools.__version__)"

# Copy application code
COPY . ./

ENV PATH="/app/.venv/bin:$PATH"
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV PADDLE_INFERENCE_CPU_NUM_THREADS=1
ENV FLAGS_allocator_strategy=naive_best_fit
ENV FLAGS_use_mkldnn=0
ENV KMP_AFFINITY=disabled

RUN chmod +x start.sh

EXPOSE 8003 8004

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

CMD ["./start.sh"]