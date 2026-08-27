# 再現性のためタグを固定する（latest は使わない）
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/models \
    OMP_NUM_THREADS=2

WORKDIR /workspace

# curl はヘルスチェックと疎通確認に使う（推論サーバ側のイメージには入っている）
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["sleep", "infinity"]
