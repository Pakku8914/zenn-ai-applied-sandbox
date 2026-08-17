# 再現性のためタグを固定する（latest は使わない）
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # モデルの取得先を名前付きボリュームに固定する（2回目以降はオフラインで動く）
    HF_HOME=/models \
    TOKENIZERS_PARALLELISM=false

WORKDIR /workspace

# 依存定義を先にコピーして install（レイヤキャッシュを効かせる）
# torch は CPU 専用 wheel を requirements.txt で固定している（イメージが 4 分の 1 になる）
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Web サーバーではないので待機させ、docker compose exec でコマンドを受ける
CMD ["sleep", "infinity"]
