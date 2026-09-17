#!/usr/bin/env bash
# 本書のコード例を一括で検証する。1つでも失敗したら非0で終了する。
#
# 使い方（コンテナ内で実行する）:
#   docker compose exec ts bash verify-all.sh
set -euo pipefail

echo "=== 型チェック（tsc --noEmit） ==="
npx tsc --noEmit

# Session 19 以降のユニットテスト。テストファイルが無い間も落ちないよう
# --passWithNoTests を付けている。
echo "=== ユニットテスト（vitest） ==="
npx vitest run --passWithNoTests

shopt -s nullglob
files=(src/session*/verify*.ts src/review*/verify*.ts src/mid*/verify*.ts src/final*/verify*.ts)

if [ ${#files[@]} -eq 0 ]; then
  echo "検証対象の verify スクリプトが1つも見つかりません" >&2
  exit 1
fi

for f in "${files[@]}"; do
  echo "=== $f ==="
  npx tsx "$f"
done

# Session 21 以降の Next.js アプリ。まだ依存を入れていない場合はスキップする。
if [ -d web/node_modules ]; then
  echo "=== Next.js アプリの型チェック（web） ==="
  (cd web && npx tsc --noEmit)
  echo "=== Next.js アプリのビルド（web） ==="
  (cd web && npx next build)
else
  echo "=== web/ はスキップ（web/node_modules が無い。cd web && npm install で用意する） ==="
fi

echo "すべての検証に成功しました（${#files[@]} 件）"
