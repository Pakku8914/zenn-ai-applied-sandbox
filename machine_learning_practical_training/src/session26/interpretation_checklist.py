"""「解釈できる」と「原因がわかる」は別 ― 2 つの列で確かめ、チェックリストにする。

使い方:
    docker compose exec lab python src/session26/interpretation_checklist.py
"""

from __future__ import annotations

from common import impurity_table, permutation_table, shap_mean_abs

# セッション16・セッション22 で実測した値（この章では再計算せず、根拠として引用する）
PUBLISHED_YEAR_P_VALUE = 0.2425  # 回帰の係数の p 値。有意ではない
PRICE_PAGES_CORRELATION = 0.9709  # price と pages の相関
PRICE_PAGES_VIF = 17.432  # 同じ 2 列の VIF

CHECKLIST = [
    "時間の順序 : その列は予測したい時点より前に確定しているか",
    "結果の一部 : その列は目的変数の言い換えになっていないか",
    "強い相関   : 同じ情報を持つ列が別にないか",
    "測り方     : どの重要度で測ったか（種類で順位が変わる）",
    "介入可能性 : その列を実際に動かせるか",
]


def measures(name: str) -> dict:
    """1 つの列について、4 種類の重要度をまとめて取り出す。"""
    impurity = impurity_table()
    row = impurity.loc[impurity["feature"] == name].iloc[0]
    perm = permutation_table("test").set_index("feature")
    shap_table = shap_mean_abs().set_index("feature")
    return {
        "split": int(row["split"]),
        "gain": int(row["gain"]),  # 表示は int()（切り捨て）で統一する
        "permutation": float(perm.loc[name, "mean"]),
        "shap_mean_abs": float(shap_table.loc[name, "mean_abs"]),
    }


def show(name: str) -> dict:
    """4 種類の重要度を同じ並びで表示する。"""
    result = measures(name)
    print(f"split（不純度・回数） : {result['split']:,}")
    print(f"gain（不純度・改善量）: {result['gain']:,}")
    print(f"permutation（評価）   : {result['permutation']:+.4f}")
    print(f"SHAP の平均絶対値     : {result['shap_mean_abs']:.4f}")
    return result


def main() -> None:
    print("■ 1. published_year ― 重要度は 0 でないが、壊しても性能は落ちない")
    year = show("published_year")
    print(f"セッション16 の p 値  : {PUBLISHED_YEAR_P_VALUE:.4f}（有意ではない）")
    print("判断: 不純度ベースの重要度は 0 になりません（木は分割に使えるものは使う）。")
    print("      一方で permutation importance はほぼ 0。『重要度が 0 でない』は『効いている』の証拠になりません。")
    print()

    print("■ 2. body_length ― どの重要度でも上位だが、原因ではない")
    length = show("body_length")
    print("判断: レビュー本文の長さは、星を付けたあとに決まる量です（セッション22 のリーク）。")
    print("      『本文を短く書かせれば星が上がる』という介入は成り立ちません。")
    print()

    print("■ 3. 解釈を因果と読み違えないためのチェックリスト")
    for number, item in enumerate(CHECKLIST, start=1):
        print(f"{number}. {item}")
    print(f"   ※ 強い相関の例: price と pages は相関 {PRICE_PAGES_CORRELATION:.4f}・VIF {PRICE_PAGES_VIF:.3f}（セッション16）")
    print()

    print("■ 4. 2 列の判定")
    print(f"published_year: permutation {year['permutation']:+.4f} ＝ 予測に効いていない。介入もできない。")
    print(f"body_length   : permutation {length['permutation']:+.4f} ＝ 予測には効く。ただし原因ではない。")
    print()
    print("注意: SHAP の値は『数値 4 列・木 50 本』の別のモデルで計算しています。")
    print("      同じ列でも、相手のモデルが違えば数字はそのまま比べられません。")


if __name__ == "__main__":
    main()
