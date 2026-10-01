"""S08 ソート・集約・ウィンドウ関数のコスト — 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。章の SQL と同じインデックスを自分で作る。
判定に使うのはノードの種類・Sort Method・HashAggregate の Batches / メモリ量（データが決定的なので一定）・結果の値。
外部ソートと内部ソートの時間差はこの環境では小さい（逆転もする）ため、時間では判定しない。
"""

from __future__ import annotations

from labcheck import (actual_total_rows, check, explain, find_nodes, finish,
                      mysql_connect, node_types, pg_connect, walk)

SORT_ALL = "SELECT id, order_id, quantity * unit_price AS amount FROM order_items ORDER BY amount DESC, id"
AGG_ORDER = "SELECT order_id, sum(quantity * unit_price) AS amount FROM order_items GROUP BY order_id"
AGG_PRODUCT = "SELECT product_id, sum(quantity * unit_price) AS amount FROM order_items GROUP BY product_id"
WINDOW = ("SELECT customer_id, id, ordered_at, "
          "row_number() OVER (PARTITION BY customer_id ORDER BY ordered_at) AS nth FROM orders")
FIRST_ORDERS = f"SELECT count(*) FROM ({WINDOW}) AS s WHERE nth = 1"
PER_NODE = """
SELECT o.customer_id, count(*) AS lines, sum(oi.quantity * oi.unit_price) AS sales,
       rank() OVER (ORDER BY sum(oi.quantity * oi.unit_price) DESC) AS sales_rank
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-01-01' AND o.ordered_at < '2025-04-01' AND o.status <> 'cancelled'
GROUP BY o.customer_id ORDER BY o.customer_id
"""
JIT_QUERY = """
SELECT o.status, count(*) AS lines, sum(oi.quantity * oi.unit_price) AS amount,
       avg(oi.quantity * oi.unit_price) AS avg_amount, max(oi.unit_price) AS max_price
FROM orders o JOIN order_items oi ON oi.order_id = o.id
GROUP BY o.status ORDER BY o.status
"""
MY_SORT = ("SELECT COUNT(*), SUM(amount) FROM (SELECT id, order_id, quantity * unit_price AS amount "
           "FROM order_items ORDER BY amount DESC, id LIMIT 2000000) AS s")


def settings(cur, *stmts: str) -> None:
    cur.execute("RESET ALL")
    for s in stmts:
        cur.execute(s)


def sort_methods(plan: dict) -> list[str]:
    return [n["Sort Method"] for n in find_nodes(plan, "Sort") if "Sort Method" in n]


def hashagg(plan: dict) -> dict:
    return [n for n in find_nodes(plan, "Aggregate") if n.get("Strategy") == "Hashed"][0]


def main() -> None:
    conn = pg_connect()
    cur = conn.cursor()

    # --- E1/E2: 200万行ソートと work_mem ---
    settings(cur)
    cur.execute("SHOW work_mem")
    check("work_mem は 8MB", cur.fetchone()[0] == "8MB")
    plan = explain(cur, SORT_ALL)
    check("8MB では external merge（外部ソート）", sort_methods(plan) == ["external merge"], str(sort_methods(plan)))
    check("全件ソートでも並列にはならない（Gather Merge が出ない）", "Gather Merge" not in node_types(plan))
    settings(cur, "SET work_mem = '64MB'")
    plan = explain(cur, SORT_ALL)
    check("64MB でもまだ external merge", sort_methods(plan) == ["external merge"], str(sort_methods(plan)))
    settings(cur, "SET work_mem = '128MB'")
    plan = explain(cur, SORT_ALL)
    check("128MB で quicksort（内部ソート）", sort_methods(plan) == ["quicksort"], str(sort_methods(plan)))
    settings(cur)
    cur.execute(SORT_ALL + " LIMIT 1")
    check("金額の最大の行", cur.fetchone() == (29, 29, 2997))

    # --- E3: HashAggregate と GroupAggregate ---
    plan = explain(cur, AGG_ORDER)
    h = hashagg(plan)
    check("注文別集計は HashAggregate がディスクに退避する（Batches > 1）",
          h["HashAgg Batches"] > 1 and h["Disk Usage"] > 0, f"Batches {h['HashAgg Batches']}, Disk {h['Disk Usage']}kB")
    check("ハッシュ表は work_mem(8MB) を超え、work_mem×2（16MB）付近まで使う（hash_mem_multiplier = 2）",
          8192 < h["Peak Memory Usage"] < 18000, f"{h['Peak Memory Usage']}kB")
    check("100万グループ", actual_total_rows(plan["Plan"]) == 1000000)
    settings(cur, "SET hash_mem_multiplier = 1")
    h1 = hashagg(explain(cur, AGG_ORDER))
    check("hash_mem_multiplier = 1 ならハッシュ表は work_mem 近くで止まり、Batches が増える",
          h1["Peak Memory Usage"] < h["Peak Memory Usage"] and h1["HashAgg Batches"] > h["HashAgg Batches"],
          f"{h1['Peak Memory Usage']}kB, Batches {h1['HashAgg Batches']}")
    settings(cur, "SET work_mem = '64MB'")
    h64 = hashagg(explain(cur, AGG_ORDER))
    check("64MB ならハッシュ表が 1 回で収まる", h64["HashAgg Batches"] == 1 and h64["Disk Usage"] == 0)
    settings(cur, "SET enable_hashagg = off")
    plan = explain(cur, AGG_ORDER)
    check("HashAggregate を禁止すると Sort ＋ GroupAggregate",
          node_types(plan)[:2] == ["Aggregate", "Sort"] and plan["Plan"].get("Strategy") == "Sorted",
          str(node_types(plan)))
    settings(cur)
    plan = explain(cur, AGG_PRODUCT)
    batches = [n.get("HashAgg Batches") for n in find_nodes(plan, "Aggregate") if n.get("Strategy") == "Hashed"]
    check("商品別（5,000 グループ）はメモリに収まる", batches and all(b == 1 for b in batches), str(batches))
    cur.execute("CREATE INDEX order_items_order_id_idx ON order_items (order_id)")
    plan = explain(cur, AGG_ORDER)
    check("order_id のインデックスがあれば Sort なしの GroupAggregate",
          plan["Plan"].get("Strategy") == "Sorted" and "Sort" not in node_types(plan)
          and "Index Scan" in node_types(plan), str(node_types(plan)))

    # --- E4: Top-N ---
    settings(cur, "SET max_parallel_workers_per_gather = 0")
    plan = explain(cur, SORT_ALL + " LIMIT 10")
    check("LIMIT 10 は top-N heapsort", sort_methods(plan) == ["top-N heapsort"], str(sort_methods(plan)))
    plan = explain(cur, SORT_ALL + " LIMIT 10 OFFSET 100000")
    check("OFFSET 100000 では外部ソートに戻る", sort_methods(plan) == ["external merge"], str(sort_methods(plan)))
    settings(cur)
    plan = explain(cur, SORT_ALL + " LIMIT 100000")
    sorts = find_nodes(plan, "Sort")
    workers = sorts[0].get("Workers", []) if sorts else []
    check("LIMIT 100000 は並列で、ワーカーごとに外部ソートする",
          "Gather Merge" in node_types(plan) and len(workers) == 2
          and all(w.get("Sort Method") == "external merge" for w in workers), str(workers))

    # --- E5: インデックスでソートを省略する ---
    settings(cur)
    plan = explain(cur, "SELECT * FROM orders ORDER BY ordered_at LIMIT 10")
    check("インデックスなしでは Sort が必要", "Sort" in node_types(plan))
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    plan = explain(cur, "SELECT * FROM orders ORDER BY ordered_at LIMIT 10")
    check("ordered_at のインデックスで Sort が消える", "Sort" not in node_types(plan) and "Index Scan" in node_types(plan))
    plan = explain(cur, "SELECT * FROM orders ORDER BY ordered_at DESC LIMIT 10")
    scans = find_nodes(plan, "Index Scan")
    check("DESC はインデックスを後ろから読む", bool(scans) and scans[0].get("Scan Direction") == "Backward")
    plan = explain(cur, "SELECT * FROM orders ORDER BY ordered_at, id LIMIT 10")
    check("先頭キーだけ一致なら Incremental Sort", "Incremental Sort" in node_types(plan))
    plan = explain(cur, "SELECT * FROM orders ORDER BY date_trunc('day', ordered_at) LIMIT 10")
    check("式で並べるとインデックスは使えず Sort", "Sort" in node_types(plan) and "Index Scan" not in node_types(plan))
    q = "SELECT * FROM orders WHERE customer_id = 777 ORDER BY ordered_at DESC LIMIT 10"
    plan = explain(cur, q)
    check("customer_id で絞ると ordered_at のインデックスは役に立たず Sort が残る", "Sort" in node_types(plan))
    cur.execute("CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at)")
    plan = explain(cur, q)
    check("(customer_id, ordered_at) の複合インデックスで Sort が消える", "Sort" not in node_types(plan))
    check("顧客 777 の注文を新しい順に 10 件", actual_total_rows(plan["Plan"]) == 10)

    # --- E6: ウィンドウ関数 ---
    cur.execute("DROP INDEX orders_customer_id_ordered_at_idx")
    plan = explain(cur, WINDOW)
    check("ウィンドウ関数の前段に Sort（外部ソート）", node_types(plan)[:2] == ["WindowAgg", "Sort"]
          and sort_methods(plan) == ["external merge"], str(node_types(plan)))
    plan = explain(cur, FIRST_ORDERS)
    wagg = find_nodes(plan, "WindowAgg")
    check("nth = 1 は Run Condition で打ち切られる", bool(wagg) and "Run Condition" in wagg[0])
    cur.execute(FIRST_ORDERS)
    check("顧客 5 万人それぞれの最初の注文", cur.fetchone()[0] == 50000)
    cur.execute("CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at)")
    plan = explain(cur, WINDOW)
    check("複合インデックスがあれば Sort なしで WindowAgg", "Sort" not in node_types(plan)
          and "Index Scan" in node_types(plan), str(node_types(plan)))

    # --- E7: work_mem はノードごと（出発点に近い状態で測るため、この節で作ったインデックスを消す） ---
    for idx in ("orders_ordered_at_idx", "orders_customer_id_ordered_at_idx", "order_items_order_id_idx"):
        cur.execute(f"DROP INDEX {idx}")
    settings(cur, "SET max_parallel_workers_per_gather = 0")
    plan = explain(cur, PER_NODE)
    mem = []
    for n in walk(plan["Plan"]):
        if n["Node Type"] == "Sort" and n.get("Sort Space Type") == "Memory":
            mem.append(("Sort", n["Sort Space Used"]))
        elif n["Node Type"] in ("Hash", "Aggregate") and "Peak Memory Usage" in n:
            mem.append((n["Node Type"], n["Peak Memory Usage"]))
    total = sum(m for _, m in mem)
    check("1 クエリでメモリを使うノードが 4 つ（Hash・HashAggregate・Sort×2）", len(mem) == 4, str(mem))
    check("ノードの合計は work_mem(8MB) を超える", total > 8192, f"{total}kB")
    hash_mem = [m for t, m in mem if t == "Hash"]
    check("Hash ノード単独でも work_mem を超える（上限は work_mem × hash_mem_multiplier）",
          bool(hash_mem) and 8192 < hash_mem[0] < 18000, str(hash_mem))
    settings(cur)
    plan = explain(cur, PER_NODE)
    partial = [n for n in find_nodes(plan, "Aggregate") if n.get("Partial Mode") == "Partial"]
    check("並列ではワーカーもそれぞれハッシュ表を持つ（Worker 0 / Worker 1）",
          bool(partial) and len(partial[0].get("Workers", [])) == 2, str(partial[0].get("Workers") if partial else None))

    # --- E8: JIT ---
    settings(cur, "SET jit = on")
    cur.execute("SELECT pg_jit_available()")
    check("jit = on で JIT が使える（llvmjit が入っている）", cur.fetchone()[0] is True)
    settings(cur, "SET jit = on", "SET max_parallel_workers_per_gather = 0")
    plan = explain(cur, JIT_QUERY)
    check("並列なし（コスト > 100000）では JIT: が出る", "JIT" in plan, str(plan.get("JIT", {}).get("Functions")))
    settings(cur, "SET jit = off", "SET max_parallel_workers_per_gather = 0")
    check("jit = off では JIT: が出ない", "JIT" not in explain(cur, JIT_QUERY))
    settings(cur, "SET jit = on")
    check("並列あり（コスト < 100000）では jit = on でも JIT: が出ない", "JIT" not in explain(cur, JIT_QUERY))
    settings(cur)
    cur.execute("SELECT o.status, count(*), sum(oi.quantity * oi.unit_price) FROM orders o "
                "JOIN order_items oi ON oi.order_id = o.id GROUP BY o.status ORDER BY o.status")
    rows = cur.fetchall()
    check("ステータス別の明細数は合計 200万", sum(r[1] for r in rows) == 2000000, str(rows))
    conn.close()

    # --- MySQL: sort_buffer_size と Sort_merge_passes ---
    my = mysql_connect()
    with my.cursor() as mc:
        def merge_passes() -> int:
            mc.execute("SHOW SESSION STATUS LIKE 'Sort_merge_passes'")
            return int(mc.fetchone()[1])
        before = merge_passes()
        mc.execute(MY_SORT)
        total_amount = mc.fetchone()
        after_default = merge_passes()
        mc.execute("SET SESSION sort_buffer_size = 128 * 1024 * 1024")
        mc.execute(MY_SORT)
        mc.fetchone()
        after_large = merge_passes()
        check("MySQL: 既定の sort_buffer_size(256KB) では 200万行のソートでマージが発生する",
              after_default - before > 0, f"{after_default - before} 回")
        check("MySQL: 128MB ならマージは発生しない", after_large == after_default)
        check("MySQL: 全明細の金額合計", int(total_amount[1]) == 2199323575, str(total_amount))
    my.close()

    finish("S08 ソート・集約・ウィンドウ関数")


if __name__ == "__main__":
    main()
