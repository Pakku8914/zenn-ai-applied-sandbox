#!/usr/bin/env bash
# 本書の全セッションの検証を順に実行する。1 つでも失敗したら非 0 で終了する。
# 使い方: cd zenn-ai-applied-sandbox/database_internals_query_tuning && docker compose up -d --wait && ./verify-all.sh
set -euo pipefail
cd "$(dirname "$0")"

# データが未投入なら投入する（投入済みなら再投入して状態をリセットする）
echo "=== データ投入（決定的。何度実行しても同じ内容） ==="
docker compose exec -T lab bash tools/seed.sh

echo "=== サンドボックスの自己検証（行数・拡張・実行計画の形） ==="
docker compose exec -T lab python src/verify_setup.py

# 章ごとの検証。各検証の前に出発点（主キーと外部キーのみ）へ戻すので、章どうしは互いに依存しない。
# src/<章>/verify*.py（session02〜16・review01〜03・mid01・final）と sql/<章>/verify*.sql を拾う
reset() {
  docker compose exec -T lab bash tools/reset.sh >/dev/null
}

for f in $(docker compose exec -T lab sh -c 'ls src/*/verify*.py 2>/dev/null || true' | tr -d '\r'); do
  echo "=== $f ==="
  reset
  docker compose exec -T lab python "$f"
done

# 期待値と一致しなければ psql が非 0 で終わる
for f in $(docker compose exec -T lab sh -c 'ls sql/*/verify*.sql 2>/dev/null || true' | tr -d '\r'); do
  echo "=== $f ==="
  reset
  docker compose exec -T lab psql -v ON_ERROR_STOP=1 -q -f "$f"
done
reset

echo "すべての検証に成功しました。"
