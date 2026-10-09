"""練習問題4の解答：モデルとデータベースのずれ（マイグレーションの書き忘れ）を検出する。"""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column, MetaData, String
from sqlalchemy.engine import Connection

from kondate.db import engine

from .models import SCHEMA, Base


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    return name == SCHEMA if type_ == "schema" else True  # env.py と同じ絞り込み


def _compare(conn: Connection, metadata: MetaData) -> list:
    mc = MigrationContext.configure(conn, opts={
        "include_schemas": True, "include_name": include_name, "version_table_schema": SCHEMA})
    return compare_metadata(mc, metadata)


def describe(diff: tuple | list) -> str:
    if isinstance(diff, list):  # 列の型や NULL 可否の変更は [("modify_type", schema, table, column, …)] の形
        op, schema, table, column = diff[0][:4]
        return f"{op} {schema}.{table}.{column}"
    op = diff[0]
    if op in ("add_column", "remove_column"):
        return f"{op} {diff[1]}.{diff[2]}.{diff[3].name}"
    if op in ("add_table", "remove_table"):
        return f"{op} {diff[1].fullname}"
    if op in ("add_index", "remove_index"):
        return f"{op} {diff[1].name}"
    return op


async def pending_changes(metadata: MetaData = Base.metadata) -> list[str]:
    """metadata を正として、DB に足りない・余っているものを1行ずつの文字列で返す（空ならずれなし）。"""
    async with engine.connect() as conn:
        diffs = await conn.run_sync(_compare, metadata)
    return [describe(d) for d in diffs]


def with_extra_column() -> MetaData:
    """モデルに列を足したのにマイグレーションを書き忘れた状態を、本物のモデルを汚さずに作る。"""
    md = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(md)
    md.tables[f"{SCHEMA}.messages"].append_column(Column("stop_reason", String(32), nullable=True))
    return md
