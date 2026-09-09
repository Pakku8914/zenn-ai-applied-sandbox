#!/usr/bin/env bash
# 全セッションの検証を順に実行する。1つでも失敗したら非0で終了する。
#   docker compose exec app bash verify-all.sh
set -euo pipefail

cd /workspace

echo "### モックの状態をリセットする"
python - <<'PY'
import json, urllib.request
req = urllib.request.Request(
    "http://bedrock-mock:8080/_mock/reset", data=b"{}",
    headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=10) as res:
    print(json.loads(res.read()))
PY

failed=0
for f in src/*/verify*.py; do
  echo
  echo "=== $f ==="
  if ! python "$f"; then
    failed=1
    echo "!!! $f が失敗しました"
  fi
done

if [ -d src ] && compgen -G "src/*/test_*.py" > /dev/null; then
  echo
  echo "=== pytest ==="
  python -m pytest || failed=1
fi

if [ "$failed" -ne 0 ]; then
  echo
  echo "検証に失敗したスクリプトがあります"
  exit 1
fi

echo
echo "すべての検証に成功しました"
