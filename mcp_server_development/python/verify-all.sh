#!/bin/sh
# Python 側の検証をまとめて実行する（コンテナの中で動かします）
#
#   docker compose exec python sh verify-all.sh
#
# 1 つでも失敗したら非 0 で終了します（人が出力を読んで判断する形にしません）。
set -eu

run() {
  echo "==> $*"
  "$@"
}

echo "===== 1/2 pytest（単体・契約・スナップショット） ====="
run python -m pytest -q

echo "===== 2/2 セッションごとの検証スクリプト（stdio） ====="
for f in $(ls src/*/verify*.py | sort); do
  run python "$f"
done

echo
echo "OK: Python 側の検証がすべて通りました"
