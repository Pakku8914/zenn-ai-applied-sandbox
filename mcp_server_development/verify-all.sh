#!/usr/bin/env bash
# 本書の全セッションの検証を、TypeScript・Python の両方でまとめて実行する。
# 1 つでも失敗したら非 0 で終了する。
#
#   cd zenn-ai-applied-sandbox/mcp_server_development
#   docker compose up -d --build
#   ./verify-all.sh
#   SKIP_HTTP=1 ./verify-all.sh   # HTTP 章（認可サーバーを起動する）を飛ばす
#
# 中身は各サービスの verify-all.sh を順に呼ぶだけ。コンテナの中で直接叩いてもよい。
#   docker compose exec node   sh verify-all.sh
#   docker compose exec python sh verify-all.sh
set -euo pipefail

cd "$(dirname "$0")"

echo "########## TypeScript（node サービス） ##########"
docker compose exec -T -e "SKIP_HTTP=${SKIP_HTTP:-0}" node sh verify-all.sh

echo
echo "########## Python（python サービス） ##########"
docker compose exec -T python sh verify-all.sh

echo
echo "==================================================="
echo "OK: TypeScript・Python の両方で全セッションが通りました"
echo "==================================================="
