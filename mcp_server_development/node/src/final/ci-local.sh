#!/bin/sh
# CI と同じ 4 段を、コンテナの中でも同じ順序で走らせる
#   docker compose exec node sh src/final/ci-local.sh
set -eu

echo "--- 1/4 typecheck ---"
npm run typecheck

echo "--- 2/4 vitest ---"
npx vitest run src/final

echo "--- 3/4 パッケージのビルド ---"
npx tsc -p src/final/pkg/tsconfig.build.json
chmod +x src/final/pkg/dist/final/cli.js

echo "--- 4/4 配布物の検査 ---"
cd src/final/pkg
npm pack --dry-run 2>&1 | grep -E "verify-|\.test\.|auth-server|serve-auth|\.env" && exit 1
echo "OK: 配布物に不要なファイルは含まれていません"
