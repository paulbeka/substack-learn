FROM python:3.14-slim AS builder
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.runtime.lock ./
RUN pip install --no-cache-dir -r requirements.runtime.lock
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

FROM python:3.14-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
RUN groupadd --gid 10001 frenchbot && useradd --uid 10001 --gid 10001 --no-create-home frenchbot \
    && mkdir -p /app/data /app/output /app/logs \
    && chown -R frenchbot:frenchbot /app
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
CMD ["uvicorn", "french_bot.dashboard:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--no-proxy-headers"]
