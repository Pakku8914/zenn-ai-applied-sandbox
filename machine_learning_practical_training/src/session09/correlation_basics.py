"""相関係数を計算し、星と関係のありそうな列・情報が重なっている列を見つける。

使い方:
    docker compose exec lab python src/session09/correlation_basics.py
"""

from __future__ import annotations

from common import load_rated_reviews, load_valid_orders

NUMERIC_COLS = ["rating", "body_length", "price", "pages", "published_year"]


def main() -> None:
    reviews = load_rated_reviews()
    corr = reviews[NUMERIC_COLS].corr()  # 既定はピアソンの相関係数

    print("■ 星（rating）との相関係数（ピアソン・14,169 件）")
    print(f"本文の長さ と 星 : {corr.loc['rating', 'body_length']:+.4f}")
    print(f"価格      と 星 : {corr.loc['rating', 'price']:+.4f}")
    print(f"ページ数  と 星 : {corr.loc['rating', 'pages']:+.4f}")
    print(f"刊行年    と 星 : {corr.loc['rating', 'published_year']:+.4f}")

    print("\n■ 特徴量どうしの相関（説明が重なっていないかを見る）")
    print(f"ページ数  と 価格 : {corr.loc['pages', 'price']:+.4f}")

    print("\n■ 順位で測り直す（本文の長さ と 星）")
    print(f"ピアソン   : {reviews['body_length'].corr(reviews['rating']):+.4f}")
    print(f"スピアマン : {reviews['body_length'].corr(reviews['rating'], method='spearman'):+.4f}")

    # 売上額は冊数を掛けて作った列なので、相関があるのは当たり前（定義の重なり）
    valid = load_valid_orders()
    print("\n■ 定義が重なっている 2 列（有効注文 57,869 件）")
    print(f"冊数 と 売上額 : {valid['quantity'].corr(valid['amount']):+.4f}")

    # 数値でない列（category）を混ぜたまま corr() を呼ぶとどうなるか
    print("\n■ 文字列の列を混ぜて corr() を呼ぶと")
    try:
        reviews[NUMERIC_COLS + ["category"]].corr()
        print("例外は起きませんでした")
    except Exception:  # noqa: BLE001 - 例外の型を決め打ちしない（環境差で変わりうる）
        print("数値でない列が混ざっているため、例外で止まりました")


if __name__ == "__main__":
    main()
