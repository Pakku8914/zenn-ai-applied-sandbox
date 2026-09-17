"""係数をオッズ比として読む。標準化した係数だからこそ大きさを比べられる。

使い方:
    docker compose exec lab python src/session17/odds_ratio.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from common import (
    NUMERIC,
    OUT_DIR,
    RANDOM_STATE,
    TEST_SIZE,
    coefficient_table,
    fit_model,
    load_review_table,
    numeric_scale,
    odds_multiplier,
    prepare,
    print_coefficient_table,
    split_xy,
)

# レビュー本文が何文字増えたときのオッズを見るか
DELTA_CHARS = 100


def unscaled_design(df: pd.DataFrame) -> pd.DataFrame:
    """標準化しない 9 列の特徴量を作る（セッション12 の「スケーリングなし」と同じ作り方）。"""
    dummies = pd.get_dummies(df["category"], dtype="float64")  # 列は名前順に並ぶ
    return pd.concat([df[NUMERIC].astype("float64"), dummies], axis=1)


def draw(table: pd.DataFrame, path) -> None:
    """オッズ比の棒グラフを描く。1.0 より右は「高評価になりやすい」。"""
    ordered = table.sort_values("odds_ratio")
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    colors = ["#e45756" if v < 1 else "#4c78a8" for v in ordered["odds_ratio"]]
    # 棒の基準を 1.0（影響なし）に置く。対数目盛なので 0 を含めない
    ax.barh(ordered["feature"], ordered["odds_ratio"] - 1.0, left=1.0, color=colors)
    ax.axvline(1.0, color="#333333", linewidth=1)
    ax.set_xscale("log")  # 0.5 倍と 2 倍が左右対称に見えるように対数目盛にする
    ax.set_xlim(0.05, 10.0)
    ax.set_xlabel("オッズ比（1.0 が「影響なし」・対数目盛）")
    ax.set_title("高評価になるオッズを何倍にするか（1 標準偏差あたり）")
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    model = fit_model(train, y_train)

    table = coefficient_table(model, names)
    print("■ 標準化した係数とオッズ比（係数の大きい順）")
    print_coefficient_table(table)
    print(f"{'切片（intercept）':<22} 係数 {model.intercept_[0]:+.4f}")
    print()

    positive = list(table.loc[table["coef"] > 0, "feature"])
    negative = list(table.loc[table["coef"] < 0, "feature"])
    print("■ 符号の読み方")
    print(f"正（高評価になりやすい）: {', '.join(positive)}")
    print(f"負（高評価になりにくい）: {', '.join(negative)}")
    print()

    scale = numeric_scale(pre, "body_length")
    coef_body = float(table.loc[table["feature"] == "body_length", "coef"].iloc[0])
    print("■ 標準化された「1 目盛」を元の単位に戻す（body_length）")
    print(f"1 標準偏差 = {scale:.4f} 文字（スケーラが訓練データで fit した値）")
    print(f"（参考）全データの標本標準偏差 = {df['body_length'].std():.4f} 文字 ← これは使わない")
    print(f"1 標準偏差ぶん長くなるとオッズは {np.exp(coef_body):.4f} 倍")
    print(f"{DELTA_CHARS} 文字ぶん長くなるとオッズは {odds_multiplier(coef_body, DELTA_CHARS, scale):.4f} 倍")
    print()

    # 標準化は「当たり方」を変えない。係数を比べられるようにするためにやっている
    X_raw = unscaled_design(df)
    Xr_train, Xr_test, yr_train, yr_test = train_test_split(
        X_raw, df["is_high"], test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=df["is_high"]
    )
    raw_model = fit_model(Xr_train, yr_train)
    raw_auc = float(roc_auc_score(yr_test, raw_model.predict_proba(Xr_test)[:, 1]))
    scaled_auc = float(roc_auc_score(y_test, model.predict_proba(test)[:, 1]))
    print("■ 標準化すると精度が上がるのか（セッション12 の結果の再確認）")
    print(f"標準化あり ROC AUC {scaled_auc:.4f} / 標準化なし ROC AUC {raw_auc:.4f}")
    print("→ 当たり方はほとんど同じです。標準化は精度のためではなく、係数を比べるために行います。")
    print()

    path = OUT_DIR / "s17_odds_ratio.png"
    draw(table, path)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
