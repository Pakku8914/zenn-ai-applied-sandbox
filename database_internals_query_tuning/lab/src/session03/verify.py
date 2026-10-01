"""セッション3（B+木の構造）の自己検証。

出発点（tools/reset.sh 直後）から単独で実行して成功すること。
B+木の高さ・ページ数・キーの並び・ノードの種類・実測の行数・WAL のレコード数で判定する。
（実行時間・見積もりの rows / cost は判定に使わない）
"""

from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone

from labcheck import (actual_total_rows, check, explain, find_nodes, finish, mysql_connect,
                      node_types, pg_connect)

DAY = "SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'"
PG_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def decode_ts(data: str) -> datetime | None:
    """bt_page_items の data（timestamptz のリトルエンディアン 8 バイト）を日時に戻す。"""
    if not data:
        return None
    usec = struct.unpack("<q", bytes.fromhex(data.replace(" ", "")))[0]
    return PG_EPOCH + timedelta(microseconds=usec)


def verify_before_index(cur) -> None:
    plan = explain(cur, DAY)
    check("インデックスなし: 1 日分の検索は全表走査（Gather / Seq Scan）",
          plan["Plan"]["Node Type"] in ("Gather", "Seq Scan"), " > ".join(node_types(plan)))


def verify_btree_shape(cur) -> None:
    cur.execute("SELECT root, level FROM bt_metap('orders_ordered_at_idx')")
    root, level = cur.fetchone()
    check("orders_ordered_at_idx の高さは 3（ルートの level=2）", level == 2, f"level={level}")

    cur.execute(
        "SELECT type, count(*), max(live_items) FROM bt_multi_page_stats('orders_ordered_at_idx', 1, -1) "
        "GROUP BY type"
    )
    shape = {t: (n, mx) for t, n, mx in cur.fetchall()}
    check("段ごとのページ数: ルート 1・内部 10・リーフ 2733",
          (shape["r"][0], shape["i"][0], shape["l"][0]) == (1, 10, 2733), f"{shape}")
    check("リーフ 1 枚に最大 367 項目（366 件 + high key）", shape["l"][1] == 367, f"{shape['l'][1]}")
    cur.execute("SELECT pg_relation_size('orders_ordered_at_idx') / 8192")
    check("インデックス全体は 2745 ページ（メタページ込み）", cur.fetchone()[0] == 2745)

    cur.execute("SELECT data FROM bt_page_items('orders_ordered_at_idx', %s) ORDER BY itemoffset",
                (root,))
    keys = [decode_ts(d) for (d,) in cur.fetchall()]
    check("ルートの 1 番目は -∞（キーなし）、以降のキーは昇順",
          keys[0] is None and all(a < b for a, b in zip(keys[1:], keys[2:])), f"{len(keys)} 項目")

    cur.execute(
        "SELECT blkno, btpo_prev, btpo_next FROM bt_multi_page_stats('orders_ordered_at_idx', 1, -1) "
        "WHERE type = 'l'"
    )
    links = {blk: (prev, nxt) for blk, prev, nxt in cur.fetchall()}
    leftmost = [b for b, (prev, _) in links.items() if prev == 0]
    visited, blk = 0, leftmost[0] if len(leftmost) == 1 else None
    while blk:
        visited += 1
        blk = links[blk][1]
    check("最左のリーフから btpo_next をたどると全 2733 枚のリーフを 1 回ずつ通る",
          visited == 2733, f"visited={visited}")

    # リーフ 1 → 2 → 次 と、ページをまたいでもキーが昇順に続く（high key = 1 番目は除く）
    prev_last = None
    ok = True
    blk = leftmost[0]
    for _ in range(3):
        cur.execute("SELECT itemoffset, data FROM bt_page_items('orders_ordered_at_idx', %s) "
                    "ORDER BY itemoffset", (blk,))
        items = [decode_ts(d) for off, d in cur.fetchall() if off > 1]
        ok &= all(a <= b for a, b in zip(items, items[1:]))
        if prev_last is not None:
            ok &= prev_last <= items[0]
        prev_last = items[-1]
        blk = links[blk][1]
    check("先頭 3 枚のリーフで、キーがページをまたいで昇順に続く", ok)


def verify_plans_after_index(cur) -> None:
    plan = explain(cur, DAY)
    heap = find_nodes(plan, "Bitmap Heap Scan")
    check("インデックスあり: 1 日分は Index Scan ではなく Bitmap Heap Scan",
          plan["Plan"]["Node Type"] == "Bitmap Heap Scan", " > ".join(node_types(plan)))
    check("1 日分の 2740 行が 2740 ページに散らばっている（Heap Blocks exact=2740）",
          bool(heap) and heap[0].get("Exact Heap Blocks") == 2740
          and actual_total_rows(heap[0]) == 2740)

    cur.execute("SELECT correlation FROM pg_stats WHERE tablename = 'orders' AND attname = 'ordered_at'")
    corr = cur.fetchone()[0]
    check("ordered_at と物理順の相関はほぼ 0", abs(corr) < 0.1, f"correlation={corr:.4f}")

    plan = explain(cur, "SELECT * FROM orders WHERE ordered_at >= '2025-06-01 10:00' "
                        "AND ordered_at < '2025-06-01 10:01'")
    check("1 分間（3 行）は Index Scan", plan["Plan"]["Node Type"] == "Index Scan"
          and actual_total_rows(plan["Plan"]) == 3, " > ".join(node_types(plan)))

    plan = explain(cur, "SELECT * FROM orders ORDER BY ordered_at LIMIT 10")
    check("ORDER BY ordered_at LIMIT 10 はソートなし（Limit > Index Scan）",
          node_types(plan) == ["Limit", "Index Scan"], " > ".join(node_types(plan)))

    plan = explain(cur, "SELECT * FROM orders ORDER BY ordered_at DESC LIMIT 10")
    check("DESC でも逆向きにたどるだけ（Index Scan Backward）",
          find_nodes(plan, "Index Scan")[0].get("Scan Direction") == "Backward")

    sql = "SELECT * FROM orders WHERE ordered_at = '2025-06-01 10:00:11+00'"
    explain(cur, sql, buffers=True)
    plan = explain(cur, sql, buffers=True)
    n = plan["Plan"]
    touched = n["Shared Hit Blocks"] + n["Shared Read Blocks"]
    check("1 件の検索で触るページは 4（木の高さ 3 + ヒープ 1）", touched == 4
          and actual_total_rows(n) == 1, f"hit+read={touched}")


def verify_like(cur) -> None:
    cur.execute("CREATE INDEX IF NOT EXISTS customers_email_idx ON customers (email)")
    cur.execute("ANALYZE customers")
    plan = explain(cur, "SELECT * FROM customers WHERE email LIKE 'user123%'")
    idx = [n for n in (find_nodes(plan, "Index Scan") + find_nodes(plan, "Bitmap Index Scan"))
           if n.get("Index Name") == "customers_email_idx"]
    cond = idx[0].get("Index Cond", "") if idx else ""
    check("前方一致 'user123%' はインデックスの範囲条件になる（>= 'user123' AND < 'user124'）",
          "'user123'" in cond and "'user124'" in cond, cond)
    check("前方一致 'user123%' は 111 件", actual_total_rows(plan["Plan"]) == 111)
    for pattern in ("%@example.com", "%123%", "%12345@example.com"):
        plan = explain(cur, f"SELECT * FROM customers WHERE email LIKE '{pattern}'")
        check(f"'{pattern}' は Seq Scan", plan["Plan"]["Node Type"] == "Seq Scan")
    cur.execute("SET enable_seqscan = off")
    plan = explain(cur, "SELECT * FROM customers WHERE email LIKE '%12345@example.com'")
    cur.execute("RESET enable_seqscan")
    check("Seq Scan を禁止しても後方一致は Seq Scan のまま（Disabled）",
          plan["Plan"]["Node Type"] == "Seq Scan" and plan["Plan"].get("Disabled") is True)


def verify_maintenance(cur) -> None:
    cur.execute("DROP TABLE IF EXISTS s03_ins_0, s03_ins_1, s03_ins_3")
    for t in ("s03_ins_0", "s03_ins_1", "s03_ins_3"):
        cur.execute(f"CREATE TABLE {t} (LIKE orders)")
    cur.execute("CREATE INDEX s03_ins_1_ordered_at_idx ON s03_ins_1 (ordered_at)")
    cur.execute("CREATE INDEX s03_ins_3_ordered_at_idx ON s03_ins_3 (ordered_at)")
    cur.execute("CREATE INDEX s03_ins_3_customer_id_idx ON s03_ins_3 (customer_id)")
    cur.execute("CREATE INDEX s03_ins_3_status_idx ON s03_ins_3 (status)")
    records = {}
    for t in ("s03_ins_0", "s03_ins_1", "s03_ins_3"):
        cur.execute(f"EXPLAIN (ANALYZE, WAL, FORMAT JSON) "
                    f"INSERT INTO {t} SELECT * FROM orders WHERE id <= 100000")
        records[t] = cur.fetchone()[0][0]["Plan"]["WAL Records"]
    r1 = records["s03_ins_1"] / records["s03_ins_0"]
    r3 = records["s03_ins_3"] / records["s03_ins_0"]
    check("インデックス 1 本で WAL レコードが約 2 倍・3 本で約 4 倍（インデックスも毎行更新される）",
          1.9 <= r1 <= 2.2 and 3.8 <= r3 <= 4.4, f"{records}")

    cur.execute("CREATE INDEX s03_ins_0_bulk_idx ON s03_ins_0 (ordered_at)")
    cur.execute("SELECT pg_relation_size('s03_ins_1_ordered_at_idx') / 8192, "
                "pg_relation_size('s03_ins_0_bulk_idx') / 8192")
    grown, bulk = cur.fetchone()
    check("INSERT で育てたインデックスは一括構築より 3 割以上大きい（ページ分割で半端に空く）",
          grown > bulk * 1.3, f"INSERT {grown} ページ / 一括 {bulk} ページ")


def verify_mysql() -> None:
    conn = mysql_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.statistics WHERE table_schema = DATABASE() "
                        "AND table_name = 'orders' AND index_name = 'idx_orders_ordered_at'")
            if cur.fetchone()[0]:
                cur.execute("DROP INDEX idx_orders_ordered_at ON orders")
            cur.execute("CREATE INDEX idx_orders_ordered_at ON orders (ordered_at)")
            cur.execute("EXPLAIN FORMAT=TREE " + DAY)
            tree = cur.fetchone()[0]
            check("MySQL: 1 日分は Index range scan（Bitmap にあたる方式はない）",
                  "Index range scan on orders using idx_orders_ordered_at" in tree, tree.splitlines()[0])
            cur.execute("EXPLAIN FORMAT=TREE " + DAY.replace("SELECT *", "SELECT id"))
            tree = cur.fetchone()[0]
            check("MySQL: id だけならセカンダリインデックスで完結（Covering index range scan）",
                  "Covering index range scan" in tree)
            cur.execute("SELECT count(*) FROM (" + DAY + ") t")
            check("MySQL: 1 日分は 2740 行", cur.fetchone()[0] == 2740)
    finally:
        conn.close()


def main() -> None:
    with pg_connect() as conn, conn.cursor() as cur:
        verify_before_index(cur)
        cur.execute("CREATE INDEX IF NOT EXISTS orders_ordered_at_idx ON orders (ordered_at)")
        verify_btree_shape(cur)
        verify_plans_after_index(cur)
        verify_like(cur)
        verify_maintenance(cur)
    verify_mysql()
    finish("セッション3")


if __name__ == "__main__":
    main()
