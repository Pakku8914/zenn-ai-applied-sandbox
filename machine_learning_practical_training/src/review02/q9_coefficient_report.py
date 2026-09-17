"""実装問題 9：係数と重要度の読み方を直す（誤った報告文の訂正）。

使い方:
    docker compose exec lab python src/review02/q9_coefficient_report.py
"""

from __future__ import annotations

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import Lasso, Ridge
from sklearn.tree import DecisionTreeClassifier

from common import (
    LASSO_ALPHAS,
    N_ESTIMATORS,
    RANDOM_STATE,
    REG_CORE_FEATURES,
    REG_FEATURES,
    REG_TARGET,
    RIDGE_ALPHAS,
    add_pages_dup,
    category_columns,
    coef_series,
    fit_linear,
    fit_ols,
    fit_penalized,
    fit_pipeline,
    fitted_feature_names,
    fmt_p,
    importance_series,
    load_review_table,
    regression_scores,
    score_pipeline,
    split_classification,
    split_regression,
    standardize,
    vif_display,
    vif_table,
    zero_columns,
)

# 直す対象の 3 つの報告文（どれも本書のデータに対する誤った書き方）
WRONG_CLAIMS = [
    "生スケールの係数を比べると body_length が最も大きいので、本文の長さが最も重要だ",
    "price と pages の VIF が 17 もあるので、このモデルの予測は壊れている",
    "ランダムフォレストの重要度が 0.0707 あるので、published_year は効いている",
]


def coef_line(values: pd.Series, digits: int) -> str:
    """係数を 1 行にまとめる。符号が意味を持つので必ず付ける（列名も必ず添える）。"""
    return " / ".join(f"{name} {value:+.{digits}f}" for name, value in values.items())


def value_line(values: pd.Series, digits: int) -> str:
    """重要度のように 0 以上しか取らない値を 1 行にまとめる（符号は付けない）。"""
    return " / ".join(f"{name} {value:.{digits}f}" for name, value in values.items())


def step1_scale(df: pd.DataFrame) -> dict:
    """尺度をそろえないと係数は比べられない（セッション12・16）。"""
    X_train, X_test, y_train, y_test = split_regression(df)
    raw_model = fit_linear(X_train, y_train)
    raw = coef_series(raw_model, X_train.columns)
    X_train_s, X_test_s, _ = standardize(X_train, X_test)
    std_model = fit_linear(X_train_s, y_train)
    std = coef_series(std_model, X_train_s.columns)
    scores = regression_scores(raw_model, X_test, y_test)
    scores_std = regression_scores(std_model, X_test_s, y_test)

    print(f"■ 1. 係数は尺度をそろえてから比べる（星の回帰・訓練 {len(X_train):,} 件 / 評価 {len(X_test):,} 件）")
    print(f"  生スケール: {coef_line(raw, 6)}")
    print(f"  切片: {raw_model.intercept_:+.4f}")
    print(f"  標準化後  : {coef_line(std, 4)}")
    print(f"  絶対値が最大の列: 生スケール {raw.abs().idxmax()} / 標準化後 {std.abs().idxmax()}")
    print(f"  price は body_length の {abs(std['price']) / abs(std['body_length']):.1f} 倍（標準化後）")
    print(f"  評価データ: R2 {scores['r2']:.4f} / MAE {scores['mae']:.4f} / RMSE {scores['rmse']:.4f}")
    print(f"  検算 標準化しても R2 は変わらない: {abs(scores['r2'] - scores_std['r2']) < 1e-9}")
    return {
        "raw": raw, "std": std, "r2": scores["r2"],
        "raw_split": (X_train, y_train),
        "std_split": (X_train_s, X_test_s, y_train, y_test),
    }


def step2_vif(df: pd.DataFrame, r2: float, std_split: tuple) -> None:
    """VIF が壊すのは「係数の解釈」で、「予測」ではない（セッション16）。"""
    vif = vif_table(df[REG_FEATURES])
    dup = add_pages_dup(df)                      # pages_dup = pages * 6 + ノイズ
    dup_features = REG_CORE_FEATURES + ["pages_dup"]
    vif_dup = vif_table(dup[dup_features])
    plain = fit_ols(df[REG_CORE_FEATURES], df[REG_TARGET])
    shaken = fit_ols(dup[dup_features], df[REG_TARGET])

    print(f"■ 2. VIF が高い ≠ 予測が壊れている（データの性質なので {len(df):,} 件すべてで見る）")
    print(f"  corr(pages, price) = {df['pages'].corr(df['price']):.4f}")
    print(f"  VIF: price {vif_display(vif['price'])} / pages {vif_display(vif['pages'])}")
    print("  published_year と body_length の VIF は 1 前後（他の列から予測できない）")
    print(f"  VIF が 10 を超えた列: {[str(name) for name, value in vif.items() if value > 10]}")
    print(f"  それでも評価データの R2 は {r2:.4f}（予測は壊れていない）")
    print("  pages の写し（pages * 6 + ノイズ）を 1 本足すと:")
    print(f"    pages の VIF: {vif_display(vif['pages'])} → {vif_display(vif_dup['pages'])}")
    print(f"    pages_dup の VIF: {vif_display(vif_dup['pages_dup'])}")
    print(f"    VIF が 10 を超えた列: {[str(name) for name, value in vif_dup.items() if value > 10]}")
    print(f"    pages の係数: {plain.params['pages']:+.5f} → {shaken.params['pages']:+.5f}")
    print(f"    pages の p 値: {fmt_p(float(shaken.pvalues['pages']))}（有意でない）")
    print(f"    検算 当てはまり（訓練の R2）はほとんど動かない: {abs(plain.rsquared - shaken.rsquared) < 0.001}")

    X_train_s, X_test_s, y_train, y_test = std_split
    print("  対処: ① 片方の列を落とす ② Ridge で係数を縮める")
    for alpha in RIDGE_ALPHAS:
        coefs, r2_ridge = fit_penalized(Ridge(alpha=alpha), X_train_s, y_train, X_test_s, y_test)
        print(f"    Ridge α={alpha}: price の係数 {coefs['price']:+.4f} / 評価 R2 {r2_ridge:.4f}")


def step3_importance(df: pd.DataFrame, std: pd.Series, raw_split: tuple, std_split: tuple) -> None:
    """重要度は「分岐に使われた量」であって「効いている証拠」ではない（セッション18・19）。"""
    X_train, X_test, y_train, y_test = split_classification(df)
    forest = fit_pipeline(
        RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=1),
        X_train,
        y_train,
    )
    forest_scores = score_pipeline(forest, X_test, y_test)
    forest_importance = importance_series(forest)
    shallow = fit_pipeline(DecisionTreeClassifier(max_depth=3, random_state=RANDOM_STATE), X_train, y_train)
    shallow_importance = importance_series(shallow)
    names = fitted_feature_names(forest)
    categories = category_columns(names)
    numeric = [name for name in names if name not in categories]

    print("■ 3.「重要度が 0 でない」は「効いている」ではない（高評価レビューの分類）")
    print(
        f"  ランダムフォレスト（{N_ESTIMATORS} 本）: "
        f"accuracy {forest_scores['accuracy']:.4f} / ROC AUC {forest_scores['roc_auc']:.4f}"
    )
    print(f"  重要度: {value_line(forest_importance[numeric], 4)}")
    print(
        f"  数値 4 列の合計: {forest_importance[numeric].sum():.3f}"
        f" / カテゴリ 5 列の合計: {forest_importance[categories].sum():.3f}"
    )
    used = shallow_importance[shallow_importance > 0]
    unused = [str(name) for name in shallow_importance[shallow_importance == 0].index]
    print(f"  決定木（深さ 3）が使った列: {value_line(used, 4)}")
    print(f"  決定木（深さ 3）が 1 度も使わなかった列: {unused}")

    X_train_raw, y_train_raw = raw_split
    ols = fit_ols(X_train_raw, y_train_raw)
    low, high = ols.conf_int().loc["published_year"].iloc[0], ols.conf_int().loc["published_year"].iloc[1]
    print("  published_year を別の道具で見ると:")
    print(f"    標準化後の線形回帰の係数: {std['published_year']:+.4f}")
    print(f"    statsmodels の p 値: {fmt_p(float(ols.pvalues['published_year']))}（有意でない）")
    print(f"    95% 信頼区間が 0 をまたぐ: {bool(low < 0 < high)}")
    X_train_s, X_test_s, y_train_s, y_test_s = std_split
    for alpha in LASSO_ALPHAS:
        coefs, r2_lasso = fit_penalized(Lasso(alpha=alpha), X_train_s, y_train_s, X_test_s, y_test_s)
        print(f"    Lasso α={alpha}: ゼロになった列 {zero_columns(coefs)} / 評価 R2 {r2_lasso:.4f}")


def step4_rewrite(raw: pd.Series, std: pd.Series) -> None:
    """3 つの報告文を、根拠となる数値を添えて書き直す。"""
    ratio = abs(std["price"]) / abs(std["body_length"])
    rewritten = [
        [
            f"標準化して比べると、1 標準偏差あたりの効果は price {std['price']:+.4f} が最大で、",
            f"body_length {std['body_length']:+.4f} の約 {ratio:.1f} 倍です。生スケールの係数",
            f"（price {raw['price']:+.6f} / body_length {raw['body_length']:+.6f}）の大小は",
            "単位の違いを見ているだけで、重要さの順位にはなりません。",
        ],
        [
            "VIF が高いときに壊れるのは係数の解釈で、予測そのものは壊れていません。",
            "写しの列を足しても当てはまりはほとんど動かず、動いたのは pages の係数と p 値でした。",
            "報告では「price と pages はほぼ同じ情報なので、どちらの係数も単独では読めない」と書き、",
            "予測の良し悪しは R2 で別に述べます。",
        ],
        [
            "木の重要度は「分岐に使われた量」なので、効いていない列にも 0 より大きい値が付きます。",
            f"published_year は標準化後の係数が {std['published_year']:+.4f} と小さく、p 値は有意でなく、",
            "信頼区間は 0 をまたぎ、Lasso では最初に消える列でした。",
            "「重要度が 0 でないので効いている」とは言えません。",
        ],
    ]
    print("■ 4. 誤った報告文を書き直す")
    for number, (claim, lines) in enumerate(zip(WRONG_CLAIMS, rewritten), start=1):
        print(f"  ({number}) 誤り: 「{claim}」")
        for position, line in enumerate(lines):
            # 1 行目だけに見出しを付け、2 行目以降は見出しの幅（全角 4 文字 +「: 」）だけ字下げする
            head = "書き直し: " if position == 0 else " " * 10
            print(f"      {head}{line}")


def main() -> None:
    df = load_review_table()
    first = step1_scale(df)
    step2_vif(df, first["r2"], first["std_split"])
    step3_importance(df, first["std"], first["raw_split"], first["std_split"])
    step4_rewrite(first["raw"], first["std"])


if __name__ == "__main__":
    main()
