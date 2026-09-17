"""問題3 の解答: 係数の表を列名付きで作り、オッズ比として読む。

使い方:
    docker compose exec lab python src/session17/q3_odds_ratio_table.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import fit_model, load_review_table, prepare, split_xy

DELTA_CHARS = 100  # レビュー本文が何文字増えたときのオッズを見るか
# 比べたい 2 つのカテゴリ（オッズ比の比が「何倍か」になる）
COMPARE = ("category_児童書", "category_実用書")


def build_table(model, feature_names: list[str]) -> pd.DataFrame:
    """係数・オッズ比・係数の絶対値を並べた表を作る。列名は前処理器から取り出す。"""
    table = pd.DataFrame({"feature": feature_names, "coef": model.coef_[0]})
    table["odds_ratio"] = np.exp(table["coef"])
    table["abs_coef"] = table["coef"].abs()
    return table.sort_values("abs_coef", ascending=False).reset_index(drop=True)


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)
    model = fit_model(train, y_train)

    table = build_table(model, names)
    print("■ 係数とオッズ比（係数の絶対値が大きい順）")
    for row in table.itertuples(index=False):
        print(f"{row.feature:<22} 係数 {row.coef:+.4f} / オッズ比 {row.odds_ratio:.4f}")
    print(f"切片 {model.intercept_[0]:+.4f}")
    print()

    top = table.iloc[0]
    print("■ いちばん効いている特徴量")
    print(f"{top['feature']}（係数 {top['coef']:+.4f} / オッズ比 {top['odds_ratio']:.4f}）")
    print(f"1 標準偏差だけ高いと、高評価になるオッズは {1 / top['odds_ratio']:.1f} 分の 1 になります。")
    print()

    scale = float(pre.named_transformers_["num"].scale_[3])  # body_length は数値 4 列の 4 番目
    coef_body = float(table.loc[table["feature"] == "body_length", "coef"].iloc[0])
    print("■ body_length を元の単位で読む")
    print(f"1 標準偏差 = {scale:.4f} 文字 / 1 標準偏差でオッズ {np.exp(coef_body):.4f} 倍")
    print(f"{DELTA_CHARS} 文字増でオッズ {np.exp(coef_body * DELTA_CHARS / scale):.4f} 倍")
    print()

    left, right = COMPARE
    or_left = float(table.loc[table["feature"] == left, "odds_ratio"].iloc[0])
    or_right = float(table.loc[table["feature"] == right, "odds_ratio"].iloc[0])
    print("■ カテゴリどうしを比べる（オッズ比の比を取る）")
    print(f"{left} は {right} に比べてオッズが {or_left / or_right:.1f} 倍")
    print("→ 切片の絶対値そのものではなく、係数の差（オッズ比の比）が解釈できる量です。")


if __name__ == "__main__":
    main()
