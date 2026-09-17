# 本書の演習で使う Node.js 環境。
# node:24-bookworm-slim には openssl と curl が入っていないため追加する。
#   - openssl : Prisma のクエリエンジンが必要とする（Session 23 以降）
#   - curl    : HTTP のリクエストを手で送って確かめる（Session 20）
FROM node:24-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends openssl curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /work
