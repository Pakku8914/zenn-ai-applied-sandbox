"""実装問題 10：セッション 5 〜 9 を横断して 1 枚のミニレポートを作る。

使い方:
    docker compose exec lab python src/review01/q10_mini_report.py
"""

from __future__ import annotations

import matplotlib.pyplot as plt

from common import load_books, load_customers, load_valid_orders, save_fig, yen


def main() -> None:
    valid = load_valid_orders()
    books = load_books()
    customers = load_customers()
    total = float(valid["revenue"].sum())

    # 月次（月末ラベル）。端の 2 か月は期間が欠けている（セッション 7）
    monthly = valid.set_index("ordered_at")["revenue"].sort_index().resample("ME").sum()
    full = monthly.iloc[1:-1]
    last_days = int(valid.loc[valid["ordered_at"] >= "2026-09-01", "ordered_at"].dt.normalize().nunique())

    by_category = (
        valid.merge(books[["book_id", "category"]], on="book_id", how="left", validate="many_to_one")
        .groupby("category")["revenue"]
        .sum()
        .sort_values()
    )
    joined = valid.merge(
        customers[["customer_id", "region"]], on="customer_id", how="left", validate="many_to_one"
    )
    dropped = float(joined.loc[joined["region"].isna(), "revenue"].sum())

    print(f"母集団: 有効注文 {len(valid):,} 件 / 売上 {yen(total)}（重複とキャンセルを除外）")
    print("■ 所見 1：伸びているが、端の月は読まない")
    print(f"  月次の箱: {len(monthly)} か月（期間がそろっているのは {len(full)} か月）")
    print(f"  最大 {monthly.idxmax():%Y-%m}: {yen(monthly.max())}")
    print(f"  先頭 {monthly.index[0]:%Y-%m}: {yen(monthly.iloc[0])}（この月は 9 日から始まる）")
    print(f"  末尾 {monthly.index[-1]:%Y-%m}: {yen(monthly.iloc[-1])}（{last_days} 日分しかない）")
    print("  → 末尾の下がり方を「急落」と読んではいけない")

    print("■ 所見 2：内訳の合計は総額と一致しない")
    for category, revenue in by_category.sort_values(ascending=False).items():
        print(f"    {category}: {yen(revenue)}")
    breakdown = sum(round(float(v)) for v in by_category)
    print(f"  総額 {yen(total)} / 丸めた内訳の合計 {breakdown:,} 円（差 {breakdown - round(total):+,} 円）")
    print("  → 内訳の合計を総額として使わない")

    print("■ 所見 3：地域別集計に現れない売上がある")
    print(f"  region が未入力の顧客の売上: {yen(dropped)}")
    print("  → この分は地域別の表のどのセルにも入らない。表の合計を総額として使わない")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    line, bar = axes

    line.plot(
        full.index,
        full.to_numpy() / 1e6,
        marker="o",
        color="#4c78a8",
        label=f"期間がそろった {len(full)} か月",
    )
    ends = monthly.iloc[[0, -1]]
    line.plot(
        ends.index,
        ends.to_numpy() / 1e6,
        marker="x",
        markersize=10,
        linestyle="none",
        color="#e45756",
        label="端の月（期間が欠けている）",
    )
    line.set_title("月次売上の推移")
    line.set_xlabel("年月")
    line.set_ylabel("売上（百万円）")
    line.legend(loc="upper left")
    line.tick_params(axis="x", rotation=45)

    bars = bar.barh(by_category.index.tolist(), by_category.to_numpy() / 1e6, color="#4c78a8")
    bar.bar_label(bars, labels=[yen(v) for v in by_category], padding=4)
    bar.set_xlim(0, 78)
    bar.set_title("カテゴリ別の売上")
    bar.set_xlabel("売上（百万円）")

    fig.suptitle(f"有効注文 {len(valid):,} 件・売上 {yen(total)} の読み方")
    save_fig(fig, "review01_mini_report.png")


if __name__ == "__main__":
    main()
