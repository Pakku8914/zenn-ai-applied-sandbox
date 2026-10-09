#!/usr/bin/env bash
# 全セッションの検証（src/*/verify*.py）を順に実行する。1つでも失敗したら非0で終了する。
# api コンテナの中で実行する：
#   docker compose exec api bash verify-all.sh                 # すべて
#   docker compose exec api bash verify-all.sh src/session01   # 指定したディレクトリだけ
# 各 verify は互いに独立していること（DB はスキーマ sNN、Redis はキー接頭辞 sNN: を自分で初期化する）。
set -uo pipefail
cd "$(dirname "$0")"
shopt -s nullglob

files=()
if [ "$#" -eq 0 ]; then
  files=(src/*/verify*.py)
else
  for dir in "$@"; do
    files+=("${dir%/}"/verify*.py)
  done
fi

if [ "${#files[@]}" -eq 0 ]; then
  echo "verify*.py が見つかりません: ${*:-src/*/}"
  exit 1
fi

failed=()
for f in "${files[@]}"; do
  echo "=== $f ==="
  python "$f"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    failed+=("$f")
  fi
  echo
done

if [ "${#failed[@]}" -eq 0 ]; then
  echo "すべての検証が成功しました（${#files[@]} ファイル）"
  exit 0
fi
echo "失敗した検証：${#failed[@]} / ${#files[@]} ファイル"
printf ' - %s\n' "${failed[@]}"
exit 1
