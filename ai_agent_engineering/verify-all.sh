#!/usr/bin/env bash
# 全セッションの検証を順に実行する。1つでも失敗したら非0で終了する。
#
#   docker compose exec app bash verify-all.sh
#
# 環境変数:
#   SKIP_RUNNER=1  隔離実行コンテナを使う検証を飛ばす（tool-runner 未起動時）
set -euo pipefail
cd "$(dirname "$0")"

echo "=============================================="
echo " 実行環境"
echo "=============================================="
python tools/env_report.py

echo
echo "=============================================="
echo " データの生成（決定的・毎回同じ結果になる）"
echo "=============================================="
python tools/make_data.py
python tools/data_stats.py

echo
echo "=============================================="
echo " セッション別の検証"
echo "=============================================="
for f in src/*/verify*.py; do
  echo
  echo "--- $f ---"
  python "$f"
done

echo
echo "=============================================="
echo " 軌跡の評価"
echo "=============================================="
if [ "${SKIP_RUNNER:-0}" = "1" ]; then
  python tools/eval_trajectories.py --no-runner
else
  python tools/eval_trajectories.py
fi

echo
echo "=============================================="
echo " 演習で汚れたデータを元に戻す"
echo "=============================================="
python tools/make_data.py

echo
echo "=============================================="
echo " すべての検証が成功しました"
echo "=============================================="
