#!/usr/bin/env bash
# 本書の全セッションの検証を順に実行する。1 つでも失敗したら非 0 で終了する。
# 使い方: cd sandbox && docker compose up -d && ./verify-all.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "=== 型チェック（tsc --noEmit） ==="
docker compose exec -T app npm run --silent typecheck

echo "=== サンドボックスの自己検証（認可サーバーとの疎通・トークン検証） ==="
docker compose exec -T app npx tsx src/verify-setup.ts

# セッション・プロジェクトごとの検証スクリプト
# （章の生成に合わせて src/sessionNN/・src/mid01/・src/final01/ 配下に追加される）
verifies=$(docker compose exec -T app sh -c 'ls src/session*/verify*.ts src/mid*/verify*.ts src/final*/verify*.ts src/review*/q*-check.ts 2>/dev/null || true' | tr -d '\r')
for f in $verifies; do
  echo "=== $f ==="
  docker compose exec -T app npx tsx "$f"
done

echo "=== ユニットテスト（vitest） ==="
if docker compose exec -T app sh -c 'ls src/**/*.test.ts src/*.test.ts 2>/dev/null | head -1' | grep -q .; then
  docker compose exec -T app npm run --silent test
else
  echo "（テストファイルはまだありません）"
fi

echo "すべての検証に成功しました。"
