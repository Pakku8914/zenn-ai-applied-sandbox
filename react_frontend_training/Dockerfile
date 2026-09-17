# Node.js 22（LTS）をバージョン固定する（latest は使わない）
FROM node:22.12.0-bookworm-slim

WORKDIR /app

# 依存定義だけ先にコピーして install する（Docker のレイヤーキャッシュを効かせるため）
COPY package.json package-lock.json* ./
RUN npm install

# アプリ本体をコピーする（実行時はバインドマウントで上書きされる前提の保険）
COPY . .

# Vite 開発サーバの待ち受けポート
EXPOSE 5173

# 0.0.0.0 で待ち受け、ホスト（Windows/Mac）のブラウザから到達できるようにする
CMD ["npm", "run", "dev", "--", "--host"]
