"""セッション2（ページ・タプル・ヒープ）の自己検証。

出発点（tools/reset.sh 直後）から単独で実行して成功すること。
ページの中身・ページ数・ctid の変化など、決定的な物理量だけで判定する。
（t_xmin / t_xmax の値や、何度目の実行かでずれる ctid の番号そのものは判定に使わない）
"""

from __future__ import annotations

from labcheck import check, finish, mysql_connect, pg_connect


def page_of(ctid: str) -> int:
    return int(ctid.strip("()").split(",")[0])


def verify_page_layout(cur) -> None:
    cur.execute("SELECT lower, upper FROM page_header(get_raw_page('orders', 0))")
    lower, upper = cur.fetchone()
    check("orders 0 ページ目: 行ポインタ 122 個（lower=512）", lower == 512, f"lower={lower}")
    check("orders 0 ページ目: 空き 8 バイト（満杯）", upper - lower == 8, f"upper-lower={upper - lower}")

    cur.execute(
        "SELECT lp_len, count(*) FROM heap_page_items(get_raw_page('orders', 0)) "
        "GROUP BY lp_len ORDER BY lp_len"
    )
    dist = dict(cur.fetchall())
    check("orders 0 ページ目: 58 バイトの行 105 個・56 バイトの行 17 個",
          dist == {56: 17, 58: 105}, f"{dist}")

    cur.execute("SELECT ctid::text FROM orders WHERE id = 1000")
    ctid = cur.fetchone()[0]
    check("id=1000 の ctid が (8,24)（1 ページ 122 行の計算どおり）", ctid == "(8,24)", ctid)

    cur.execute("SELECT count(*) FROM products WHERE ctid < '(1,0)'")
    check("products 0 ページ目に 136 行", cur.fetchone()[0] == 136)


def verify_page_estimate(cur) -> None:
    # 代表的な 1 行の長さ → 8 バイト境界 → 行ポインタ 4 → 8168 を割る → ページ数
    typical = {"customers": 80, "products": 56, "orders": 58, "order_items": 52}
    for table, row_len in typical.items():
        cur.execute(
            f"SELECT mode() WITHIN GROUP (ORDER BY pg_column_size(x.*)) FROM {table} x"
        )
        got = cur.fetchone()[0]
        check(f"{table} の代表的な行の長さが {row_len} バイト", got == row_len, f"{got}")

    cur.execute(
        "SELECT relname, relpages, reltuples FROM pg_class "
        "WHERE relnamespace = 'public'::regnamespace "
        "AND relname IN ('customers', 'products', 'orders', 'order_items')"
    )
    for relname, relpages, reltuples in cur.fetchall():
        per_row = -(-typical[relname] // 8) * 8 + 4
        rows_per_page = 8168 // per_row
        est = -(-int(reltuples) // rows_per_page)
        diff = (est - relpages) / relpages * 100
        if relname == "orders":
            ok = 1.0 <= diff <= 2.5
            note = "代表値だけだと 1〜2.5% 多めに出る（pending 行が 8 バイト短いため）"
        else:
            ok = abs(diff) <= 0.5
            note = "代表値の見積もりが実測と一致する"
        check(f"{relname}: {note}", ok, f"見積もり {est} / relpages {relpages}（{diff:+.1f}%）")

    cur.execute(
        "SELECT ceil(count(*) / floor(8168 / avg(ceil(pg_column_size(o.*) / 8.0) * 8 + 4))) "
        "FROM orders o"
    )
    est = int(cur.fetchone()[0])
    cur.execute("SELECT relpages FROM pg_class WHERE relname = 'orders'")
    relpages = cur.fetchone()[0]
    check("orders: 行ごとの平均で見積もると relpages と一致", abs(est - relpages) <= 1,
          f"見積もり {est} / relpages {relpages}")


def verify_update_moves_row() -> None:
    conn = pg_connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE orders SET status = 'pending' WHERE id = 1")
            cur.execute("SELECT ctid::text FROM orders WHERE id = 1")
            new_ctid = cur.fetchone()[0]
            check("orders: UPDATE 後の id=1 は 0 ページ目の外にいる（満杯なので別ページへ）",
                  page_of(new_ctid) != 0, new_ctid)
            cur.execute(
                "SELECT t_xmax::text, t_ctid::text FROM heap_page_items(get_raw_page('orders', 0)) "
                "WHERE lp = 1"
            )
            xmax, old_points_to = cur.fetchone()
            cur.execute("SELECT pg_current_xact_id()::text")
            my_xid = cur.fetchone()[0]
            check("orders: 古い版は 0 ページ目に残り、t_ctid が新しい版を指す",
                  old_points_to == new_ctid, f"t_ctid={old_points_to}")
            check("orders: 古い版の t_xmax に自分のトランザクション番号が入る", xmax == my_xid)
            cur.execute(
                "SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_xact_user_tables "
                "WHERE relname = 'orders'"
            )
            upd, hot = cur.fetchone()
            check("orders: 満杯のページでの更新は HOT にならない", upd == 1 and hot == 0,
                  f"n_tup_upd={upd} n_tup_hot_upd={hot}")
            cur.execute("SELECT min(id) FROM orders WHERE ctid < '(1,0)'")
            check("orders: 0 ページ目を読むと先頭の行は id=2（id=1 は見えない）",
                  cur.fetchone()[0] == 2)
        conn.rollback()

        with conn.cursor() as cur:
            cur.execute("UPDATE products SET stock = stock + 1 WHERE id = 1")
            cur.execute("SELECT ctid::text FROM products WHERE id = 1")
            ctid = cur.fetchone()[0]
            cur.execute(
                "SELECT n_tup_hot_upd FROM pg_stat_xact_user_tables WHERE relname = 'products'"
            )
            hot = cur.fetchone()[0]
            check("products（小さいテーブル）でも新しい版は別ページへ・HOT にならない",
                  page_of(ctid) != 0 and hot == 0, f"ctid={ctid} n_tup_hot_upd={hot}")
        conn.rollback()
    finally:
        conn.close()

    with pg_connect() as ac, ac.cursor() as cur:
        cur.execute("SELECT ctid::text FROM orders WHERE id = 1")
        check("ROLLBACK 後の id=1 は (0,1) に戻る", cur.fetchone()[0] == "(0,1)")


def verify_hot(cur) -> None:
    cur.execute("DROP TABLE IF EXISTS s02_orders_ff100, s02_orders_ff90")
    cur.execute("CREATE TABLE s02_orders_ff100 (LIKE orders INCLUDING ALL)")
    cur.execute("CREATE TABLE s02_orders_ff90 (LIKE orders INCLUDING ALL) WITH (fillfactor = 90)")
    for t in ("s02_orders_ff100", "s02_orders_ff90"):
        cur.execute(f"INSERT INTO {t} SELECT * FROM orders WHERE id <= 10000 ORDER BY id")

    cur.execute("SELECT pg_relation_size('s02_orders_ff100') / 8192, "
                "pg_relation_size('s02_orders_ff90') / 8192")
    p100, p90 = cur.fetchone()
    check("1 万行のコピー: fillfactor 100 は 82 ページ・90 は 92 ページ", (p100, p90) == (82, 92),
          f"{p100} / {p90}")

    conn = pg_connect(autocommit=False)
    try:
        for table, expect_same_page in (("s02_orders_ff100", False), ("s02_orders_ff90", True)):
            with conn.cursor() as c:
                c.execute(f"UPDATE {table} SET status = 'pending' WHERE id = 1")
                c.execute(f"SELECT ctid::text FROM {table} WHERE id = 1")
                ctid = c.fetchone()[0]
                c.execute("SELECT n_tup_hot_upd FROM pg_stat_xact_user_tables WHERE relname = %s",
                          (table,))
                hot = c.fetchone()[0]
                c.execute(
                    "SELECT array_agg(DISTINCT flag) FROM heap_page_items(get_raw_page(%s, 0)) h, "
                    "LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) f, "
                    "unnest(f.raw_flags) AS flag", (table,)
                )
                flags = set(c.fetchone()[0] or [])
                if expect_same_page:
                    check(f"{table}: 新しい版は同じページ（0 ページ目）に入り HOT になる",
                          page_of(ctid) == 0 and hot == 1, f"ctid={ctid} n_tup_hot_upd={hot}")
                    check(f"{table}: HEAP_HOT_UPDATED と HEAP_ONLY_TUPLE が立つ",
                          {"HEAP_HOT_UPDATED", "HEAP_ONLY_TUPLE"} <= flags)
                else:
                    check(f"{table}: 新しい版は別ページに入り HOT にならない",
                          page_of(ctid) != 0 and hot == 0, f"ctid={ctid} n_tup_hot_upd={hot}")
            conn.rollback()
    finally:
        conn.close()


def verify_mysql() -> None:
    conn = mysql_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT @@innodb_page_size")
            check("MySQL: InnoDB のページは 16KB", cur.fetchone()[0] == 16384)
            cur.execute("BEGIN")
            cur.execute("UPDATE orders SET status = 'pending' WHERE id = 1")
            # SELECT id だけだと外部キー用のセカンダリインデックス（id を含む）を読むので、行全体を取る
            cur.execute("SELECT * FROM orders LIMIT 3")
            ids = [r[0] for r in cur.fetchall()]
            cur.execute("ROLLBACK")
            check("MySQL: UPDATE しても行は主キーの順に並んだまま", ids == [1, 2, 3], f"{ids}")
    finally:
        conn.close()


def main() -> None:
    with pg_connect() as conn, conn.cursor() as cur:
        verify_page_layout(cur)
        verify_page_estimate(cur)
        verify_hot(cur)
    verify_update_moves_row()
    verify_mysql()
    finish("セッション2")


if __name__ == "__main__":
    main()
