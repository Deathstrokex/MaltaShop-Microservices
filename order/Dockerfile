# Two-stage build: isolate build tools and use a small unprivileged runtime.
FROM python:3.12-slim AS wheels
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir -r requirements.txt -w /wheels

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=wheels /wheels /wheels
RUN pip install --no-index --find-links=/wheels fastapi==0.128.2 uvicorn==0.48.0  && useradd --system --uid 10001 --create-home app  && mkdir -p /data && chown -R app:app /data
COPY common/ /app/common/
COPY order/ /app/order/
USER 10001
HEALTHCHECK --interval=20s --timeout=3s --start-period=10s --retries=3 \
 CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/healthz',timeout=2)" || exit 1
CMD ["uvicorn", "order.app:app", "--host", "0.0.0.0", "--port", "8000"]
