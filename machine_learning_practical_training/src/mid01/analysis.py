"""中間プロジェクト①の集計。図とレポートがどちらもこの関数群を呼ぶ。

集計と作図・報告を分けておくと、「図の中の数字」と「レポートの数字」が食い違う
事故が起きません（両者が別のコードで集計されていると必ずどこかでずれます）。
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from common import (
    AGE_BASE_YEAR,
    AGE_BINS,
    AGE_LABELS,
    CATEGORY_ORDER,
    REFERENCE_DATE,
    load_books,
    load_customers,
    load_orders,
    load_valid_orders,
)


@lru_cache(maxsize=1)
def base_table() -> pd.DataFrame:
    """有効注文 57,869 件に、カテゴリ・年代・流入経路・地域を付けた 1 枚の表を返す。

    読み込みと結合は 1 回だけ行う（lru_cache）。返り値は使い回されるので、
    呼び出した側で列を足したり値を書き換えたりしないこと（必要なら .copy() を取る）。
    """
    df = load_valid_orders().merge(
        load_books()[["book_id", "category", "price"]],
        on="book_id",
        how="left",
        validate="many_to_one",  # 結合で行が増えないことを宣言しておく（セッション 5）
    ).merge(
        load_customers()[["customer_id", "birth_year", "region", "channel"]],
        on="customer_id",
        how="left",
        validate="many_to_one",
    )
    df["age"] = AGE_BASE_YEAR - df["birth_year"]
    df["年代"] = pd.cut(df["age"], bins=AGE_BINS, labels=AGE_LABELS)
    return df


def population() -> dict[str, float]:
    """母集団の確定に使う件数と人数。レポートの先頭に必ず書く数値。"""
    raw = load_orders(dedupe=False)
    unique = raw.drop_duplicates()
    valid = load_valid_orders()
    recency = (REFERENCE_DATE - valid.groupby("customer_id")["ordered_at"].max()).dt.days
    return {
        "raw_orders": len(raw),
        "unique_orders": len(unique),
        "valid_orders": len(valid),
        "total_revenue": float(valid["revenue"].sum()),
        "all_customers": len(load_customers()),
        "ordered_customers": int(unique["customer_id"].nunique()),
        "valid_customers": int(valid["customer_id"].nunique()),
        "active_customers": int((recency <= 90).sum()),
    }


def category_summary() -> pd.DataFrame:
    """カテゴリ別の売上・注文数・1 注文あたり平均金額と、マスタ側の平均価格。"""
    summary = (
        base_table()
        .groupby("category", observed=True)
        .agg(
            revenue=("revenue", "sum"),
            orders=("order_id", "count"),
            mean_amount=("revenue", "mean"),
        )
    )
    # 平均価格は「売れた注文」ではなく書籍マスタ側で数える（セッション 6）
    summary["mean_price"] = load_books().groupby("category")["price"].mean()
    return summary.loc[CATEGORY_ORDER]


def cross_revenue(index: str) -> pd.DataFrame:
    """index（"年代" または "channel"）× カテゴリの売上（丸めない値）。"""
    table = base_table().pivot_table(
        index=index, columns="category", values="revenue", aggfunc="sum", observed=True
    )[CATEGORY_ORDER]
    if index == "年代":
        return table.reindex(AGE_LABELS)  # 年代には大小の順序があるので固定する
    # 流入経路に自然な順序はないので、売上の多い順に並べる
    return table.loc[table.sum(axis=1).sort_values(ascending=False).index]


def age_share() -> pd.DataFrame:
    """年代別のカテゴリ構成比（%）。行（年代）ごとに 100% になる。"""
    table = cross_revenue("年代")
    return table.div(table.sum(axis=1), axis=0) * 100


def age_segment() -> pd.DataFrame:
    """年代ごとの「セグメントの大きさ」。顧客数と、注文 1 件あたりの平均単価。"""
    return (
        base_table()
        .groupby("年代", observed=True)
        .agg(customers=("customer_id", "nunique"), mean_unit_price=("unit_price", "mean"))
        .reindex(AGE_LABELS)
    )


def region_revenue() -> tuple[pd.Series, float]:
    """地域別の売上（多い順）と、region が未入力の顧客の売上を返す。

    未入力の売上は地域別のどの行にも入らない。表の合計を総額として使わないこと。
    """
    df = base_table()
    by_region = df.groupby("region")["revenue"].sum().sort_values(ascending=False)
    missing = float(df.loc[df["region"].isna(), "revenue"].sum())
    return by_region, missing
