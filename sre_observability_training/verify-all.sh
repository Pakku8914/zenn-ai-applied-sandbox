#!/usr/bin/env bash
# 本書の全セッションの検証を順に実行する。1 つでも失敗したら非 0 で終了する。
# 使い方: cd zenn-ai-applied-sandbox/sre_observability_training && docker compose up -d --wait && ./verify-all.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "=== サンドボックスの自己検証（テレメトリ3経路の到達確認） ==="
docker compose exec -T app python src/verify_setup.py

# セッションごとの検証スクリプト（章の生成に合わせて src/sessionNN/ 配下に追加される）
for f in $(docker compose exec -T app sh -c 'ls src/session*/verify*.py 2>/dev/null || true' | tr -d '\r'); do
  echo "=== $f ==="
  docker compose exec -T app python "$f"
done

echo "=== 負荷試験のしきい値チェック（k6） ==="
docker compose run --rm -T k6 run /scripts/smoke.js

echo "すべての検証に成功しました。"
