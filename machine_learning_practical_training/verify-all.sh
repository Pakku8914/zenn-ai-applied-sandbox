#!/usr/bin/env bash
# 本書の全セッションの検証を順に実行する。1 つでも失敗したら非 0 で終了する。
# 使い方: cd zenn-ai-applied-sandbox/machine_learning_practical_training && docker compose up -d && ./verify-all.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "=== データセットの生成（何度実行しても同じ内容になる） ==="
docker compose exec -T lab python tools/make_datasets.py

echo "=== サンドボックスの自己検証（本文に載せた数値の再現確認） ==="
docker compose exec -T lab python src/verify_setup.py

# 章ごとの検証スクリプト（src/sessionNN/ と src/reviewNN/・src/midNN/ 配下に追加される）
for f in $(docker compose exec -T lab sh -c 'ls src/*/verify*.py 2>/dev/null || true' | tr -d '\r'); do
  echo "=== $f ==="
  docker compose exec -T lab python "$f"
done

echo "=== ユニットテスト（pytest） ==="
if docker compose exec -T lab sh -c 'ls src/**/test_*.py tests/test_*.py 2>/dev/null | head -1' | grep -q .; then
  docker compose exec -T lab python -m pytest -q
else
  echo "（テストファイルはまだありません）"
fi

echo "すべての検証に成功しました。"
