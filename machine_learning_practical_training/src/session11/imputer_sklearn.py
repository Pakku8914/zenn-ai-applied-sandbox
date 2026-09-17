"""scikit-learn の SimpleImputer ― fit で「埋める値」を覚え、transform で当てはめる。

使い方:
    docker compose exec lab python src/session11/imputer_sklearn.py
"""

from __future__ import annotations

from sklearn.impute import SimpleImputer

from common import load_customers, load_reviews

# strategy と、それに必要な追加の引数。constant のときだけ fill_value を渡す
STRATEGIES = [
    ("mean", {}),
    ("median", {}),
    ("most_frequent", {}),
    ("constant", {"fill_value": 0.0}),
]


def main() -> None:
    reviews = load_reviews()
    # 2 次元（DataFrame）で渡す。reviews["rating"] のような 1 次元の Series はエラーになる
    X = reviews[["rating"]]

    print("■ strategy ごとに「覚える値」を見る")
    for strategy, kwargs in STRATEGIES:
        imputer = SimpleImputer(strategy=strategy, **kwargs).fit(X)
        print(f"  strategy={strategy:<13} statistics_ = {float(imputer.statistics_[0]):.4f}")

    print("■ add_indicator=True で欠損フラグを残す")
    flagged = SimpleImputer(strategy="mean", add_indicator=True).set_output(transform="pandas")
    result = flagged.fit_transform(X)
    print(f"  出力の列: {list(result.columns)}")
    print(f"  フラグが 1 の行: {int(result['missingindicator_rating'].sum()):,} 件")
    print(f"  代入後の標準偏差: {result['rating'].std(ddof=1):.4f}")

    print("■ 文字列の列（region）は most_frequent か constant を使う")
    customers = load_customers()
    region_imputer = SimpleImputer(strategy="most_frequent", add_indicator=True).set_output(
        transform="pandas"
    )
    filled = region_imputer.fit_transform(customers[["region"]])
    print(f"  statistics_ = {region_imputer.statistics_[0]}")
    print(f"  代入後の東京: {int((filled['region'] == '東京').sum()):,} 人")
    print(f"  フラグが 1 の行: {int(filled['missingindicator_region'].sum()):,} 件")


if __name__ == "__main__":
    main()
