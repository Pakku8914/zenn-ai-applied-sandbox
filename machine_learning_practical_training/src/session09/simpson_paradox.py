"""ページ数と星の関係が、価格を一緒に見ると符号を変えることを確かめる。

回帰はここでは「相関の落とし穴を見せる道具」として使うだけです。
回帰そのものの理論はセッション16で扱います。

使い方:
    docker compose exec lab python src/session09/simpson_paradox.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import statsmodels.api as sm

from common import OUT_DIR, PRICE_BANDS, load_rated_reviews, pad_ja


def main() -> None:
    reviews = load_rated_reviews()

    # 1. ページ数だけで星を説明する（単回帰）
    single = sm.OLS(reviews["rating"], sm.add_constant(reviews[["pages"]])).fit()
    # 2. 価格も一緒に入れる（重回帰）。pages の係数は「価格を揃えたときの傾き」になる
    both = sm.OLS(reviews["rating"], sm.add_constant(reviews[["pages", "price"]])).fit()

    print("■ 星をページ数だけで説明する（単回帰）")
    print(f"pages の係数 : {single.params['pages']:+.6f}  (p = {single.pvalues['pages']:.2e})")
    print(f"決定係数 R2  : {single.rsquared:.4f}")

    print("\n■ 価格を一緒に入れる（重回帰）")
    print(f"pages の係数 : {both.params['pages']:+.6f}  (p = {both.pvalues['pages']:.2e})")
    print(f"決定係数 R2  : {both.rsquared:.4f}")
    print(f"price の係数の符号 : {'マイナス' if both.params['price'] < 0 else 'プラス'}")
    print(f"ページ数 と 価格 の相関 : {reviews['pages'].corr(reviews['price']):+.4f}")

    # 3. 価格を 4 等分して、同じ価格帯の中だけで比べる
    banded = reviews.assign(price_band=pd.qcut(reviews["price"], 4, labels=PRICE_BANDS))
    print("\n■ 価格の 4 分位ごとの平均")
    for band in PRICE_BANDS:
        group = banded.loc[banded["price_band"] == band]
        print(
            f"{band} : {len(group):>5,} 件 / 平均の星 {group['rating'].mean():.4f}"
            f" / 平均ページ数 {group['pages'].mean():>5.1f}"
        )

    # 4. カテゴリごとに見る（層別）。全体の相関がどこから来ていたのかを確かめる
    rows = []
    for category, group in reviews.groupby("category"):
        rows.append(
            {
                "category": category,
                "n": len(group),
                "mean_rating": group["rating"].mean(),
                "mean_price": group["price"].mean(),
                "corr_pages_rating": group["pages"].corr(group["rating"]),
            }
        )
    by_category = pd.DataFrame(rows).sort_values("mean_price", ascending=False)

    print("\n■ カテゴリごとに見る（件数 / 平均の星 / 平均価格 / ページ数と星の相関）")
    for row in by_category.itertuples():
        print(
            f"{pad_ja(row.category, 8)} : {row.n:>5,} 件 / {row.mean_rating:.4f}"
            f" / {row.mean_price:>7,.1f} 円 / {row.corr_pages_rating:+.4f}"
        )

    # 5. 図にする。pages の係数の符号が反転することを 1 枚で見せる
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    ax.bar(
        ["ページ数だけ", "価格も一緒に"],
        [single.params["pages"], both.params["pages"]],
        color=["#d62728", "#4c78a8"],
    )
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_ylabel("pages の係数")
    ax.set_title("同じデータなのに pages の係数の符号が反転する")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "s09_simpson.png", dpi=110)
    plt.close(fig)
    print("\n図を保存しました: outputs/s09_simpson.png")


if __name__ == "__main__":
    main()
