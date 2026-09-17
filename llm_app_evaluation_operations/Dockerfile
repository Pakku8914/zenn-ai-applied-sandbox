# 再現性のためタグを固定する（latest は使わない）
FROM python:3.12.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace

# 依存定義を先にコピーして install（レイヤキャッシュを効かせる）
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Web サーバーではないので待機させ、docker compose exec でコマンドを受ける
CMD ["sleep", "infinity"]
