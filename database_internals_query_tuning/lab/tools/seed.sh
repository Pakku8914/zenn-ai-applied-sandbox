#!/usr/bin/env bash
# 両方の DB にデータを投入する。何度実行しても同じ内容になる（決定的）。
# コンテナ内で実行する: docker compose exec lab bash tools/seed.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "--- PostgreSQL へ投入 ---"
time psql -v ON_ERROR_STOP=1 -q -f sql/seed_pg.sql

echo "--- MySQL へ投入 ---"
# MySQL 9 は既定で TLS を要求するが、同梱のクライアントは自己署名証明書を検証して失敗する。
# サンドボックス内の閉じた通信なので TLS を使わない（本番では必ず有効にする）。
time mysql --skip-ssl -h "${MYSQL_HOST}" -ulab shopdb < sql/seed_mysql.sql

echo "投入が完了しました。"
