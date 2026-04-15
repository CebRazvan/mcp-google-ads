FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install upstream deps first (cached across code-only changes)
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Pin modern MCP SDK (streamable-http) + ASGI stack separately so upstream
# requirements.txt bumps don't invalidate this layer
RUN pip install "mcp>=1.27,<2" uvicorn starlette

# Application code (respects .dockerignore)
COPY . .

EXPOSE 8080

CMD ["python", "/app/entrypoint.py"]
