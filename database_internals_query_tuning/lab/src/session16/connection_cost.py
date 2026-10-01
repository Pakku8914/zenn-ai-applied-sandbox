"""S16 接続を確立するコスト：「毎回接続して1クエリ」と「1接続を使い回す」を比べる。

使い方: docker compose exec lab python src/session16/connection_cost.py
同じ 200 回の SELECT を、(A) 毎回 connect → 1クエリ → close と、(B) 1本の接続を使い回して実行し、
交互に5回ずつ測って中央値を出す。時間は環境によって変わるので、倍率で読む。
"""

from __future__ import annotations

import statistics
import time

import psycopg

N = 200
ROUNDS = 5
QUERY = "SELECT count(*) FROM customers WHERE id = %s"


def connect_each_time() -> float:
    start = time.perf_counter()
    for i in range(N):
        with psycopg.connect(prepare_threshold=None) as conn:
            conn.execute(QUERY, (i + 1,)).fetchone()
    return (time.perf_counter() - start) * 1000


def reuse_one_connection() -> float:
    start = time.perf_counter()
    with psycopg.connect(prepare_threshold=None) as conn:
        for i in range(N):
            conn.execute(QUERY, (i + 1,)).fetchone()
    return (time.perf_counter() - start) * 1000


def main() -> None:
    each, reuse = [], []
    for _ in range(ROUNDS):
        each.append(connect_each_time())
        reuse.append(reuse_one_connection())
    a, b = statistics.median(each), statistics.median(reuse)
    print(f"(A) 毎回接続して1クエリ × {N} 回: 中央値 {a:.1f} ms  （1回あたり {a / N:.2f} ms）")
    print(f"(B) 1接続を使い回して {N} 回     : 中央値 {b:.1f} ms  （1回あたり {b / N:.3f} ms）")
    print(f"(A) / (B) = 約 {a / b:.0f} 倍")


if __name__ == "__main__":
    main()
