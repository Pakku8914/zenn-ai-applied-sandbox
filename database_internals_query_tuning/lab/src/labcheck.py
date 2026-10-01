"""章ごとの verify スクリプトが共通で使う道具。

- 接続先は環境変数で決まる（PostgreSQL は PG* 変数、MySQL は MYSQL_HOST / MYSQL_PWD / MYSQL_DATABASE）
- 実行計画は EXPLAIN (FORMAT JSON) で取り、ノードの種類と実測の行数で判定する
  （見積もりの rows は ANALYZE のサンプリングで揺れ、実行時間は環境で変わるため、判定に使わない）
- check() で結果を積み、最後に finish() を呼ぶと、1 つでも NG があれば非 0 で終了する
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from typing import Any

import psycopg
import pymysql

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(("OK  " if ok else "NG  ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        _failures.append(name)
    return ok


def finish(title: str) -> None:
    if _failures:
        print(f"\n{title}: {len(_failures)} 件の検証に失敗しました。")
        for name in _failures:
            print(f"  - {name}")
        sys.exit(1)
    print(f"\n{title}: すべての検証に成功しました。")


def pg_connect(autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(autocommit=autocommit)


def mysql_connect() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        user="lab",
        password=os.environ["MYSQL_PWD"],
        database=os.environ.get("MYSQL_DATABASE", "shopdb"),
        autocommit=True,
    )


def explain(cur: psycopg.Cursor, sql: str, params: Any = None, *,
            analyze: bool = True, buffers: bool = False) -> dict:
    """EXPLAIN の JSON を返す。戻り値の ["Plan"] が計画木の根。"""
    options = ["FORMAT JSON"]
    if analyze:
        options.append("ANALYZE")
    if buffers:
        options.append("BUFFERS")
    cur.execute(f"EXPLAIN ({', '.join(options)}) {sql}", params)
    return cur.fetchone()[0][0]


def walk(plan: dict) -> Iterator[dict]:
    """計画木のノードを根から順にたどる。"""
    yield plan
    for child in plan.get("Plans", []):
        yield from walk(child)


def node_types(result_or_plan: dict) -> list[str]:
    plan = result_or_plan.get("Plan", result_or_plan)
    return [n["Node Type"] for n in walk(plan)]


def find_nodes(result_or_plan: dict, node_type: str) -> list[dict]:
    plan = result_or_plan.get("Plan", result_or_plan)
    return [n for n in walk(plan) if n["Node Type"] == node_type]


def actual_total_rows(node: dict) -> float:
    """ノードが実際に返した行数の合計（PostgreSQL 18 の actual rows は loops あたりの平均）。"""
    return node["Actual Rows"] * node["Actual Loops"]
