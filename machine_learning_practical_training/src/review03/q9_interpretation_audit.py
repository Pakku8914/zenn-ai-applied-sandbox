"""問題9 の解答: 重要度と SHAP の「言いすぎ」を、permutation importance と p 値で正す。

実行:
    docker compose exec lab python src/review03/q9_interpretation_audit.py
"""

from __future__ import annotations

from common import (
    HIGH_NUMERIC,
    PUBLISHED_YEAR_P_VALUE,
    RANDOM_ID,
    TOLERANCE,
    body_length_pair,
    gbm_bundle,
    impurity_table,
    load_review_table,
    pdp_table,
    permutation_table,
    permutation_value,
    shap_local_check,
    shap_mean_abs,
)

WRONG_CLAIMS = [
    "不純度ベースの重要度で random_id が 2 位なので、この列は予測に重要です。",
    "published_year の重要度は 0 ではないので、刊行年は効いています。",
    "SHAP で body_length の寄与が見えたので、レビューを短く書かせれば高評価が増えます。",
]

# 「言い切ってよいか」を決めるときに見る 3 つの列（セッション26 の判定表と同じ形）
JUDGED = ["unit_price", "body_length", "published_year"]
OUTCOME_COLUMNS = ["body_length"]        # 予測したい結果のあとで決まる列
UNREACHABLE_COLUMNS = ["published_year"]  # 施策で動かせない列


def random_id_audit() -> dict:
    """意味のない乱数の列が、4 つの重要度にどう映るかを 1 か所に集める。"""
    plain = gbm_bundle()
    noisy = gbm_bundle(True)
    table = impurity_table(True)
    row = table.loc[table["feature"] == RANDOM_ID].iloc[0]
    top = table.sort_values("split", ascending=False).iloc[0]
    return {
        "n_columns": int(len(table)),
        "split": int(row["split"]),
        "split_rank": int(row["split_rank"]),
        "gain": int(row["gain"]),
        "gain_rank": int(row["gain_rank"]),
        "top_split_feature": str(top["feature"]),
        "top_split": int(top["split"]),
        "perm_test": permutation_value(RANDOM_ID, "test", True),
        "perm_train": permutation_value(RANDOM_ID, "train", True),
        "roc_auc_plain": plain["roc_auc"],
        "roc_auc_noisy": noisy["roc_auc"],
    }


def judge_table() -> list[dict]:
    """3 つの列について「効いているか」「結果の一部か」「介入できるか」を並べる。"""
    impurity = impurity_table()
    perm = permutation_table("test")
    rows = []
    for name in JUDGED:
        split = int(impurity.loc[impurity["feature"] == name, "split"].iloc[0])
        value = float(perm.loc[perm["feature"] == name, "mean"].iloc[0])
        rows.append(
            {
                "feature": name,
                "split": split,
                "permutation": value,
                "solid": "はい" if value > TOLERANCE else "いいえ",
                "is_outcome": "はい" if name in OUTCOME_COLUMNS else "いいえ",
                "can_act": "いいえ" if name in UNREACHABLE_COLUMNS else "はい",
            }
        )
    return rows


def rewrite(audit: dict, body: dict, pdp: dict) -> list[str]:
    """3 つの主張を、根拠の数値を埋め込んだ形に書き直す。"""
    impurity = impurity_table()
    year_split = int(impurity.loc[impurity["feature"] == "published_year", "split"].iloc[0])
    year_perm = permutation_value("published_year", "test")
    local = shap_local_check(0)
    return [
        (
            f"random_id は 0〜9,999 の乱数で、目的変数と何の関係もありません。"
            f"それでも不純度ベースでは split {audit['split']:,} 回で {audit['split_rank']} 位"
            f"（1 位の {audit['top_split_feature']} は {audit['top_split']:,} 回）、gain では {audit['gain_rank']} 位に入ります。"
            f"評価データの permutation importance は {audit['perm_test']:+.4f} で、"
            f"この列を足しても ROC AUC は {audit['roc_auc_plain']:.4f} → {audit['roc_auc_noisy']:.4f} しか動きません。"
            f"不純度ベースの順位は「値の種類が多い列」を上げるだけで、重要さの証拠になりません。"
        ),
        (
            f"published_year は split {year_split:,} 回使われていますが、"
            f"評価データの permutation importance は {year_perm:+.4f}（シャッフルしても性能が落ちない）で、"
            f"線形回帰の p 値も {PUBLISHED_YEAR_P_VALUE:.4f} でした。"
            f"「使われた回数が 0 でない」ことは「効いている」ことを意味しません。"
            f"ここで言えるのは「効いていると言い切れない」までで、「効いていない」と断定もしません。"
        ),
        (
            f"SHAP は 1 件の予測を特徴量ごとの寄与に分解する道具です（この 1 行では寄与の合計 "
            f"{local['total']:+.4f} ＋ 基準値 {local['base']:.4f} ＝ {local['logit']:.4f} → 確率 {local['proba_from_shap']:.4f} と、"
            f"predict_proba の {local['proba_from_model']:.4f} が一致します）。合計が予測に一致するのは加法性という性質で、"
            f"因果の証明ではありません。body_length はレビューを書き終えたあとに決まる値（結果の一部）で、"
            f"部分依存も 20 文字 {pdp['short']:.4f} → 204 文字 {pdp['long']:.4f} と下がりますが、"
            f"この列を外すと ROC AUC は {body['leaked']:.4f} → {body['correct']:.4f} になります。"
            f"短く書かせても星が上がるとは言えません。"
        ),
    ]


def main() -> None:
    audit = random_id_audit()
    print("■ 1. 意味のない乱数の列（random_id）は 4 つの重要度にどう映るか")
    print(f"変換後の列数                      : {audit['n_columns']} 列")
    print(f"不純度ベース split                : {audit['split']:,} 回（{audit['split_rank']} 位）")
    print(f"不純度ベース gain                 : {audit['gain']:,}（{audit['gain_rank']} 位）")
    print(f"split の 1 位                     : {audit['top_split_feature']}（{audit['top_split']:,} 回）")
    print(f"permutation importance（訓練）    : {audit['perm_train']:+.4f}")
    print(f"permutation importance（評価）    : {audit['perm_test']:+.4f}")
    print(f"ROC AUC（random_id なし → あり）  : {audit['roc_auc_plain']:.4f} → {audit['roc_auc_noisy']:.4f}")
    print("→ 騙されたのは split・gain・訓練データの permutation。評価データの permutation だけが騙されませんでした")
    print()

    print("■ 2. permutation importance（評価データ・5 特徴量のモデル）")
    print("列               |  平均   | ばらつき")
    perm = permutation_table("test")
    for name, mean, std in zip(perm["feature"], perm["mean"], perm["std"]):
        print(f"{str(name):<16} | {float(mean):+.4f} | {float(std):.4f}")
    print(f"→ 0 とみなせる（許容誤差 {TOLERANCE} 未満）列は、性能の根拠として使いません")
    print()

    print("■ 3. SHAP の加法性を検算する（1 行目）")
    local = shap_local_check(0)
    for name in HIGH_NUMERIC:
        print(f"{name:<16} の SHAP 値: {local['values'][name]:+.4f}")
    print(f"SHAP 値の合計          : {local['total']:+.4f}")
    print(f"基準値（expected_value）: {local['base']:.4f}")
    print(f"合計 ＋ 基準値（対数オッズ）: {local['logit']:.4f}")
    print(f"シグモイドで確率に直した値  : {local['proba_from_shap']:.4f}")
    print(f"predict_proba の値          : {local['proba_from_model']:.4f}")
    print(f"一致するか                  : {local['matches']}")
    print("■ 3b. SHAP 値の平均絶対値（全体としてどの列が効いたか）")
    mean_abs = shap_mean_abs()
    for name, value in zip(mean_abs["feature"], mean_abs["mean_abs"]):
        print(f"{str(name):<16} : {float(value):.4f}")
    print()

    print("■ 4. 部分依存と「外したらどうなるか」")
    short_table = pdp_table("body_length")
    price_table = pdp_table("unit_price")
    for label, table in (("body_length", short_table), ("unit_price", price_table)):
        points = " / ".join(f"{grid:,.0f} → {average:.4f}" for grid, average in zip(table["grid"], table["average"]))
        print(f"{label:<12}: {points}")
    body = body_length_pair(load_review_table())
    print(f"body_length と rating の相関  : {body['corr']:+.4f}")
    print(f"body_length あり → なしの AUC : {body['leaked']:.4f} → {body['correct']:.4f}")
    print()

    print("■ 5. 「効いている」と言い切ってよいかの判定表")
    print("列               | split |  perm  | 効いていると言えるか | 結果の一部か | 施策で動かせるか")
    for row in judge_table():
        print(
            f"{row['feature']:<16} | {row['split']:>5,} | {row['permutation']:+.4f} |"
            f" {row['solid']:<20} | {row['is_outcome']:<12} | {row['can_act']}"
        )
    print()

    print("■ 6. 3 つの主張を書き直す")
    pdp = {"short": float(short_table["average"].iloc[0]), "long": float(short_table["average"].iloc[-1])}
    for number, (wrong, fixed) in enumerate(zip(WRONG_CLAIMS, rewrite(audit, body, pdp)), start=1):
        print(f"({number}) 誤: {wrong}")
        print(f"    正: {fixed}")


if __name__ == "__main__":
    main()
