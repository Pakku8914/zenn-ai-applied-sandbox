# 再現性のためタグを固定する（latest は使わない）
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # モデルの取得先を名前付きボリュームに固定する（2回目以降はオフラインで動く）
    HF_HOME=/models \
    TOKENIZERS_PARALLELISM=false \
    # CPU の並列度。学習の実測値を安定させるため明示する
    OMP_NUM_THREADS=2

WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["sleep", "infinity"]
