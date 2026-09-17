# 本番用のイメージを作る Dockerfile（セッション28）。
# 開発用の ../Dockerfile とは別物である。開発用は「編集してすぐ動かす」ための入れ物、
# こちらは「ビルド済みのものだけを配る」ための入れ物。
#
# 3段に分けてある:
#   1) deps    — 依存だけを入れる（package.json が変わらなければキャッシュが効く）
#   2) builder — Prisma Client を生成して next build する
#   3) runner  — 動かすのに必要なものだけを持つ最終イメージ
#
# ビルド（サンドボックスのフォルダで実行する。数分かかる）:
#   docker build -f web/Dockerfile -t mini-zakka-web:1.0.0 web
# 実行:
#   docker run --rm -p 3000:3000 -e DATABASE_URL=postgresql://... mini-zakka-web:1.0.0
#
# verify-all.sh には含めていない（ビルドに時間がかかるため）。
# 段の構成が正しいかは src/session28/verify.ts がこのファイルを読んで検査する。

# ---------------------------------------------------------------------------
# 1段目: 依存のインストール
# ---------------------------------------------------------------------------
FROM node:24-bookworm-slim AS deps

# Prisma のクエリエンジンが openssl を必要とする
RUN apt-get update \
  && apt-get install -y --no-install-recommends openssl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# package.json と package-lock.json だけを先にコピーする。
# アプリのコードをいくら直しても、この2つが変わらなければこの段はキャッシュから再利用される。
COPY package.json package-lock.json ./

# npm ci はロックファイルのとおりに入れる（npm install と違い、勝手に更新しない）
RUN npm ci

# ---------------------------------------------------------------------------
# 2段目: ビルド
# ---------------------------------------------------------------------------
FROM node:24-bookworm-slim AS builder

RUN apt-get update \
  && apt-get install -y --no-install-recommends openssl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# ビルド中はデータベースに接続しないが、Prisma Client の生成とページの収集で
# DATABASE_URL の「存在」だけを見る箇所がある。形だけ満たすダミーを置く。
# 本物の接続情報は実行時（docker run の -e）に渡す。
ENV DATABASE_URL=postgresql://build:build@127.0.0.1:5432/build

# データベースに接続せずに Prisma Client の型と実装を作る
RUN npx prisma generate

# next.config.ts の output: 'standalone' により .next/standalone が作られる
RUN npx next build

# ---------------------------------------------------------------------------
# 3段目: 実行
# ---------------------------------------------------------------------------
FROM node:24-bookworm-slim AS runner

RUN apt-get update \
  && apt-get install -y --no-install-recommends openssl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
# コンテナの外からの接続を受けるため 0.0.0.0 で待ち受ける
ENV HOSTNAME=0.0.0.0

# node ユーザー（uid 1000）は node:24 のイメージに最初から用意されている。
# root で動かさないのは、侵入されたときにできることを減らすため。
USER node

# standalone には「動かすのに必要な node_modules だけ」が入っている。
# だから node_modules を丸ごとコピーしない（ここが小さくなる理由）。
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

# 画像や favicon を置く public フォルダを作ったら、次の行を有効にする。
# 本書のサンドボックスには public フォルダが無いため、コメントにしてある。
# COPY --from=builder --chown=node:node /app/public ./public

EXPOSE 3000

# standalone の入口。next start ではなく server.js を直接動かす
CMD ["node", "server.js"]
