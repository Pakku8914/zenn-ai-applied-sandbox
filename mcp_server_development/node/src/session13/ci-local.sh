#!/bin/sh
# CI と同じ 3 段を、ローカル（コンテナ内）でも同じ順序で走らせる（問題7-c の解答）
#   docker compose exec node sh src/session13/ci-local.sh
#
# CI にしかコマンドが書かれていない状態を避けるためのスクリプトです。
# CI 側は「このスクリプトと同じコマンドを並べるだけ」にします。
set -eu

echo "==> 1/3 typecheck"
npm run typecheck

echo "==> 2/3 単体・契約・スナップショット"
npx vitest run

echo "==> 3/3 E2E（Inspector CLI）"
npx tsx src/session13/e2e-inspector.ts

echo "OK: CI と同じ 3 段が通りました"
