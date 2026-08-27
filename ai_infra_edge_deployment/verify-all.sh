#!/usr/bin/env bash
# 全セッションの検証を順に実行する。1つでも失敗したら非0で終了する。
#
#   docker compose exec app bash verify-all.sh
#
# 環境変数:
#   SKIP_SERVER=1  推論サーバ・ゲートウェイを使う検証を飛ばす（各 verify 側が解釈する）
#
# 検証スクリプトは src/sessionNN/verify*.py を「セッション番号順・ファイル名順」で
# 自動的に拾う。章を追加したら verify*.py を置くだけでよく、このファイルの編集は不要。
set -euo pipefail
cd "$(dirname "$0")"

echo "=============================================="
echo " 実行環境"
echo "=============================================="
python tools/env_report.py

# セッション番号順・ファイル名順に並べる（LC_ALL=C で環境差をなくす）
scripts=$(find src -type f -name 'verify*.py' | LC_ALL=C sort)

if [ -z "$scripts" ]; then
  echo "検証スクリプトが1つも見つかりません（src/sessionNN/verify*.py）" >&2
  exit 1
fi

total=$(echo "$scripts" | wc -l | tr -d ' ')
echo
echo "検出した検証スクリプト: ${total} 本"

n=0
for s in $scripts; do
  n=$((n + 1))
  echo
  echo "=============================================="
  echo " [${n}/${total}] ${s}"
  echo "=============================================="
  python "$s"
done

echo
echo "=============================================="
echo " すべての検証が成功しました（${total} 本）"
echo "=============================================="
