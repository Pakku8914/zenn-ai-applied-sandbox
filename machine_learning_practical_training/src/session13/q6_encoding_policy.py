"""問題6 の解答: 列ごとの変換方針を、計算した数値を埋め込んだ Markdown レポートにする。

使い方:
    docker compose exec lab python src/session13/q6_encoding_policy.py
    docker compose exec lab python src/session13/q6_encoding_policy.py > outputs/s13_policy.md
"""

from __future__ import annotations

import lightgbm
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder

from common import (
    CATEGORY_FEATURE,
    ID_FEATURE,
    MISSING_LABEL,
    RANDOM_STATE,
    TEST_SIZE,
    auc_of,
    design,
    load_customers,
    load_review_features,
    onehot_features,
    ordinal_features,
    scaled_numeric,
    split_features,
    target_features,
    target_means,
)

MAX_CATEGORIES = 20
UNKNOWN = "写真集"


def main() -> None:
    customers = load_customers()
    df = load_review_features()
    X_train, X_test, y_train, y_test = split_features(df)
    num_train, num_test = scaled_numeric(X_train, X_test)
    prior = float(y_train.mean())

    oh_train, oh_test, oh_encoder = onehot_features(X_train, X_test)
    od_train, od_test, _ = ordinal_features(X_train, X_test)
    onehot = (design(num_train, oh_train), design(num_test, oh_test))
    label = (design(num_train, od_train), design(num_test, od_test))

    def lr(sets) -> float:
        return auc_of(
            LogisticRegression(max_iter=1000, random_state=RANDOM_STATE), sets[0], y_train, sets[1], y_test
        )

    def gbm(sets) -> float:
        return auc_of(
            lightgbm.LGBMClassifier(n_estimators=200, random_state=RANDOM_STATE, verbose=-1),
            sets[0],
            y_train,
            sets[1],
            y_test,
        )

    auc = {
        "lr_onehot": lr(onehot),
        "lr_label": lr(label),
        "gbm_onehot": gbm(onehot),
        "gbm_label": gbm(label),
    }

    book_means = target_means(X_train[ID_FEATURE], y_train)
    clean = target_features(X_train, X_test, book_means, prior, ID_FEATURE)
    leaked_means = target_means(df[ID_FEATURE], df["is_high"])
    leaked = target_features(X_train, X_test, leaked_means, float(df["is_high"].mean()), ID_FEATURE)
    auc["gbm_te_clean"] = gbm((design(num_train, clean[0]), design(num_test, clean[1])))
    auc["gbm_te_leak"] = gbm((design(num_train, leaked[0]), design(num_test, leaked[1])))

    region_levels = customers["region"].nunique() + 1  # 「不明」を 1 水準として数える
    book_levels = X_train[ID_FEATURE].nunique()
    grouped = OneHotEncoder(
        sparse_output=False, handle_unknown="infrequent_if_exist", max_categories=MAX_CATEGORIES
    ).fit(X_train[[ID_FEATURE]])
    grouped_columns = grouped.transform(X_train[[ID_FEATURE]]).shape[1]
    unknown_vector = oh_encoder.transform(pd.DataFrame({CATEGORY_FEATURE: [UNKNOWN]}))

    print("# カテゴリ変数の変換方針（高評価レビューの分類）")
    print()
    print(f"- 母集団 : レビュー {len(df):,} 行（星の欠損を落としたあと）")
    print(f"- 分割 : 訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件"
          f"（test_size={TEST_SIZE}・random_state={RANDOM_STATE}・層化）")
    print(f"- 正例率 : {df['is_high'].mean():.4f}")
    print()
    print("## 1. 列ごとの方針")
    print()
    print("| 列 | 水準の数 | 尺度 | One-Hot の列数 | 方針と根拠 |")
    print("| :--- | ---: | :--- | ---: | :--- |")
    print(f"| region | {customers['region'].nunique()}（＋欠損 {int(customers['region'].isna().sum())} 件）"
          f" | 名義 | {region_levels} | 欠損を「{MISSING_LABEL}」で埋めてから One-Hot。列名で欠損だと分かる |")
    print(f"| channel | {customers['channel'].nunique()} | 名義 | {customers['channel'].nunique()}"
          " | そのまま One-Hot |")
    print(f"| category | {X_train[CATEGORY_FEATURE].nunique()} | 名義 | {oh_train.shape[1]}"
          f" | 線形モデルには One-Hot（Label だと {auc['lr_onehot']:.4f} → {auc['lr_label']:.4f}） |")
    print(f"| book_id | {book_levels} | 名義 | {book_levels}"
          f" | そのまま開かない。max_categories={MAX_CATEGORIES} で {grouped_columns} 列にまとめる |")
    print()
    print("## 2. モデル別の注意")
    print()
    print("| モデル | category の変換 | ROC AUC（One-Hot → Label） |")
    print("| :--- | :--- | :--- |")
    print(f"| ロジスティック回帰 | One-Hot 必須 | {auc['lr_onehot']:.4f} → {auc['lr_label']:.4f} |")
    print(f"| LightGBM | どちらでもよい | {auc['gbm_onehot']:.4f} → {auc['gbm_label']:.4f} |")
    print()
    print("## 3. 未知のカテゴリへの備え")
    print()
    print(f"- `handle_unknown=\"ignore\"` : 未知の「{UNKNOWN}」は"
          f" {[int(v) for v in unknown_vector.to_numpy()[0]]} になる（合計 {int(unknown_vector.to_numpy().sum())}）")
    print("- `handle_unknown=\"error\"` : `ValueError` で止まる。本番の推論では止めてよいかを先に決める")
    print("- どちらにしても、未知の行数を自分で数えて記録する（エラーも警告も出ないため）")
    print()
    print("## 4. データリークを避ける")
    print()
    print(f"- ターゲットエンコーディングを全データで作ると {auc['gbm_te_leak']:.4f}、"
          f"訓練データだけで作ると {auc['gbm_te_clean']:.4f}")
    print("- 高いほうは「評価データの答え」を特徴量に混ぜた結果で、本番では再現できない")
    print("- 対応表は必ず訓練データだけで作り、評価データには当てるだけにする")
    print()
    print("## 5. 申し送り")
    print()
    print("- 変換器（encoder）は学習済みモデルと一緒に保存する。列の並びが変わると予測が狂う")
    print("- 手順（欠損を埋める → 変換する → 標準化する）は後で Pipeline に載せて 1 つにまとめる")
    print("- 新しい水準が増えたら、水準の一覧と列数をこのレポートごと作り直す")


if __name__ == "__main__":
    main()
