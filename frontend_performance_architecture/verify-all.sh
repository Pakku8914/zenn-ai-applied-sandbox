#!/usr/bin/env bash
# 本書の全セッションの検証を順に実行する。1 つでも失敗したら非 0 で終了する。
# 使い方: cd zenn-ai-applied-sandbox/frontend_performance_architecture && docker compose up -d --wait && ./verify-all.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "=== 型チェック（tsc --noEmit） ==="
docker compose exec -T app npm run --silent typecheck

echo "=== 本番ビルドを作り直す（pages/ に追加した改善版ページを preview に載せる） ==="
docker compose restart preview >/dev/null
docker compose up -d --wait preview >/dev/null

echo "=== Next.js 版を本番ビルドで起動する（S12 の比較対象） ==="
docker compose --profile next restart next >/dev/null 2>&1 || true
docker compose --profile next up -d --wait next >/dev/null

echo "=== 計測側の依存を用意 ==="
docker compose exec -T measure npm install --no-fund --no-audit --silent

echo "=== サンドボックスの自己検証（Core Web Vitals が計測できること） ==="
docker compose exec -T measure npm run --silent verify

# ビルド成果物やソースを調べる検証（app コンテナで実行）
for f in $(docker compose exec -T app sh -c 'ls verify/session*/verify*.ts verify/review*/verify*.ts verify/mid*/verify*.ts verify/final*/verify*.ts 2>/dev/null || true' | tr -d '\r'); do
  echo "=== app/$f ==="
  docker compose exec -T app node "$f"
done

# ブラウザで計測する検証（measure コンテナで実行）
for f in $(docker compose exec -T measure sh -c 'ls src/session*/verify*.ts src/review*/verify*.ts src/mid*/verify*.ts src/final*/verify*.ts 2>/dev/null || true' | tr -d '\r'); do
  echo "=== measure/$f ==="
  docker compose exec -T measure node --experimental-strip-types "$f"
done

echo "=== ユニットテスト（vitest） ==="
if docker compose exec -T app sh -c 'find src -name "*.test.ts" -o -name "*.test.tsx" | head -1' | grep -q .; then
  docker compose exec -T app npm run --silent test
else
  echo "（テストファイルはまだありません）"
fi

echo "すべての検証に成功しました。"
