# api（FastAPI）と worker（Celery）で共用するイメージ
FROM python:3.12.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --root-user-action=ignore -r requirements.txt \
 && useradd --create-home --uid 10001 app

# ソースはバインドマウントで渡す（compose.yaml の volumes）。イメージには依存だけを入れる
USER app
EXPOSE 8000
CMD ["uvicorn", "kondate.main:app", "--host", "0.0.0.0", "--port", "8000"]
