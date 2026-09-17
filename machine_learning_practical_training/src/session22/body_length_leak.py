"""body_length は「原因」ではなく「結果」である（本文 6 節）。

レビュー本文の長さは、レビューを書き終えたあとにしか分かりません。
「投稿される前に高評価かを当てる」用途では使えない列です。

実行:
    docker compose exec lab python src/session22/body_length_leak.py
"""

from __future__ import annotations

from common import holdout_auc, load_review_table

# 「投稿される前」に分かっている列だけを残す（body_length を落とす）
BEFORE_POSTING = ["unit_price", "pages", "published_year"]


def compare(df) -> dict[str, float]:
    """body_length を入れた場合と外した場合の ROC AUC を測る。"""
    with_length = holdout_auc(df)                          # 数値 4 列 + category
    without_length = holdout_auc(df, numeric=BEFORE_POSTING)  # 数値 3 列 + category
    return {
        "with_length": with_length,
        "without_length": without_length,
        "gap": without_length - with_length,
        "corr": float(df["body_length"].corr(df["rating"])),
    }


def main() -> None:
    df = load_review_table()
    result = compare(df)

    print(f"body_length と rating の相関                        : {result['corr']:+.4f}")
    print(f"① body_length を含む 5 特徴量の ROC AUC            : {result['with_length']:.4f}")
    print(f"② body_length を外した 4 特徴量の ROC AUC          : {result['without_length']:.4f}")
    print(f"③ ② − ①（正直にすると落ちる分）                   : {result['gap']:+.4f}")
    print(f"④ ② は当て推量 0.5 を上回っているか                : {result['without_length'] > 0.5}")
    print()
    print("①は「レビューを読んだあとで、そのレビューが高評価かを言い当てる」性能です。")
    print("②が「投稿される前に高評価かを予測する」性能で、報告してよいのはこちらです。")


if __name__ == "__main__":
    main()
