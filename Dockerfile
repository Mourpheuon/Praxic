# Praxic -- Docker Image
# Build:  docker build -t praxic .
# Run:    docker run -p 8000:8000 -v $(pwd)/data:/app/data -v $(pwd)/config.toml:/app/config.toml praxic

FROM python:3.12-slim

LABEL org.opencontainers.image.title="Praxic"
LABEL org.opencontainers.image.description="AI agent with Maoist dialectical-materialist cognitive core"
LABEL org.opencontainers.image.version="0.0.3"

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --break-system-packages \
    "anthropic>=0.28.0" \
    "openai>=1.35.0" \
    "pydantic>=2.7.0" \
    "structlog>=24.2.0" \
    "httpx>=0.27.0" \
    "typer>=0.12.0" \
    "rich>=13.7.0" \
    "tiktoken>=0.7.0" \
    "python-dotenv>=1.0.0" \
    "fastapi>=0.111.0" \
    "uvicorn[standard]>=0.30.0" \
    "aiosqlite>=0.20.0"

# Copy application code
COPY siwu/ ./siwu/
# prompts/ 目录由应用启动时自动创建（siwu/config.py _resolve_prompts_dir），无需 COPY

# Create non-root user
RUN useradd --create-home --shell /bin/bash praxic && chown -R praxic:praxic /app
USER praxic

# Create volume mount points
RUN mkdir -p /app/data /app/workspace /app/logs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/setup/status || exit 1

CMD ["python", "-m", "uvicorn", "siwu.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
