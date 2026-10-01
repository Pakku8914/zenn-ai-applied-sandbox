#!/usr/bin/env bash
# 章の実験で追加したインデックス・拡張統計・作業用テーブルを片付け、出発点に戻す。
# 通常は数秒で終わる。4テーブルの行が実験で変わっていたときだけ、データを入れ直す（15秒ほど）。
# コンテナ内で実行する: docker compose exec lab bash tools/reset.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# 章の実験で4テーブルの行が変わっていたら、PostgreSQL のデータを入れ直す。
# ROLLBACK した UPDATE でも、ページの並び（ページ数・ctid）が変わって本書の出力と一致しなくなるため。
# 判定：投入後に 0 にした行数カウンタ、または投入直後のページ数（customers 516 / products 37 / orders 8197 / order_items 14706）
state=$(psql -Atq -c "
  SELECT CASE WHEN
      (SELECT coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) FROM pg_stat_user_tables
        WHERE relname IN ('customers', 'products', 'orders', 'order_items')) = 0
      AND pg_relation_size('customers') / 8192 = 516
      AND pg_relation_size('products') / 8192 = 37
      AND pg_relation_size('orders') / 8192 = 8197
      AND pg_relation_size('order_items') / 8192 = 14706
    THEN 'clean' ELSE 'dirty' END")
if [ "$state" != "clean" ]; then
  echo "4テーブルのデータが実験で変わっているため、PostgreSQL のデータを入れ直します（15秒ほどかかります）。"
  psql -v ON_ERROR_STOP=1 -q -f sql/seed_pg.sql
fi

psql -v ON_ERROR_STOP=1 -q -f sql/reset_pg.sql
python tools/reset_mysql.py
echo "出発点に戻しました（主キーと外部キーのみ）。"
