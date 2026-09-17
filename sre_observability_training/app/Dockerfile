FROM python:3.14.7-slim-trixie

WORKDIR /app

# 依存を先に入れてレイヤキャッシュを効かせる
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

EXPOSE 8000

# opentelemetry-instrument が自動計装を有効にしてから uvicorn を起動する
CMD ["opentelemetry-instrument", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
