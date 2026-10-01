"""S15 MySQL/InnoDB との比較 — 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。章の SQL と同じインデックス・作業用テーブルを自分で作る。
判定に使うのは、ノードの種類・実測の行数・クエリの結果・ページ数などの物理量・MySQL の計画の表示と、
10 倍以上の差がある時間の大小だけ。PostgreSQL と MySQL の速さは比べない。
MySQL のメモリを大きく使わないよう、投入は 5 万行ずつに分ける。
"""

from __future__ import annotations

import statistics
import time

import psycopg

from labcheck import (actual_total_rows, check, explain, find_nodes, finish,
                      mysql_connect, node_types, pg_connect)

WEEK = "ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08'"
CHUNKS = ((1, 50000), (50001, 100000), (100001, 150000), (150001, 200000))
PG_KEYS = {"seq": "id", "rand": "(id * 48271) % 2147483647",
           "uuid": "substr(encode(sha256(id::text::bytea), 'hex'), 1, 32)::uuid"}
MY_KEYS = {"seq": "id", "rand": "(id * 48271) % 2147483647", "uuid": "UNHEX(LEFT(SHA2(id, 256), 32))"}
TOP5 = """WITH s AS (
  SELECT c.region, oi.product_id, SUM(oi.quantity * oi.unit_price) AS sales
  FROM orders o {h1}
  JOIN customers c {h2} ON c.id = o.customer_id
  JOIN order_items oi {h3} ON oi.order_id = o.id
  WHERE o.status <> 'cancelled'
  GROUP BY c.region, oi.product_id
), r AS (
  SELECT region, product_id, sales,
         ROW_NUMBER() OVER (PARTITION BY region ORDER BY sales DESC, product_id) AS rn
  FROM s
)
SELECT region, rn, product_id, sales FROM r WHERE rn <= 5 ORDER BY region, rn"""
TOP5_PLAIN = TOP5.format(h1="", h2="", h3="")
TOP5_NO_INDEX = TOP5.format(h1="IGNORE INDEX (PRIMARY, fk_orders_customer)", h2="IGNORE INDEX (PRIMARY)",
                            h3="IGNORE INDEX (fk_items_order)")
WEEK_JOIN = f"""SELECT c.region, COUNT(DISTINCT o.id) AS orders, SUM(oi.quantity * oi.unit_price) AS sales
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN order_items oi ON oi.order_id = o.id
WHERE o.{WEEK.replace('ordered_at <', 'o.ordered_at <')}
  AND o.status <> 'cancelled'
GROUP BY c.region
ORDER BY sales DESC"""


def my_tree(mc, sql: str) -> str:
    mc.execute("EXPLAIN FORMAT=TREE " + sql)
    return mc.fetchone()[0]


def my_analyze_ms(mc, sql: str) -> float:
    mc.execute("EXPLAIN ANALYZE " + sql)
    first = mc.fetchone()[0].splitlines()[0]
    return float(first.split("actual time=")[1].split("..")[1].split(" ")[0])


def my_indexes(mc, *tables: str) -> set[str]:
    mc.execute("SELECT DISTINCT index_name FROM information_schema.statistics "
               "WHERE table_schema = DATABASE() AND table_name IN (" + ", ".join(["%s"] * len(tables)) + ")",
               tables)
    return {r[0] for r in mc.fetchall()}


def heap_pages_of_range(cur, table: str) -> int:
    cur.execute(f"SELECT count(DISTINCT (ctid::text::point)[0]) FROM {table} WHERE id BETWEEN 200001 AND 300000")
    return cur.fetchone()[0]


def check_pg(cur) -> list[tuple]:
    # --- E1: 主キー順の範囲読みとセカンダリインデックス ---
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    plan = explain(cur, "SELECT * FROM orders WHERE id BETWEEN 200001 AND 300000")
    scans = [n for n in find_nodes(plan, "Index Scan") if n.get("Index Name") == "orders_pkey"]
    check("PG: 主キーの範囲読みは orders_pkey の Index Scan で 10万行",
          bool(scans) and actual_total_rows(scans[0]) == 100000, str(node_types(plan)))

    plan = explain(cur, f"SELECT id, ordered_at FROM orders WHERE {WEEK}")
    check("PG: (ordered_at) のインデックスだけでは id を返せず Bitmap Heap Scan",
          "Bitmap Heap Scan" in node_types(plan) and "Index Only Scan" not in node_types(plan),
          str(node_types(plan)))
    cur.execute("CREATE INDEX orders_ordered_at_id_idx ON orders (ordered_at) INCLUDE (id)")
    plan = explain(cur, f"SELECT id, ordered_at FROM orders WHERE {WEEK}")
    ios = find_nodes(plan, "Index Only Scan")
    check("PG: INCLUDE (id) を足すと Index Only Scan（1週間 19,180 行・Heap Fetches 0）",
          bool(ios) and actual_total_rows(ios[0]) == 19180 and ios[0]["Heap Fetches"] == 0,
          str(node_types(plan)))

    # --- E2: 主キーの値の並び ---
    for k, key in PG_KEYS.items():
        typ = "uuid" if k == "uuid" else "bigint"
        cur.execute(f"DROP TABLE IF EXISTS s15_pk_{k}")
        cur.execute(f"CREATE TABLE s15_pk_{k} (id {typ} PRIMARY KEY, customer_id integer NOT NULL, "
                    "ordered_at timestamptz NOT NULL, status text NOT NULL)")
        for a, b in CHUNKS:
            cur.execute(f"INSERT INTO s15_pk_{k} SELECT {key}, customer_id, ordered_at, status FROM orders "
                        f"WHERE id BETWEEN {a} AND {b} ORDER BY id")
        cur.execute(f"VACUUM ANALYZE s15_pk_{k}")
        cur.execute(f"CREATE INDEX s15_pk_{k}_ordered_at_idx ON s15_pk_{k} (ordered_at)")
    size = {}
    for k in PG_KEYS:
        cur.execute(f"SELECT pg_relation_size('s15_pk_{k}') / 8192, pg_relation_size('s15_pk_{k}_pkey') / 8192, "
                    f"pg_relation_size('s15_pk_{k}_ordered_at_idx') / 8192, "
                    f"(SELECT avg_leaf_density FROM pgstatindex('s15_pk_{k}_pkey'))")
        size[k] = cur.fetchone()
    check("PG: ヒープの大きさは主キーの並びに関係ない（連番 = ランダム順の整数）",
          size["seq"][0] == size["rand"][0], str({k: v[0] for k, v in size.items()}))
    check("PG: 主キーのインデックスは 連番 < ランダム整数 < UUID",
          size["seq"][1] < size["rand"][1] < size["uuid"][1], str({k: v[1] for k, v in size.items()}))
    check("PG: 連番の主キーはリーフがいちばん詰まっている",
          size["seq"][3] > size["rand"][3] and size["seq"][3] > size["uuid"][3],
          str({k: float(v[3]) for k, v in size.items()}))
    check("PG: セカンダリインデックスの大きさは主キーの太さに関係ない",
          size["seq"][2] == size["rand"][2] == size["uuid"][2], str({k: v[2] for k, v in size.items()}))

    # --- E3: 古い版はヒープに残る（S10・S12 の復習） ---
    cur.execute("DROP TABLE IF EXISTS s15_mvcc")
    cur.execute("CREATE TABLE s15_mvcc (id integer PRIMARY KEY, v integer NOT NULL) WITH (autovacuum_enabled = off)")
    cur.execute("INSERT INTO s15_mvcc SELECT id, 0 FROM orders WHERE id <= 1000")
    cur.execute("VACUUM ANALYZE s15_mvcc")
    notices: list[str] = []
    cur.connection.add_notice_handler(lambda d: notices.append(d.message_primary or ""))
    a = psycopg.connect(prepare_threshold=None)
    a.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
    a.execute("SELECT sum(v) FROM s15_mvcc").fetchone()
    for _ in range(5000):
        cur.execute("UPDATE s15_mvcc SET v = v + 1 WHERE id = 1")
    cur.execute("VACUUM (VERBOSE) s15_mvcc")
    blocked = " ".join(notices)
    old = a.execute("SELECT sum(v) FROM s15_mvcc").fetchone()[0]
    a.execute("COMMIT")
    a.close()
    check("PG: 古いスナップショットからは更新前の合計 0 が見える", old == 0, str(old))
    check("PG: スナップショットを持っている間、VACUUM は 5000 版を回収できない",
          "5000 are dead but not yet removable" in blocked)
    notices.clear()
    cur.execute("VACUUM (VERBOSE) s15_mvcc")
    check("PG: COMMIT の後の VACUUM は 5000 版を回収する", "tuples: 5000 removed" in " ".join(notices))

    # --- 演習: 地域別の売上上位5商品 ---
    cur.execute(TOP5_PLAIN)
    pg_top5 = [(r[0], int(r[1]), int(r[2]), int(r[3])) for r in cur.fetchall()]
    plan = explain(cur, TOP5_PLAIN)
    check("PG: 地域別上位5商品は 25 行", len(pg_top5) == 25)
    check("PG: 既定の計画は Hash Join（Nested Loop なし）",
          "Hash Join" in node_types(plan) and "Nested Loop" not in node_types(plan), str(node_types(plan)))

    # --- 演習: 更新でヒープの並びが崩れる ---
    cur.execute("DROP TABLE IF EXISTS s15_orders_copy")
    cur.execute("CREATE TABLE s15_orders_copy AS SELECT * FROM orders ORDER BY id")
    cur.execute("ALTER TABLE s15_orders_copy ADD PRIMARY KEY (id)")
    cur.execute("VACUUM ANALYZE s15_orders_copy")
    before = heap_pages_of_range(cur, "s15_orders_copy")
    cur.execute("UPDATE s15_orders_copy SET status = status WHERE id % 10 = 0")
    cur.execute("VACUUM ANALYZE s15_orders_copy")
    after = heap_pages_of_range(cur, "s15_orders_copy")
    cur.execute("SELECT correlation FROM pg_stats WHERE tablename = 's15_orders_copy' AND attname = 'id'")
    corr = cur.fetchone()[0]
    check("PG: 1割を更新すると、同じ主キー範囲の行が散らばるページが増える", after > before, f"{before} → {after}")
    check("PG: 更新後の id の correlation は 1 から下がる", corr < 0.95, f"{corr:.3f}")
    cur.execute("DROP TABLE s15_orders_copy")
    return pg_top5


def check_mysql(mc, pg_top5: list[tuple]) -> None:
    # --- E1: クラスタ化インデックス ---
    mc.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    tree = my_tree(mc, "SELECT * FROM orders WHERE id BETWEEN 200001 AND 300000")
    check("MySQL: 主キーの範囲読みは PRIMARY の Index range scan", "Index range scan on orders using PRIMARY" in tree)
    tree = my_tree(mc, f"SELECT id, ordered_at FROM orders WHERE {WEEK}")
    check("MySQL: (ordered_at) のインデックスだけで id も返せる（Covering index range scan）",
          "Covering index range scan on orders using orders_ordered_at_idx" in tree)
    tree = my_tree(mc, f"SELECT * FROM orders WHERE {WEEK}")
    check("MySQL: 全列を取ると主キーで引き直す Index range scan（Covering ではない）",
          "Index range scan on orders using orders_ordered_at_idx" in tree and "Covering" not in tree)

    # --- E4: 表形式の EXPLAIN ---
    mc.execute("EXPLAIN FORMAT=TRADITIONAL " + WEEK_JOIN)
    cols = [d[0] for d in mc.description]
    types = {r[cols.index("table")]: r[cols.index("type")] for r in mc.fetchall()}
    check("MySQL: 1週間の地域別集計の type 列は o=range / c=eq_ref / oi=ref",
          types == {"o": "range", "c": "eq_ref", "oi": "ref"}, str(types))

    # --- E2: 主キーの値の並び ---
    for k, key in MY_KEYS.items():
        typ = "BINARY(16)" if k == "uuid" else "BIGINT"
        mc.execute(f"DROP TABLE IF EXISTS s15_pk_{k}")
        mc.execute(f"CREATE TABLE s15_pk_{k} (id {typ} NOT NULL PRIMARY KEY, customer_id INT NOT NULL, "
                   "ordered_at DATETIME NOT NULL, status VARCHAR(10) NOT NULL)")
        for a, b in CHUNKS:
            mc.execute(f"INSERT INTO s15_pk_{k} SELECT {key}, customer_id, ordered_at, status FROM orders "
                       f"WHERE id BETWEEN {a} AND {b} ORDER BY id")
    mc.execute("SET SESSION information_schema_stats_expiry = 0")
    mc.execute("ANALYZE TABLE s15_pk_seq, s15_pk_rand, s15_pk_uuid")
    mc.fetchall()
    mc.execute("SELECT table_name, data_length FROM information_schema.tables "
               "WHERE table_schema = DATABASE() AND table_name LIKE 's15\\_pk\\_%'")
    data = {r[0].removeprefix("s15_pk_"): r[1] for r in mc.fetchall()}
    check("MySQL: テーブル本体（クラスタ化インデックス）は 連番 < ランダム整数 < UUID",
          data["seq"] < data["rand"] < data["uuid"], str(data))
    mc.execute("SELECT table_name, AVG(data_size) FROM information_schema.innodb_buffer_page "
               "WHERE table_name LIKE CONCAT('`', DATABASE(), '`.`s15\\_pk\\_%') AND index_name = 'PRIMARY' "
               "GROUP BY table_name")
    fill = {r[0].split("s15_pk_")[1].rstrip("`"): float(r[1]) for r in mc.fetchall()}
    check("MySQL: 連番の主キーはページがいちばん詰まっている（バッファプール上のページ）",
          len(fill) == 3 and fill["seq"] > fill["rand"] and fill["seq"] > fill["uuid"],
          str({k: round(v / 16384 * 100, 1) for k, v in fill.items()}))
    for k in MY_KEYS:
        mc.execute(f"CREATE INDEX s15_pk_{k}_ordered_at_idx ON s15_pk_{k} (ordered_at)")
    mc.execute("ANALYZE TABLE s15_pk_seq, s15_pk_rand, s15_pk_uuid")
    mc.fetchall()
    mc.execute("SELECT table_name, index_length FROM information_schema.tables "
               "WHERE table_schema = DATABASE() AND table_name LIKE 's15\\_pk\\_%'")
    idx = {r[0].removeprefix("s15_pk_"): r[1] for r in mc.fetchall()}
    check("MySQL: セカンダリインデックスは主キーの値を持つので、UUID の主キーだと太る",
          idx["seq"] == idx["rand"] < idx["uuid"], str(idx))
    mc.execute("DROP TABLE s15_pk_seq, s15_pk_rand, s15_pk_uuid")

    # --- E3: UNDO と purge ---
    mc.execute("DROP TABLE IF EXISTS s15_undo")
    mc.execute("CREATE TABLE s15_undo (id INT PRIMARY KEY, v INT NOT NULL)")
    mc.execute("INSERT INTO s15_undo SELECT id, 0 FROM orders WHERE id <= 1000")
    a = mysql_connect()
    ac = a.cursor()
    ac.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
    ac.execute("SELECT SUM(v) FROM s15_undo")
    ac.fetchall()
    before_a = statistics.median(my_analyze_ms(ac, "SELECT SUM(v) FROM s15_undo") for _ in range(3))
    for _ in range(5000):
        mc.execute("UPDATE s15_undo SET v = v + 1 WHERE id = 1")
    mc.execute("SELECT count FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len'")
    hll = mc.fetchone()[0]
    mc.execute("SELECT SUM(v) FROM s15_undo")
    new_sum = mc.fetchone()[0]
    ac.execute("SELECT SUM(v) FROM s15_undo")
    old_sum = ac.fetchone()[0]
    after_a = statistics.median(my_analyze_ms(ac, "SELECT SUM(v) FROM s15_undo") for _ in range(3))
    reader_b = statistics.median(my_analyze_ms(mc, "SELECT SUM(v) FROM s15_undo") for _ in range(3))
    ac.execute("COMMIT")
    a.close()
    check("MySQL: スナップショットを持っている間、History list length が 5000 以上になる", hll >= 5000, str(hll))
    check("MySQL: 新しい読み手は 5000、古いスナップショットは 0 を見る", (new_sum, old_sum) == (5000, 0),
          str((new_sum, old_sum)))
    # 実測の差は 9〜40 倍と揺れるので、判定は緩く 3 倍にする
    check("MySQL: 古いスナップショットの読みは undo をたどるぶん遅くなる（更新前の自分・新しい読み手より遅い）",
          after_a > reader_b * 3 and after_a > before_a * 3,
          f"A 前 {before_a} ms / A 後 {after_a} ms / B {reader_b} ms")
    mc.execute("DROP TABLE s15_undo")

    # --- 演習: 地域別の売上上位5商品 ---
    tree = my_tree(mc, TOP5_PLAIN)
    # 駆動表（customers / orders / order_items のどれから読むか）は ANALYZE TABLE の標本で変わるので判定しない
    check("MySQL: 既定の計画はインデックスを引く Nested loop（hash join なし）",
          "Nested loop inner join" in tree and "hash join" not in tree.lower())
    tree = my_tree(mc, TOP5_NO_INDEX)
    check("MySQL: 結合に使えるインデックスを外すと hash join になる", "Inner hash join" in tree)
    mc.execute(TOP5_PLAIN)
    my_top5 = [(r[0], int(r[1]), int(r[2]), int(r[3])) for r in mc.fetchall()]
    check("MySQL: 地域別上位5商品の結果は PostgreSQL と同じ（並び順は照合順序で変わるので集合で比べる）",
          sorted(my_top5) == sorted(pg_top5), f"{len(my_top5)} 行")

    # --- 演習: 結合に使う列を全部持つセカンダリインデックス ---
    mc.execute("CREATE INDEX s15_orders_customer_status_idx ON orders (customer_id, status)")
    mc.execute("CREATE INDEX s15_items_order_cover_idx ON order_items (order_id, product_id, quantity, unit_price)")
    try:
        left = my_indexes(mc, "orders", "order_items")
        check("MySQL: 外部キーの列で始まるインデックスを作ると、外部キー用のインデックスが消える",
              "fk_orders_customer" not in left and "fk_items_order" not in left, str(sorted(left)))
        tree = my_tree(mc, TOP5_PLAIN)
        check("MySQL: Nested loop の内側が Covering index lookup になる（クラスタ化インデックスを引き直さない）",
              "Covering index lookup on o using s15_orders_customer_status_idx" in tree
              or "Covering index lookup on oi using s15_items_order_cover_idx" in tree)
    finally:
        for s in ("SET SESSION foreign_key_checks = 0",
                  "ALTER TABLE orders DROP FOREIGN KEY fk_orders_customer",
                  "DROP INDEX s15_orders_customer_status_idx ON orders",
                  "ALTER TABLE orders ADD CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) "
                  "REFERENCES customers (id), ALGORITHM = INPLACE",
                  "ALTER TABLE order_items DROP FOREIGN KEY fk_items_order",
                  "DROP INDEX s15_items_order_cover_idx ON order_items",
                  "ALTER TABLE order_items ADD CONSTRAINT fk_items_order FOREIGN KEY (order_id) "
                  "REFERENCES orders (id), ALGORITHM = INPLACE",
                  "SET SESSION foreign_key_checks = 1"):
            mc.execute(s)
    left = my_indexes(mc, "orders", "order_items")
    check("MySQL: 後片付けで外部キー用のインデックスが戻る",
          {"fk_orders_customer", "fk_items_order"} <= left and not any(i.startswith("s15_") for i in left),
          str(sorted(left)))


def main() -> None:
    conn = pg_connect()
    cur = conn.cursor()
    pg_top5 = check_pg(cur)
    conn.close()

    my = mysql_connect()
    with my.cursor() as mc:
        check_mysql(mc, pg_top5)
    my.close()

    finish("S15 MySQL/InnoDB との比較")


if __name__ == "__main__":
    main()
