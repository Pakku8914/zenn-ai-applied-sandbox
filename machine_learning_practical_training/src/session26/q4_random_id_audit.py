"""問題4: 意味のない random_id を足して、どの重要度なら騙されないかを確かめる。

使い方:
    docker compose exec lab python src/session26/q4_random_id_audit.py
"""

from __future__ import annotations

from common import RANDOM_ID, fitted, impurity_table, permutation_table

TOP_RANK = 3  # 「上位」とみなす順位
EFFECT_FLOOR = 0.01  # これ以上 AUC が落ちるなら「効いている」とみなす
AUC_TOLERANCE = 0.005  # 本書共通の許容誤差。これ以内の差は「変わらない」と読む


def audit() -> dict:
    """random_id を 4 つの見方で調べ、それぞれが騙されたかどうかを判定する。"""
    plain = fitted()
    noisy = fitted(True)
    table = impurity_table(True)
    row = table.loc[table["feature"] == RANDOM_ID].iloc[0]
    top_split = table.sort_values("split", ascending=False).iloc[0]

    perm_test = float(permutation_table("test", True).set_index("feature").loc[RANDOM_ID, "mean"])
    perm_train = float(permutation_table("train", True).set_index("feature").loc[RANDOM_ID, "mean"])
    diff = noisy["roc_auc"] - plain["roc_auc"]
    return {
        "roc_auc_plain": plain["roc_auc"],
        "roc_auc_noisy": noisy["roc_auc"],
        "auc_diff": diff,
        "auc_changed": bool(abs(diff) > AUC_TOLERANCE),
        "n_columns": len(table),
        "split": int(row["split"]),
        "split_rank": int(row["split_rank"]),
        "gain": int(row["gain"]),
        "gain_rank": int(row["gain_rank"]),
        "top_split_feature": str(top_split["feature"]),
        "top_split": int(top_split["split"]),
        "perm_test": perm_test,
        "perm_train": perm_train,
        # 「この重要度は騙されたか？」の判定
        "split_fooled": bool(int(row["split_rank"]) <= TOP_RANK),
        "gain_fooled": bool(int(row["gain_rank"]) <= TOP_RANK),
        "perm_test_fooled": bool(perm_test > EFFECT_FLOOR),
        "perm_train_fooled": bool(perm_train > EFFECT_FLOOR),
    }


def main() -> None:
    result = audit()

    print("■ 1. 予測性能は変わったか")
    print(f"random_id なし: {result['roc_auc_plain']:.4f}")
    print(f"random_id あり: {result['roc_auc_noisy']:.4f}")
    print(f"差            : {result['auc_diff']:+.3f}")
    print(f"許容誤差 {AUC_TOLERANCE} を超えて変わったか: {result['auc_changed']}")
    print()

    print("■ 2. 4 つの見方で random_id を評価する")
    print(f"{'見方':<22}{'値':>10}  騙されたか")
    print(f"{'不純度（split）':<22}{result['split']:>10,}  {result['split_fooled']}")
    print(f"{'不純度（gain）':<22}{result['gain']:>10,}  {result['gain_fooled']}")
    print(f"{'permutation（訓練）':<22}{result['perm_train']:>10.4f}  {result['perm_train_fooled']}")
    print(f"{'permutation（評価）':<22}{result['perm_test']:>10.4f}  {result['perm_test_fooled']}")
    print()
    print(f"split は {result['n_columns']} 列中 {result['split_rank']} 位（1 位は {result['top_split_feature']} の {result['top_split']:,}）")
    print(f"gain は {result['n_columns']} 列中 {result['gain_rank']} 位")
    print()

    print("■ 3. 結論")
    print("予測性能は動いていないので、random_id は情報をまったく持っていません。")
    print("それでも不純度ベースの重要度は上位に置きます。値がばらけている列は分割の候補が多く、")
    print("木は『まだ分けられる場所』として使ってしまうためです（高カーディナリティへの偏り）。")
    print("評価データの permutation importance だけが 0 に近い値を返し、この列を正しく捨てられます。")


if __name__ == "__main__":
    main()
