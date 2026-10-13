# api（FastAPI＋faster-whisper）のイメージ。VOICEVOX は公式イメージを別サービスで使う
FROM python:3.12.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    HF_HUB_DISABLE_TELEMETRY=1

# 検証用の画像・PDF に日本語を描くためのフォント（IPAex ゴシック。IPA フォントライセンス v1.0）
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-ipaexfont-gothic=00401-5 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --root-user-action=ignore -r requirements.txt \
 && useradd --create-home --uid 10001 app \
 && mkdir -p /models && chown app:app /models

# ソースはバインドマウントで渡す（compose.yaml の volumes）。Whisper のモデルは名前付きボリューム /models にキャッシュする
USER app
EXPOSE 8000
CMD ["uvicorn", "kondate.main:app", "--host", "0.0.0.0", "--port", "8000"]
