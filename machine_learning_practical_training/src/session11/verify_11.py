"""セッション 11 の検証スクリプト。

「セッション11：欠損値 ― 仕組みを見極めて埋める」の本文・練習問題・解答に載せた
数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session11/verify_11.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import KNNImputer, SimpleImputer
from sklearn.model_selection import train_test_split

from common import (
    ALPHA,
    CHANNELS,
    DATA_DIR,
    MISSING_LABEL,
    REGIONS,
    chi2_compare,
    load_customers,
    load_orders,
    load_reviews,
    order_count_per_customer,
    region_missing_revenue,
    welch_compare,
)

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = bool(actual == expected)
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


def check_close(label: str, actual: float, expected: float, tol: float = TOLERANCE) -> None:
    ok = abs(actual - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.4f}")
    if not ok:
        print(f"     期待値: {expected:.4f} ± {tol}")
        failures.append(label)


missing_files = [
    name for name in ("books", "customers", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()
]
if missing_files:
    print(f"NG   データが未生成です: {missing_files}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. 欠損の棚卸し（どこに、どれだけあるか）
# ------------------------------------------------------------------
customers = load_customers()
reviews = load_reviews()
orders = load_orders()

check("customers.csv の行数", len(customers), 8000)
check("customers の列数", customers.shape[1], 5)
check("region の欠損数", int(customers["region"].isna().sum()), 392)
check("customers の欠損は region だけ", int(customers.isna().sum().sum()), 392)
check("region の欠損率（小数第 2 位まで）", f"{customers['region'].isna().mean():.2%}", "4.90%")
check("region の count（欠損を除いた件数）", int(customers["region"].count()), 7608)

check("reviews.csv の行数", len(reviews), 14467)
check("reviews の列数", reviews.shape[1], 7)
check("rating の欠損数", int(reviews["rating"].isna().sum()), 298)
check("reviews の欠損は rating だけ", int(reviews.isna().sum().sum()), 298)
check("rating の欠損率（小数第 2 位まで）", f"{reviews['rating'].isna().mean():.2%}", "2.06%")

check("重複を除いた注文の行数", len(orders), 60031)

# 顧客数の 3 通りの数え方（本書の規約）
check("全顧客", len(customers), 8000)
check("注文が 1 件以上ある顧客", orders["customer_id"].nunique(), 7654)
valid_orders = orders.loc[orders["is_canceled"] == 0]
check("有効注文が 1 件以上ある顧客", valid_orders["customer_id"].nunique(), 7629)

# 結合すると欠損は広がる（顧客 1 人の欠損が、その人のレビュー全行に付く）
analysed = reviews.dropna(subset=["rating"]).merge(
    customers[["customer_id", "region", "channel", "birth_year"]],
    on="customer_id",
    how="left",
    validate="many_to_one",
)
check("rating の欠損を落としたレビューの行数", len(analysed), 14169)
check("14,467 - 298 と一致すること", len(analysed), 14467 - 298)
check("結合後の region の欠損数", int(analysed["region"].isna().sum()), 729)
check("結合後の region の欠損率", f"{analysed['region'].isna().mean():.2%}", "5.15%")
check("結合で欠損が増えること", int(analysed["region"].isna().sum()) > 392, True)

# ------------------------------------------------------------------
# 2. region の欠損が MCAR かどうかの検証
# ------------------------------------------------------------------
customers = customers.assign(order_count=order_count_per_customer(customers, orders).to_numpy())
check("注文回数の合計が 60,031 になること", int(customers["order_count"].sum()), 60031)

missing = customers["region"].isna()
check("欠損群の人数", int(missing.sum()), 392)
check("非欠損群の人数", int((~missing).sum()), 7608)

channel = chi2_compare(customers["channel"], missing)
table = channel["table"][CHANNELS]
ratio = channel["ratio"][CHANNELS]
check("クロス集計表の形", channel["table"].shape, (2, 4))
expected_channel = {
    # チャネル: (欠損群の人数, 欠損群の構成比, 非欠損群の人数, 非欠損群の構成比)
    "検索": (164, 0.4184, 3211, 0.4221),
    "SNS": (115, 0.2934, 2127, 0.2796),
    "メルマガ": (68, 0.1735, 1368, 0.1798),
    "紹介": (45, 0.1148, 902, 0.1186),
}
for name, (n_missing, ratio_missing, n_filled, ratio_filled) in expected_channel.items():
    check(f"{name}（欠損群）の人数", int(table.loc[True, name]), n_missing)
    check(f"{name}（欠損群）の構成比", round(float(ratio.loc[True, name]), 4), ratio_missing)
    check(f"{name}（非欠損群）の人数", int(table.loc[False, name]), n_filled)
    check(f"{name}（非欠損群）の構成比", round(float(ratio.loc[False, name]), 4), ratio_filled)
check("欠損群の合計", int(table.loc[True].sum()), 392)
check("非欠損群の合計", int(table.loc[False].sum()), 7608)
check_close("channel のカイ二乗検定 chi2", channel["chi2"], 0.3932, tol=0.01)
check("channel のカイ二乗検定の自由度", channel["dof"], 3)
check_close("channel のカイ二乗検定 p 値", channel["p"], 0.9416)
check("channel の分布に差が見つからないこと", channel["p"] >= ALPHA, True)

birth = welch_compare(customers["birth_year"], missing)
check("birth_year の欠損群の件数", birth["n_a"], 392)
check("birth_year の非欠損群の件数", birth["n_b"], 7608)
check_close("birth_year の欠損群の平均", birth["mean_a"], 1986.93, tol=0.01)
check_close("birth_year の非欠損群の平均", birth["mean_b"], 1987.51, tol=0.01)
check_close("birth_year の Welch の t 検定 p 値", birth["p"], 0.3504)
check("birth_year の平均に差が見つからないこと", birth["p"] >= ALPHA, True)

order_count = welch_compare(customers["order_count"], missing)
check_close("注文回数の欠損群の平均", order_count["mean_a"], 7.745)
check_close("注文回数の非欠損群の平均", order_count["mean_b"], 7.491)
check_close("注文回数の Welch の t 検定 p 値", order_count["p"], 0.4362)
check("注文回数に差が見つからないこと", order_count["p"] >= ALPHA, True)

# rating の欠損も同じ手順で調べる（欠損フラグが情報を持つかの確認）
body_length = welch_compare(reviews["body_length"], reviews["rating"].isna())
check("body_length の欠損群の件数", body_length["n_a"], 298)
check("body_length の非欠損群の件数", body_length["n_b"], 14169)
check_close("rating 欠損群の body_length の平均", body_length["mean_a"], 80.2, tol=0.05)
check_close("rating 非欠損群の body_length の平均", body_length["mean_b"], 83.7, tol=0.05)
check_close("body_length の Welch の t 検定 p 値", body_length["p"], 0.3076)
check("body_length に差が見つからないこと", body_length["p"] >= ALPHA, True)

# ------------------------------------------------------------------
# 3. region を「削除 / 定数 / 最頻値」で処理した結果
# ------------------------------------------------------------------
mode_value = customers["region"].mode().iloc[0]
check("region の最頻値", str(mode_value), "東京")

deleted = customers.dropna(subset=["region"])
check("削除後の行数", len(deleted), 7608)
check("削除した人数", len(customers) - len(deleted), 392)
check("削除で失われる売上（円）", round(region_missing_revenue(customers, orders)), 6492330)

constant = customers.assign(region=customers["region"].fillna(MISSING_LABEL))
check("定数代入後の行数", len(constant), 8000)
check("代入前のカテゴリ数", customers["region"].nunique(), 7)
check("定数代入後のカテゴリ数", constant["region"].nunique(), 8)
check(f"{MISSING_LABEL} の人数", int((constant["region"] == MISSING_LABEL).sum()), 392)

filled = customers.assign(region=customers["region"].fillna(mode_value))
counts = filled["region"].value_counts().reindex(REGIONS)
expected_regions = {"東京": 3025, "大阪": 1180, "愛知": 895, "福岡": 890, "広島": 692, "宮城": 668, "北海道": 650}
for name, expected_count in expected_regions.items():
    check(f"最頻値代入後の {name}", int(counts.loc[name]), expected_count)
check("最頻値代入後の合計", int(counts.sum()), 8000)
check("代入前の東京", int((deleted["region"] == "東京").sum()), 3025 - 392)
check("東京の構成比（削除・分母 7,608）", f"{(deleted['region'] == '東京').mean():.2%}", "34.61%")
check("東京の構成比（代入後・分母 8,000）", f"{(filled['region'] == '東京').mean():.2%}", "37.81%")

# ------------------------------------------------------------------
# 4. rating を平均で埋めるとばらつきが縮む
# ------------------------------------------------------------------
observed = reviews["rating"].dropna()
check("欠損を落とした件数", len(observed), 14169)
check("星の分布", [int(value) for value in observed.value_counts().sort_index()], [1, 38, 2558, 9325, 2247])
check_close("rating の平均", float(observed.mean()), 3.9725)
check_close("rating の標準偏差", float(observed.std(ddof=1)), 0.5914)
check("rating の中央値", float(observed.median()), 4.0)
check("rating の最頻値", float(observed.mode().iloc[0]), 4.0)

mean_filled = reviews["rating"].fillna(float(observed.mean()))
check("平均代入後の件数", len(mean_filled), 14467)
check_close("平均代入後の平均（変わらない）", float(mean_filled.mean()), 3.9725)
check_close("平均代入後の標準偏差（縮む）", float(mean_filled.std(ddof=1)), 0.5853)
check("標準偏差が縮むこと", float(mean_filled.std(ddof=1)) < float(observed.std(ddof=1)), True)
check(
    "代入値の棒が 1 本増えること（元の 5 種類 + 代入値）",
    int(mean_filled.round(4).nunique()),
    6,
)

# ------------------------------------------------------------------
# 5. SimpleImputer（fit で覚えて transform で当てはめる）
# ------------------------------------------------------------------
X = reviews[["rating"]]
expected_statistics = [("mean", {}, 3.9725), ("median", {}, 4.0), ("most_frequent", {}, 4.0), ("constant", {"fill_value": 0.0}, 0.0)]
for strategy, kwargs, expected_value in expected_statistics:
    imputer = SimpleImputer(strategy=strategy, **kwargs).fit(X)
    check_close(f"SimpleImputer(strategy={strategy}) が覚えた値", float(imputer.statistics_[0]), expected_value)

flagged = SimpleImputer(strategy="mean", add_indicator=True).set_output(transform="pandas")
result = flagged.fit_transform(X)
check("add_indicator=True の出力の列", list(result.columns), ["rating", "missingindicator_rating"])
check("フラグが 1 の行の数", int(result["missingindicator_rating"].sum()), 298)
check_close("SimpleImputer で埋めた後の標準偏差", float(result["rating"].std(ddof=1)), 0.5853)
check("欠損が残っていないこと", int(result["rating"].isna().sum()), 0)

region_imputer = SimpleImputer(strategy="most_frequent", add_indicator=True).set_output(transform="pandas")
region_filled = region_imputer.fit_transform(customers[["region"]])
check("most_frequent が覚えた値（文字列の列）", str(region_imputer.statistics_[0]), "東京")
check("SimpleImputer で埋めた後の東京", int((region_filled["region"] == "東京").sum()), 3025)
check("region のフラグが 1 の行の数", int(region_filled["missingindicator_region"].sum()), 392)

# S25 で組み立てる形の予告（ここでは出力の形だけ確認する）
preview = ColumnTransformer([("cat", SimpleImputer(strategy="most_frequent"), ["region", "channel"])])
check("ColumnTransformer の出力の形", preview.fit_transform(customers).shape, (8000, 2))

# ------------------------------------------------------------------
# 6. 訓練データの統計量で検証データを埋める（toy）
# ------------------------------------------------------------------
toy = pd.DataFrame({"rating": [5.0, 5.0, 4.0, 4.0, np.nan, 2.0, np.nan, 2.0]})
train, test = toy.iloc[:5], toy.iloc[5:]
check("toy の行数", len(toy), 8)
check("toy の欠損数", int(toy["rating"].isna().sum()), 2)
check_close("訓練データの観測平均", float(train["rating"].mean()), 4.5)
check_close("全データの観測平均", float(toy["rating"].mean()), 3.6667)

correct = SimpleImputer(strategy="mean").fit(train)
check_close("訓練だけで fit した値", float(correct.statistics_[0]), 4.5)
check(
    "訓練を埋めた結果（正しい手順）",
    [round(float(value), 4) for value in np.ravel(correct.transform(train))],
    [5.0, 5.0, 4.0, 4.0, 4.5],
)
check(
    "検証を埋めた結果（正しい手順）",
    [round(float(value), 4) for value in np.ravel(correct.transform(test))],
    [2.0, 4.5, 2.0],
)

leaked = SimpleImputer(strategy="mean").fit(toy)
check_close("全データで fit した値", float(leaked.statistics_[0]), 3.6667)
check(
    "訓練を埋めた結果（誤った手順・検証データが混ざる）",
    [round(float(value), 4) for value in np.ravel(leaked.transform(train))],
    [5.0, 5.0, 4.0, 4.0, 3.6667],
)
check(
    "検証を埋めた結果（誤った手順）",
    [round(float(value), 4) for value in np.ravel(leaked.transform(test))],
    [2.0, 3.6667, 2.0],
)
check("2 つの手順で代入値が変わること", float(correct.statistics_[0]) != float(leaked.statistics_[0]), True)

# ------------------------------------------------------------------
# 7. モデルで埋める（KNNImputer の toy）
# ------------------------------------------------------------------
knn_toy = pd.DataFrame(
    {
        "pages": [100.0, 110.0, 300.0, 320.0, 105.0],
        "price": [1000.0, 1100.0, 3000.0, 3200.0, np.nan],
    }
)
knn_filled = KNNImputer(n_neighbors=2).fit_transform(knn_toy)
check_close("KNNImputer が埋めた price", float(knn_filled[4, 1]), 1050.0)
check("KNNImputer は欠損を残さない", int(np.isnan(knn_filled).sum()), 0)

# ------------------------------------------------------------------
# 8. 練習問題の解答（q1〜q6）で本文に載せた数値
# ------------------------------------------------------------------
# 問題1: 行数 - count = 欠損数 の検算
check("問題1 region の検算", len(customers) - int(customers["region"].count()), 392)
check("問題1 rating の検算", len(reviews) - int(reviews["rating"].count()), 298)
check(
    "問題1 結合後の欠損率がマスタより大きいこと",
    float(analysed["region"].isna().mean()) > float(customers["region"].isna().mean()),
    True,
)

# 問題2: 4 つの検定すべてが有意水準を下回らないこと
p_values = [
    channel["p"],
    birth["p"],
    order_count["p"],
    body_length["p"],
]
check("問題2 有意水準を下回った検定の数", sum(p < ALPHA for p in p_values), 0)

# 問題3: 方針ごとの「東京の構成比」（同じデータでも 3 通りの数字になる）
check("問題3 東京の構成比（削除）", f"{(deleted['region'] == '東京').mean():.2%}", "34.61%")
check("問題3 東京の構成比（定数代入）", f"{(constant['region'] == '東京').mean():.2%}", "32.91%")
check("問題3 東京の構成比（最頻値代入）", f"{(filled['region'] == '東京').mean():.2%}", "37.81%")
check("問題3 分布の合計が元の行数に戻ること", int(counts.sum()) == len(customers), True)

# 問題4: 最頻値で埋めると「星 4」だけが 298 件増える
mode_filled = SimpleImputer(strategy="most_frequent").set_output(transform="pandas").fit_transform(X)
check("問題4 代入前の星 4", int((observed == 4.0).sum()), 9325)
check("問題4 最頻値代入後の星 4", int((mode_filled["rating"] == 4.0).sum()), 9325 + 298)

# 問題5: 訓練だけで fit する手順（customers 8,000 行を 6,000 / 2,000 に分ける）
X_train, X_test = train_test_split(customers[["region"]], test_size=0.25, random_state=42)
check("問題5 訓練データの行数", len(X_train), 6000)
check("問題5 検証データの行数", len(X_test), 2000)
q5_imputer = SimpleImputer(strategy="most_frequent", add_indicator=True).set_output(transform="pandas")
q5_train = q5_imputer.fit_transform(X_train)
q5_test = q5_imputer.transform(X_test)
check("問題5 訓練データで覚えた値", str(q5_imputer.statistics_[0]), "東京")
check(
    "問題5 全データで fit しても値は同じ（差が出ないデータでも手順は守る）",
    str(SimpleImputer(strategy="most_frequent").fit(customers[["region"]]).statistics_[0]),
    "東京",
)
check(
    "問題5 フラグの合計（訓練 + 検証）",
    int(q5_train["missingindicator_region"].sum()) + int(q5_test["missingindicator_region"].sum()),
    392,
)
check("問題5 検証データに欠損が残らないこと", int(q5_test["region"].isna().sum()), 0)

# 問題6: 4 方針を同じ形で比較したときのフラグ列
q6_flagged = SimpleImputer(strategy="most_frequent", add_indicator=True).set_output(transform="pandas")
q6_result = q6_flagged.fit_transform(customers[["region"]])
check("問題6 フラグ列の合計", int(q6_result["missingindicator_region"].astype(int).sum()), 392)
check("問題6 代入後のカテゴリ数（フラグを付けても 7 のまま）", q6_result["region"].nunique(), 7)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 11 のすべての検証に成功しました。")
