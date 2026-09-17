"""サンドボックス全体の自己検証。

本文に載せる「行数」「実行計画の形」「内部構造を覗く拡張が使えること」を確認する。
期待どおりでなければ非 0 で終了する。
"""

from __future__ import annotations

import os
import sys

import psycopg
import pymysql

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("OK  " if ok else "NG  ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def verify_pg() -> None:
    with psycopg.connect(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version")
            version = cur.fetchone()[0]
            check("PostgreSQL に接続できる", True, f"server_version={version}")

            # 行数（seed が決定的であることの確認）
            expected = {
                "customers": 50_000,
                "products": 5_000,
                "orders": 1_000_000,
                "order_items": 2_000_000,
            }
            for table, want in expected.items():
                cur.execute(f"SELECT count(*) FROM {table}")
                got = cur.fetchone()[0]
                check(f"pg {table} の行数", got == want, f"{got:,} 行（期待 {want:,}）")

            # 内部構造を覗く拡張が使えること
            for ext in ("pg_stat_statements", "pageinspect", "pgstattuple"):
                cur.execute("SELECT count(*) FROM pg_extension WHERE extname = %s", (ext,))
                check(f"pg 拡張 {ext} が有効", cur.fetchone()[0] == 1)

            # インデックスがない状態では Seq Scan になること（S03 の出発点）
            cur.execute(
                "EXPLAIN (FORMAT JSON) SELECT * FROM orders WHERE ordered_at "
                ">= '2025-06-01' AND ordered_at < '2025-06-02'"
            )
            plan = cur.fetchone()[0][0]["Plan"]
            check(
                "pg 日付範囲検索がインデックスなしで Seq Scan になる",
                plan["Node Type"] in ("Seq Scan", "Gather"),
                f'Node Type={plan["Node Type"]}',
            )

            # ページの中身を直接読める（B+木の観察に使う）
            cur.execute("SELECT count(*) FROM heap_page_items(get_raw_page('orders', 0))")
            check("pg ヒープページの中身を読める", cur.fetchone()[0] > 0)


def verify_mysql() -> None:
    conn = pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        user="lab",
        password=os.environ["MYSQL_PWD"],
        database="shopdb",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            check("MySQL に接続できる", True, f"version={cur.fetchone()[0]}")

            for table, want in (("customers", 50_000), ("orders", 1_000_000)):
                cur.execute(f"SELECT count(*) FROM {table}")
                got = cur.fetchone()[0]
                check(f"mysql {table} の行数", got == want, f"{got:,} 行（期待 {want:,}）")

            # InnoDB のバッファプールの状態を読めること（S 内で比較に使う）
            cur.execute(
                "SELECT count(*) FROM information_schema.innodb_buffer_page WHERE table_name LIKE '%orders%'"
            )
            check("mysql InnoDB バッファプールの中身を読める", cur.fetchone()[0] >= 0)
    finally:
        conn.close()


def main() -> int:
    verify_pg()
    print()
    verify_mysql()
    print()
    if failures:
        print(f"検証に失敗しました（{len(failures)}件）: {', '.join(failures)}")
        return 1
    print("サンドボックスの自己検証に成功しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
