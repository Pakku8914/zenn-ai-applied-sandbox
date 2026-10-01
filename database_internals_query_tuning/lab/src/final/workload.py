"""Final 最終プロジェクト — 注文管理画面の負荷を再現する。

画面が発行する 5 本のクエリを、利用頻度に近い比率（50 操作あたり Q1 20・Q2 15・Q3 10・Q4 4・Q5 1）で、
複数の接続から同時に繰り返す。操作の並びとパラメータは決定的（何度実行しても同じ操作列になる）。

  Q1 顧客の注文一覧（顧客詳細画面。直近 10 件の注文と金額）
  Q2 在庫引き当て（注文確定ボタン。在庫を減らし、出荷待ちに積む）
  Q3 未発送の注文の検索（倉庫の担当者が、自分の地域の古い順に 50 件を見る）
  Q4 商品別ランキング（カテゴリ別・直近 7 日の売上上位 10 商品）
  Q5 日別の売上（直近 90 日の日別売上と購入者数。管理者向けのレポート）

使い方（サンドボックスのディレクトリで。改善前は数十秒かかる）:
  docker compose exec lab python src/final/workload.py                     # 在庫引き当ては改善前の書き方
  docker compose exec lab python src/final/workload.py --allocation short  # 在庫引き当てを改善後の書き方にする

最初に、この DB の pg_stat_statements だけをリセットする（pg_stat_statements_reset(0, <この DB の oid>, 0)。
他の DB の統計は消さない）。終わったら sql/final/02_top_queries.sql で総実行時間の順位を見る。
どの接続にも lock_timeout / statement_timeout を付けてあるので、想定外の待ちが起きても止まったままにはならない。
"""

from __future__ import annotations

import argparse
import threading
import time

import psycopg
from psycopg.types.numeric import Int4

Q1_CUSTOMER_ORDERS = """
SELECT o.id, o.ordered_at, o.status, count(*) AS items, sum(oi.quantity * oi.unit_price) AS amount
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.customer_id = %s
GROUP BY o.id
ORDER BY o.ordered_at DESC
LIMIT 10
"""

# Q2 在庫引き当て。改善前は「行ロックを取る → 外部の決済 API を呼ぶ → 在庫を減らす → 出荷待ちに積む → COMMIT」を
# 1 つのトランザクションで行う（API の応答を待つ間も行ロックを持ち続ける）
Q2_LOCK = "SELECT stock FROM final_products WHERE id = %s FOR UPDATE"
Q2_UPDATE = "UPDATE final_products SET stock = stock - %s WHERE id = %s"
# 改善後は「在庫が足りれば減らす」を 1 文で行い、すぐ COMMIT する。決済 API はトランザクションの外で呼ぶ
Q2_UPDATE_SHORT = "UPDATE final_products SET stock = stock - %s WHERE id = %s AND stock >= %s RETURNING stock"
Q2_ENQUEUE = """
INSERT INTO final_ship_queue (order_id, customer_id, region, ordered_at)
SELECT nextval('final_order_id_seq'), id, region, now() FROM customers WHERE id = %s
"""

Q3_SHIP_QUEUE = """
SELECT order_id, customer_id, ordered_at
FROM final_ship_queue
WHERE region = %s
ORDER BY ordered_at
LIMIT 50
"""

Q4_RANKING = """
SELECT p.id, p.name, sum(oi.quantity) AS qty, sum(oi.quantity * oi.unit_price) AS sales
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-12-25' AND o.ordered_at < '2026-01-01'
  AND o.status <> 'cancelled' AND p.category = %s
GROUP BY p.id, p.name
ORDER BY sales DESC
LIMIT 10
"""

Q5_DAILY_SALES = """
SELECT date_trunc('day', o.ordered_at) AS day,
       count(DISTINCT o.customer_id) AS buyers,
       sum(oi.quantity * oi.unit_price) AS sales
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled'
  AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
GROUP BY 1
ORDER BY 1
"""

NAMES = {
    "Q1": "顧客の注文一覧",
    "Q2": "在庫引き当て",
    "Q3": "未発送の注文の検索",
    "Q4": "商品別ランキング",
    "Q5": "日別の売上",
}
MIX = (("Q1", 20), ("Q2", 15), ("Q3", 10), ("Q4", 4), ("Q5", 1))  # 50 操作あたりの回数
HOT_PRODUCT = 777        # セール中の人気商品。引き当ての 3 回に 2 回はこの商品
REGIONS = ("東京", "大阪", "名古屋", "福岡", "札幌")
CATEGORIES = ("文具", "書籍", "雑貨", "食品")


def pattern() -> list[str]:
    """50 操作の並び。各クエリの回数は MIX のとおりで、同じ種類が固まらないよう均等に散らす
    （種類ごとに n 回を 50 枠へ等間隔に置いた位置の順に並べる）。"""
    total = sum(n for _, n in MIX)
    placed = [((j + 0.5) * total / n, order, kind)
              for order, (kind, n) in enumerate(MIX) for j in range(n)]
    return [kind for _, _, kind in sorted(placed)]


def build_plan(ops: int) -> list[tuple[str, tuple]]:
    """op 番号 k ごとの（クエリの種類, パラメータ）。k だけで決まるので、何度実行しても同じ操作列になる。"""
    slots = pattern()
    plan = []
    for k in range(ops):
        kind = slots[k % len(slots)]
        # 整数は Int4（integer）として送る。psycopg は Python の int を値の大きさで smallint / integer に送り分けるため、
        # そのままだと同じ SQL がパラメータの型ごとに pg_stat_statements の別の行に分かれてしまう
        if kind == "Q1":
            params = (Int4(1 + (k * 7919) % 50000),)
        elif kind == "Q2":
            product = HOT_PRODUCT if k % 3 else 1 + (k * 104729) % 5000
            params = (Int4(product), Int4(1), Int4(1 + (k * 31) % 50000))   # 商品, 数量, 注文した顧客
        elif kind == "Q3":
            params = (REGIONS[k % len(REGIONS)],)
        elif kind == "Q4":
            params = (CATEGORIES[k % len(CATEGORIES)],)
        else:
            params = ()
        plan.append((kind, params))
    return plan


def allocate(conn: psycopg.Connection, params: tuple, mode: str, api_ms: int) -> bool:
    """在庫を引き当てる。成功すれば True（在庫不足なら False）。"""
    product, qty, customer = params
    cur = conn.cursor()
    if mode == "long":
        with conn.transaction():
            cur.execute(Q2_LOCK, (product,))
            if cur.fetchone()[0] < qty:
                raise psycopg.Rollback()
            time.sleep(api_ms / 1000)          # 外部の決済 API を呼ぶ（行ロックを持ったまま応答を待つ）
            cur.execute(Q2_UPDATE, (qty, product))
            cur.execute(Q2_ENQUEUE, (customer,))
        return True
    with conn.transaction():
        cur.execute(Q2_UPDATE_SHORT, (qty, product, qty))
        if cur.fetchone() is None:
            raise psycopg.Rollback()
        cur.execute(Q2_ENQUEUE, (customer,))
    time.sleep(api_ms / 1000)                  # 決済 API はトランザクションの外で呼ぶ（失敗したら別の短いトランザクションで在庫を戻す）
    return True


QUERIES = {"Q1": Q1_CUSTOMER_ORDERS, "Q3": Q3_SHIP_QUEUE, "Q4": Q4_RANKING, "Q5": Q5_DAILY_SALES}


def run(ops: int = 1000, threads: int = 4, allocation: str = "long", api_ms: int = 50,
        reset: bool = True, quiet: bool = False) -> dict:
    plan = build_plan(ops)
    if reset:
        with psycopg.connect(autocommit=True) as c:
            c.execute("SELECT pg_stat_statements_reset(0, (SELECT oid FROM pg_database "
                      "WHERE datname = current_database()), 0)")
    next_op = iter(range(ops))
    lock = threading.Lock()
    elapsed: dict[str, list[float]] = {kind: [] for kind in NAMES}
    errors: dict[str, int] = {kind: 0 for kind in NAMES}

    def worker() -> None:
        # 自動プリペアを止める（毎回その値で計画を立てる）。待ちが続いてもハングしないよう上限を付ける
        with psycopg.connect(autocommit=True, prepare_threshold=None,
                             options="-c lock_timeout=10s -c statement_timeout=60s") as conn:
            while True:
                with lock:
                    k = next(next_op, None)
                if k is None:
                    return
                kind, params = plan[k]
                t0 = time.perf_counter()
                try:
                    if kind == "Q2":
                        allocate(conn, params, allocation, api_ms)
                    else:
                        conn.execute(QUERIES[kind], params).fetchall()
                except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled):
                    errors[kind] += 1
                with lock:
                    elapsed[kind].append((time.perf_counter() - t0) * 1000)

    start = time.perf_counter()
    workers = [threading.Thread(target=worker) for _ in range(threads)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    wall = time.perf_counter() - start

    if not quiet:
        print(f"workload: 操作 {ops} 回 / 同時接続 {threads} / 在庫引き当て = {allocation} / 決済 API {api_ms} ms")
        print(f"経過時間: {wall:.1f} 秒（1 秒あたり {ops / wall:.1f} 操作）")
        print("     画面の操作            回数   平均 ms   最大 ms  エラー")
        for kind, name in NAMES.items():
            times = elapsed[kind]
            mean = sum(times) / len(times) if times else 0.0
            label = name + " " * (20 - 2 * len(name))   # 全角 1 文字を 2 桁として揃える
            print(f"{kind:<5}{label}{len(times):>6}{mean:>10.1f}{max(times, default=0):>10.1f}{errors[kind]:>8}")
        print("（時間はアプリ側で測った 1 操作の時間。Q2 は決済 API の待ちを含む）")
    return {"wall": wall, "elapsed": elapsed, "errors": errors}


def main() -> None:
    ap = argparse.ArgumentParser(description="注文管理画面の負荷を再現する")
    ap.add_argument("--ops", type=int, default=1000, help="操作の回数（既定 1000）")
    ap.add_argument("--threads", type=int, default=4, help="同時接続数（既定 4）")
    ap.add_argument("--allocation", choices=("long", "short"), default="long",
                    help="在庫引き当ての書き方。long = 改善前（既定）、short = 改善後")
    ap.add_argument("--api-ms", type=int, default=50, help="決済 API の応答時間（ミリ秒。既定 50）")
    ap.add_argument("--no-reset", action="store_true", help="pg_stat_statements をリセットしない")
    args = ap.parse_args()
    run(args.ops, args.threads, args.allocation, args.api_ms, reset=not args.no_reset)


if __name__ == "__main__":
    main()
