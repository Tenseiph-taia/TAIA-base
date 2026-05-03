FROM python:3.11-slim

# System deps — pillow needs libjpeg, openpyxl needs nothing extra
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libjpeg-dev \
        libpng-dev \
 && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Layer 1: dependencies (cached unless pyproject.toml changes)
COPY pyproject.toml .
RUN uv pip install --system --no-cache \
      fastmcp \
      openpyxl \
      filelock \
      pillow \
      pydantic \
      pytest

# Layer 2: source (invalidated only when code changes)
COPY taia_sheet_harness/ ./taia_sheet_harness/
RUN uv pip install --system --no-cache --no-deps -e .

# Workbooks are stored in a volume-mounted directory
RUN mkdir -p /workbooks

ENV WORKBOOKS_DIR=/workbooks \
    PORT_MCP=8006 \
    SHEET_HARNESS_HOST=localhost \
    LOCK_TIMEOUT_SECONDS=10 \
    MAX_WORKBOOKS=100

EXPOSE 8006

CMD ["taia-sheet-harness"]