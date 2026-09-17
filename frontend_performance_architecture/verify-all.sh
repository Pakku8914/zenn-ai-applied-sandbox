#!/usr/bin/env bash
# 本書の全セッションの検証を順に実行する。1 つでも失敗したら非 0 で終了する。
# 使い方: cd zenn-ai-applied-sandbox/frontend_performance_architecture && docker compose up -d --wait && ./verify-all.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "=== 型チェック（tsc --noEmit） ==="
docker compose exec -T app npm run --silent typecheck

echo "=== 計測側の依存を用意 ==="
docker compose exec -T measure npm install --no-fund --no-audit --silent

echo "=== サンドボックスの自己検証（Core Web Vitals が計測できること） ==="
docker compose exec -T measure npm run --silent verify

# セッションごとの検証スクリプト（章の生成に合わせて measure/src/sessionNN/ 配下に追加される）
for f in $(docker compose exec -T measure sh -c 'ls src/session*/verify*.ts 2>/dev/null || true' | tr -d '\r'); do
  echo "=== $f ==="
  docker compose exec -T measure node --experimental-strip-types "$f"
done

echo "=== ユニットテスト（vitest） ==="
if docker compose exec -T app sh -c 'ls src/**/*.test.ts src/**/*.test.tsx 2>/dev/null | head -1' | grep -q .; then
  docker compose exec -T app npm run --silent test
else
  echo "（テストファイルはまだありません）"
fi

echo "すべての検証に成功しました。"
