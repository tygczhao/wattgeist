# Single-container deployment: build the frontend, then let FastAPI serve it alongside the API.
# Run: docker build -t wattgeist . && docker run -p 8000:8000 wattgeist
# The image has no Kiro Crew, so the AI import review and the Séance are off inside it; run the API next to a
# signed-in Kiro Crew (see README, "AI features") to switch them on.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 \
    WATTGEIST_DATA_DIR=/data WATTGEIST_STATIC_DIR=/app/static HOST=0.0.0.0 PORT=8000
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist /app/static
# Run as a non-root user; uploaded meter data is only ever written to /data
RUN useradd --create-home --uid 10001 wattgeist && mkdir -p /data && chown wattgeist /data
USER wattgeist
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uv", "run", "--no-sync", "wattgeist-api"]
