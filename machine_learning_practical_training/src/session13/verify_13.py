"""セッション 13 の検証スクリプト。

「セッション13：カテゴリ変数のエンコーディング ― 文字を数値に変える」の本文・練習問題・解答に
載せた数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session13/verify_13.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import lightgbm
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

import cardinality
import high_cardinality
import label_vs_onehot
import onehot_basics
import q1_cardinality_report
import q2_onehot_encoder
import q3_unknown_handling
import q4_encoding_models
import q5_target_encoding
import q6_encoding_policy
import target_encoding
import unknown_category
from common import (
    CATEGORY_FEATURE,
    DATA_DIR,
    ID_FEATURE,
    MISSING_LABEL,
    OUT_DIR,
    RANDOM_STATE,
    auc_of,
    design,
    load_books,
    load_customers,
    load_review_features,
    onehot_features,
    ordinal_features,
    scaled_numeric,
    split_features,
    target_features,
    target_means,
)

TOLERANCE = 0.005  # 指標の許容誤差（本書共通）
MAX_CATEGORIES = 20
UNKNOWN = "写真集"

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
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


missing = [name for name in ("books", "customers", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. カーディナリティ（水準の数）と水準の一覧
# ------------------------------------------------------------------
customers = load_customers()
books = load_books()
check("region の水準の数", int(customers["region"].nunique()), 7)
check("channel の水準の数", int(customers["channel"].nunique()), 4)
check("category の水準の数", int(books["category"].nunique()), 5)
check("book_id の水準の数", int(books["book_id"].nunique()), 600)
check("region の欠損の数", int(customers["region"].isna().sum()), 392)
check(
    "region の水準の一覧",
    " / ".join(sorted(customers["region"].dropna().unique())),
    "北海道 / 大阪 / 宮城 / 広島 / 愛知 / 東京 / 福岡",
)
check("channel の水準の一覧", " / ".join(sorted(customers["channel"].unique())), "SNS / メルマガ / 検索 / 紹介")
check(
    "category の水準の一覧",
    " / ".join(sorted(books["category"].unique())),
    "ビジネス / 児童書 / 実用書 / 小説 / 技術書",
)
ids = sorted(books["book_id"])
check("book_id の最小と最大", f"{ids[0]} ... {ids[-1]}", "B0001 ... B0600")

# ------------------------------------------------------------------
# 2. One-Hot エンコーディング（列数・列名・行ごとに立つ 1 の数）
# ------------------------------------------------------------------
filled = customers.copy()
filled["region"] = filled["region"].fillna(MISSING_LABEL)
two = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
encoded_two = two.fit_transform(filled[["region", "channel"]])
check("region（不明を含む）+ channel を開いた列数", encoded_two.shape[1], 12)
check(
    "できた列の名前",
    " / ".join(two.get_feature_names_out(["region", "channel"])),
    "region_不明 / region_北海道 / region_大阪 / region_宮城 / region_広島 / region_愛知 / region_東京"
    " / region_福岡 / channel_SNS / channel_メルマガ / channel_検索 / channel_紹介",
)
check("すべての行で 1 の合計が 2 になること", bool((encoded_two.sum(axis=1) == 2).all()), True)
check("「不明」で埋めた行数", int(filled["region"].eq(MISSING_LABEL).sum()), 392)

# 欠損を埋めずに開くと、NaN 自体が 1 つの水準として扱われる
raw = OneHotEncoder(sparse_output=False, handle_unknown="ignore").fit(customers[["region"]])
check("欠損を埋めずに開いたときの水準の数", len(raw.categories_[0]), 8)
check("最後の水準が欠損（NaN）であること", bool(pd.isna(raw.categories_[0][-1])), True)

# 5 水準の category を 3 行だけ変換した結果
five = OneHotEncoder(sparse_output=False, handle_unknown="ignore").fit(books[["category"]])
sample = pd.DataFrame({"category": ["技術書", "小説", "実用書"]})
check(
    "3 行の変換結果",
    [[int(v) for v in row] for row in five.transform(sample)],
    [[0, 0, 0, 0, 1], [0, 0, 0, 1, 0], [0, 0, 1, 0, 0]],
)
check(
    "category の列名",
    " / ".join(five.get_feature_names_out(["category"])),
    "category_ビジネス / category_児童書 / category_実用書 / category_小説 / category_技術書",
)

# ------------------------------------------------------------------
# 3. 未知のカテゴリ（handle_unknown）
# ------------------------------------------------------------------
new_rows = pd.DataFrame({CATEGORY_FEATURE: [UNKNOWN, "技術書"]})
ignored = five.transform(new_rows)
check("未知のカテゴリを ignore で変換した結果", [int(v) for v in ignored[0]], [0, 0, 0, 0, 0])
check("未知のカテゴリのベクトルの合計", int(ignored[0].sum()), 0)
check("既知のカテゴリのベクトルの合計", int(ignored[1].sum()), 1)

strict = OneHotEncoder(sparse_output=False, handle_unknown="error").fit(books[["category"]])
try:
    strict.transform(new_rows)
except ValueError as error:
    check("未知のカテゴリで送出される例外の型", type(error).__name__, "ValueError")
    check(
        "例外メッセージに未知の水準と column 0 が含まれること",
        all(part in str(error) for part in ("Found unknown categories", UNKNOWN, "column 0")),
        True,
    )
else:
    check("未知のカテゴリで例外が出ること", "例外が出なかった", "ValueError")

ordinal = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1).fit(books[["category"]])
check(
    "OrdinalEncoder が付ける番号の順（辞書順）",
    " / ".join(ordinal.categories_[0]),
    "ビジネス / 児童書 / 実用書 / 小説 / 技術書",
)
codes = ordinal.transform(new_rows)
check("未知のカテゴリの番号", int(codes[0][0]), -1)
check("技術書の番号", int(codes[1][0]), 4)

# ------------------------------------------------------------------
# 4. 高評価分類の土台（前章と同じ特徴量・同じ分割であること）
# ------------------------------------------------------------------
df = load_review_features()
check("学習に使うレビュー件数", len(df), 14169)
X_train, X_test, y_train, y_test = split_features(df)
check("訓練データの件数", len(X_train), 10626)
check("評価データの件数", len(X_test), 3543)
check_close("正例率", float(df["is_high"].mean()), 0.8167)
check("訓練データの category の水準の数", int(X_train[CATEGORY_FEATURE].nunique()), 5)
check("訓練データの book_id の水準の数", int(X_train[ID_FEATURE].nunique()), 600)

rates = y_train.groupby(X_train[CATEGORY_FEATURE]).mean()
for name, expected in [
    ("児童書", 0.9848),
    ("小説", 0.9745),
    ("ビジネス", 0.7872),
    ("技術書", 0.7656),
    ("実用書", 0.6626),
]:
    check_close(f"訓練データの高評価率（{name}）", float(rates[name]), expected, tol=0.0001)
check(
    "高評価率の高い順",
    " > ".join(rates.sort_values(ascending=False).index),
    "児童書 > 小説 > ビジネス > 技術書 > 実用書",
)
check(
    "番号の順に並べた高評価率が単調でないこと",
    bool(rates.reindex(ordinal.categories_[0]).is_monotonic_increasing),
    False,
)

# ------------------------------------------------------------------
# 5. One-Hot と Label でモデルの性能がどう変わるか（この章の山場）
# ------------------------------------------------------------------
num_train, num_test = scaled_numeric(X_train, X_test)
oh_train, oh_test, _ = onehot_features(X_train, X_test)
od_train, od_test, _ = ordinal_features(X_train, X_test)
onehot_sets = (design(num_train, oh_train), design(num_test, oh_test))
label_sets = (design(num_train, od_train), design(num_test, od_test))
check("One-Hot の特徴量の列数", onehot_sets[0].shape[1], 9)
check("Label の特徴量の列数", label_sets[0].shape[1], 5)
check("標準化した数値 4 列の平均が 0 であること", [round(float(v), 6) for v in num_train.mean()], [0.0] * 4)


def lr_auc(sets: tuple[pd.DataFrame, pd.DataFrame]) -> float:
    return auc_of(LogisticRegression(max_iter=1000, random_state=RANDOM_STATE), sets[0], y_train, sets[1], y_test)


def gbm_auc(sets: tuple[pd.DataFrame, pd.DataFrame]) -> float:
    model = lightgbm.LGBMClassifier(n_estimators=200, random_state=RANDOM_STATE, verbose=-1)
    return auc_of(model, sets[0], y_train, sets[1], y_test)


auc_lr_onehot = lr_auc(onehot_sets)
auc_lr_label = lr_auc(label_sets)
auc_gbm_onehot = gbm_auc(onehot_sets)
auc_gbm_label = gbm_auc(label_sets)
check_close("One-Hot × ロジスティック回帰の ROC AUC", auc_lr_onehot, 0.8265)
check_close("Label × ロジスティック回帰の ROC AUC", auc_lr_label, 0.7416)
check_close("One-Hot × LightGBM の ROC AUC", auc_gbm_onehot, 0.7966)
check_close("Label × LightGBM の ROC AUC", auc_gbm_label, 0.7965)
check("線形モデルは Label で 0.05 より大きく下がること", bool(auc_lr_onehot - auc_lr_label > 0.05), True)
check("木モデルの差が許容誤差 0.005 未満であること", bool(abs(auc_gbm_onehot - auc_gbm_label) < TOLERANCE), True)

# ------------------------------------------------------------------
# 6. ターゲットエンコーディング（作り方でどれだけ評価が変わるか）
# ------------------------------------------------------------------
prior = float(y_train.mean())
means = target_means(X_train[CATEGORY_FEATURE], y_train)
check("対応表の水準の数（category）", len(means), 5)
cat_train, cat_test = target_features(X_train, X_test, means, prior, CATEGORY_FEATURE)
auc_te_category = gbm_auc((design(num_train, cat_train), design(num_test, cat_test)))
check_close("category のターゲットエンコーディング（訓練データのみ）", auc_te_category, 0.7949)

book_means = target_means(X_train[ID_FEATURE], y_train)
check("対応表の水準の数（book_id）", len(book_means), 600)
check("評価データの book_id がすべて対応表にあること", bool(X_test[ID_FEATURE].isin(book_means.index).all()), True)
bt_train, bt_test = target_features(X_train, X_test, book_means, prior, ID_FEATURE)
auc_te_clean = gbm_auc((design(num_train, bt_train), design(num_test, bt_test)))
check_close("book_id のターゲットエンコーディング（訓練データのみ）", auc_te_clean, 0.7809)

leaked_means = target_means(df[ID_FEATURE], df["is_high"])
bl_train, bl_test = target_features(X_train, X_test, leaked_means, float(df["is_high"].mean()), ID_FEATURE)
auc_te_leak = gbm_auc((design(num_train, bl_train), design(num_test, bl_test)))
check_close("book_id のターゲットエンコーディング（全データ）", auc_te_leak, 0.8153)
check_close("全データで作ったときの過大評価の幅", auc_te_leak - auc_te_clean, 0.0344)
check("全データで作ったほうが高く出ること", bool(auc_te_leak > auc_te_clean), True)
check("book_id を訓練データだけで作ると One-Hot より下がること", bool(auc_te_clean < auc_gbm_onehot), True)

# ------------------------------------------------------------------
# 7. 高カーディナリティ（book_id 600 水準）
# ------------------------------------------------------------------
wide_encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore").fit(X_train[[ID_FEATURE]])
wide = wide_encoder.transform(X_train[[ID_FEATURE]])
check("book_id をそのまま開いた列数", wide.shape[1], 600)
check("0/1 の表の大きさ", wide.shape, (10626, 600))
check("1 行に立つ 1 の数", int(wide[0].sum()), 1)

grouped = OneHotEncoder(
    sparse_output=False, handle_unknown="infrequent_if_exist", max_categories=MAX_CATEGORIES
).fit(X_train[[ID_FEATURE]])
narrow = grouped.transform(X_train[[ID_FEATURE]])
check(f"max_categories={MAX_CATEGORIES} のときの列数", narrow.shape[1], MAX_CATEGORIES)
check("まとめられた水準の数", len(grouped.infrequent_categories_[0]), 600 - (MAX_CATEGORIES - 1))
check(
    "まとめ用の列の名前",
    str(grouped.get_feature_names_out([ID_FEATURE])[-1]),
    "book_id_infrequent_sklearn",
)
check("まとめたあとも 1 行に立つ 1 の数が 1 であること", bool((narrow.sum(axis=1) == 1).all()), True)

# ------------------------------------------------------------------
# 8. 本文・練習問題の解答スクリプトが最後まで動くこと
# ------------------------------------------------------------------
FIGURES = ["s13_category_rate.png"]
for name in FIGURES:
    (Path(OUT_DIR) / name).unlink(missing_ok=True)

modules = [
    # 本文のスクリプト
    cardinality,
    onehot_basics,
    unknown_category,
    label_vs_onehot,
    target_encoding,
    high_cardinality,
    # 練習問題の解答
    q1_cardinality_report,
    q2_onehot_encoder,
    q3_unknown_handling,
    q4_encoding_models,
    q5_target_encoding,
    q6_encoding_policy,
]
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):  # 各スクリプトの出力は抑制する
        for module in modules:
            module.main()
glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)

for name in FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 13 のすべての検証に成功しました。")
