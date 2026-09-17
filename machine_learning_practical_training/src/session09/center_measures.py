"""平均・中央値・最頻値を並べ、歪んだ分布で何が起きるかを確かめる。

使い方:
    docker compose exec lab python src/session09/center_measures.py
"""

from __future__ import annotations

from common import load_orders, load_rated_reviews


def main() -> None:
    quantity = load_orders()["quantity"]
    rating = load_rated_reviews()["rating"]

    print("■ quantity（1 注文あたりの冊数・重複を落とした 60,031 行）")
    print(f"平均       : {quantity.mean():.4f}")
    print(f"中央値     : {quantity.median():.1f}")
    print(f"最頻値     : {int(quantity.mode().iloc[0])}")
    print(f"最小 / 最大: {int(quantity.min())} / {int(quantity.max())}")
    print(f"4 〜 14 冊の注文 : {int(quantity.between(4, 14).sum())} 行")
    print(f"15 冊以上の注文  : {int((quantity >= 15).sum())} 行")

    print("\n■ rating（星が入っているレビュー・14,169 件）")
    print(f"平均       : {rating.mean():.4f}")
    print(f"中央値     : {rating.median():.1f}")
    print(f"最頻値     : {int(rating.mode().iloc[0])}")
    print(f"最小 / 最大: {int(rating.min())} / {int(rating.max())}")

    print("\n■ 平均 − 中央値（正なら右に裾が伸びている）")
    print(f"quantity : {quantity.mean() - quantity.median():+.4f}")
    print(f"rating   : {rating.mean() - rating.median():+.4f}")


if __name__ == "__main__":
    main()
