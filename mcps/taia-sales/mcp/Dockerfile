FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
RUN mkdir -p /app/data

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

COPY main.py .

EXPOSE 8000
CMD ["uv", "run", "python", "main.py"]