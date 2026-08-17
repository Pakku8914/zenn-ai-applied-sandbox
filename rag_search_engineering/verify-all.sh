#!/usr/bin/env bash
# 全セッションの検証を順に実行する。1つでも失敗したら非0で終了する。
#
#   docker compose exec app bash verify-all.sh
#
# 環境変数:
#   SKIP_DENSE=1  埋め込みモデルを使う検証を飛ばす（モデル未取得のときの時短用）
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
python tools/make_corpus.py
python tools/make_fixtures.py

echo
echo "=============================================="
echo " コーパスとチャンクの統計"
echo "=============================================="
python tools/corpus_stats.py
echo
python tools/chunk_stats.py

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
echo " すべての検証が成功しました"
echo "=============================================="
