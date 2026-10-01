"""MySQL 側を出発点（主キーと外部キー用のインデックスのみ）に戻す。データには触れない。

使い方: docker compose exec lab python tools/reset_mysql.py
"""

from __future__ import annotations

import os

import pymysql

BASE_TABLES = ("customers", "products", "orders", "order_items")
# 外部キー制約のために InnoDB が自動で作ったインデックス（表, インデックス名, 列）。消すと制約が成り立たないので残す
FK_INDEXES = (
    ("orders", "fk_orders_customer", "customer_id"),
    ("order_items", "fk_items_order", "order_id"),
    ("order_items", "fk_items_product", "product_id"),
)
KEEP = {"PRIMARY"} | {name for _, name, _ in FK_INDEXES}

conn = pymysql.connect(
    host=os.environ["MYSQL_HOST"],
    user="lab",
    password=os.environ["MYSQL_PWD"],
    database=os.environ.get("MYSQL_DATABASE", "shopdb"),
    autocommit=True,
)
with conn.cursor() as cur:
    # 外部キー列から始まるインデックスを章で作ると、InnoDB は外部キー用のインデックスを黙って削除する。
    # そのままでは章のインデックスが「外部キーに必要」になって消せない（ERROR 1553）ので、先に作り直す
    for table, name, column in FK_INDEXES:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
            (table, name),
        )
        if cur.fetchone()[0] == 0:
            cur.execute(f"ALTER TABLE `{table}` ADD INDEX `{name}` (`{column}`)")

    cur.execute(
        "SELECT DISTINCT table_name, index_name FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name IN (%s, %s, %s, %s)",
        BASE_TABLES,
    )
    for table, index in cur.fetchall():
        if index not in KEEP:
            cur.execute(f"ALTER TABLE `{table}` DROP INDEX `{index}`")

    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name NOT IN (%s, %s, %s, %s)",
        BASE_TABLES,
    )
    for (table,) in cur.fetchall():
        cur.execute(f"DROP TABLE IF EXISTS `{table}`")

    # ANALYZE TABLE ... UPDATE HISTOGRAM で作ったヒストグラムを消す
    cur.execute(
        "SELECT table_name, column_name FROM information_schema.column_statistics "
        "WHERE schema_name = DATABASE()"
    )
    for table, column in cur.fetchall():
        cur.execute(f"ANALYZE TABLE `{table}` DROP HISTOGRAM ON `{column}`")
        cur.fetchall()

    for table in BASE_TABLES:
        cur.execute(f"ANALYZE TABLE `{table}`")
        cur.fetchall()
conn.close()
