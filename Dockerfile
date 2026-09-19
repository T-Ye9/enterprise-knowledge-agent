FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface
WORKDIR /app

# CPU ONNX embedding 使用 OpenMP 运行库。
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY app ./app
COPY samples/demo-company-policy.pdf samples/web-demo-policy.pdf ./samples/
RUN useradd --uid 10001 --create-home agent \
    && mkdir -p /app/data/vector-db /app/.cache \
    && chown -R agent:agent /app/data /app/.cache
USER agent
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=3)" || exit 1
CMD ["python", "-m", "app.server"]
