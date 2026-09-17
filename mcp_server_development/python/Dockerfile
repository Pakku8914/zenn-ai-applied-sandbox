# Python のバージョンはタグで固定します（latest は使いません）。
# 教材の実行結果と読者の手元の結果を一致させるためです。
FROM python:3.13.14-slim-bookworm

WORKDIR /app

# 依存関係だけを先にコピーしてインストールすることで、
# ソースを編集しただけのときに pip install が再実行されないようにする（レイヤーキャッシュ）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 出力をバッファリングしないことで、ログが即座に見えるようにする
ENV PYTHONUNBUFFERED=1

# MCP サーバーは stdio で起動するため、コンテナは待機させて exec で叩く
CMD ["sleep", "infinity"]
