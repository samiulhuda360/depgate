# Self-hosted webhook service: docker build -t depgate . && docker run -p 8080:8080 --env-file depgate.env depgate
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY depgate ./depgate
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 depgate && mkdir -p /data && chown depgate /data
USER depgate
ENV DEPGATE_AUDIT_LOG=/data/audit.jsonl DEPGATE_CACHE_DIR=/data/cache
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')" || exit 1
CMD ["depgate", "serve", "--port", "8080"]
