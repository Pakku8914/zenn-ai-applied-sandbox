"""リークを見つけるためのチェックリストと、高評価予測への当てはめ（本文 7 節）。

モデルを学習しません。**表の形とコードの手順だけを見て**危ないところを洗い出す、
という使い方を練習するためのスクリプトです。

実行:
    docker compose exec lab python src/session22/leak_checklist.py
"""

from __future__ import annotations

import pandas as pd

from common import load_review_table

# 7 つの問い。どれも「はい / いいえ」で答えられる形にしてある
CHECKLIST: list[tuple[str, str]] = [
    ("Q1", "目的変数そのもの、またはその言い換えになっている列はないか"),
    ("Q2", "予測したい時点では、まだ値が決まっていない列はないか"),
    ("Q3", "同じ人・同じ商品の行が、訓練データと評価データの両方に入っていないか"),
    ("Q4", "前処理（標準化・欠損補完・エンコーディング・特徴量選択）を分割の前にやっていないか"),
    ("Q5", "集約した特徴量は、その行より前のデータだけで作っているか"),
    ("Q6", "評価データの期間は、訓練データより後になっているか"),
    ("Q7", "ベースラインからの上がり幅が、不自然に大きくないか"),
]

# 「予測したい時点ではまだ存在しない」列。この表では本文の長さがそれに当たる
RESULT_COLUMNS = ["body_length"]


def audit(df: pd.DataFrame) -> dict[str, object]:
    """高評価予測の表を、チェックリストの観点から点検して事実だけを返す。"""
    counts = df["customer_id"].value_counts()
    return {
        "rows": len(df),
        "customers": int(counts.size),
        "max_per_customer": int(counts.max()),
        "customer_appears_twice": bool(counts.max() > 1),
        # レビューを書き終えたあとにしか分からない列（＝原因ではなく結果）
        "result_columns": [column for column in RESULT_COLUMNS if column in df.columns],
        "positive_rate": float(df["is_high"].mean()),
    }


def findings(facts: dict[str, object]) -> list[tuple[str, str, str]]:
    """チェックリストの各問いに、このモデルでの答えと対応を並べる。"""
    return [
        ("Q1", "いいえ", "rating は目的変数を作るためだけに使い、特徴量には入れていない"),
        ("Q2", "はい", f"body_length は投稿後にしか決まらない（結果の列: {facts['result_columns']}）"),
        (
            "Q3",
            "はい",
            f"顧客 {facts['customers']} 人でレビュー {facts['rows']} 件。"
            f"1 人が最大 {facts['max_per_customer']} 件書いている",
        ),
        ("Q4", "いいえ", "前処理は Pipeline に載せてあるので fold ごとに閉じている"),
        ("Q5", "該当なし", "この表には過去を集約した特徴量が無い"),
        ("Q6", "いいえ", "shuffle した分割なので未来のレビューで学習している。時系列分割でも確認した"),
        ("Q7", "いいえ", f"正例率 {facts['positive_rate']:.4f} に対して AUC 0.82 台。跳ね上がりは無い"),
    ]


def main() -> None:
    facts = audit(load_review_table())

    print("■ リーク点検チェックリスト")
    for key, question in CHECKLIST:
        print(f"{key}. {question}")
    print()

    print("■ 高評価予測（このセッションのモデル）に当てはめた結果")
    print("問い | 答え     | 根拠")
    for key, answer, reason in findings(facts):
        print(f"{key}   | {answer:<8} | {reason}")
    print()
    print("「はい」が付いた Q2 と Q3 が、この章で実際に手を動かして確かめた 2 点です。")


if __name__ == "__main__":
    main()
