# Node.js のバージョンはタグで固定します（latest は使いません）。
# 教材の実行結果と読者の手元の結果を一致させるためです。
FROM node:22.23.2-bookworm-slim

WORKDIR /app

# 依存関係だけを先にコピーしてインストールすることで、
# ソースを編集しただけのときに npm install が再実行されないようにする（レイヤーキャッシュ）
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# MCP サーバーは stdio で起動するため、コンテナは待機させて exec で叩く
CMD ["sleep", "infinity"]
