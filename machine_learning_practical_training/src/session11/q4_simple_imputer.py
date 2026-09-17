"""問題4: SimpleImputer の 4 つの strategy と欠損フラグを比べる。

使い方:
    docker compose exec lab python src/session11/q4_simple_imputer.py
"""

from __future__ import annotations

from sklearn.impute import SimpleImputer

from common import load_reviews

STRATEGIES = [("mean", {}), ("median", {}), ("most_frequent", {}), ("constant", {"fill_value": 0.0})]


def main() -> None:
    reviews = load_reviews()
    X = reviews[["rating"]]  # 2 次元で渡す（Series を渡すとエラーになる）
    observed = reviews["rating"].dropna()
    print(f"■ 欠損を落とした場合: 件数 {len(observed):,} / 平均 {observed.mean():.4f}"
          f" / 標準偏差 {observed.std(ddof=1):.4f}")

    print("■ strategy ごとに覚えた値（statistics_）")
    for strategy, kwargs in STRATEGIES:
        imputer = SimpleImputer(strategy=strategy, **kwargs).fit(X)
        print(f"  {strategy}: {float(imputer.statistics_[0]):.4f}")

    # 平均代入はばらつきを縮める（平均からのずれが 0 の行が増えるため）
    mean_filled = SimpleImputer(strategy="mean").set_output(transform="pandas").fit_transform(X)["rating"]
    print(f"■ 平均で埋めた場合: 件数 {len(mean_filled):,} / 平均 {mean_filled.mean():.4f}"
          f" / 標準偏差 {mean_filled.std(ddof=1):.4f}（縮む）")

    # 最頻値代入は「最頻値の棒」だけを高くする
    mode_filled = SimpleImputer(strategy="most_frequent").set_output(transform="pandas").fit_transform(X)["rating"]
    before = int((observed == 4.0).sum())
    after = int((mode_filled == 4.0).sum())
    print(f"■ 最頻値で埋めた場合: 星 4 が {before:,} 件 → {after:,} 件")

    flagged = SimpleImputer(strategy="mean", add_indicator=True).set_output(transform="pandas")
    result = flagged.fit_transform(X)
    print(f"■ add_indicator=True の出力列: {list(result.columns)}")
    print(f"  フラグが 1 の行: {int(result['missingindicator_rating'].sum()):,} 件"
          f" / 欠損が残った行: {int(result['rating'].isna().sum())} 件")


if __name__ == "__main__":
    main()
