"""課題6 の解答: リークを再現し、自分のモデルが跳ねていないかを点検する。

実行:
    docker compose exec lab python src/mid02/leak_audit.py
"""

from __future__ import annotations

from common import load_order_table
from features import LEAK_COLUMN, add_all_features, run_steps

# PR-AUC がこの幅を超えて跳ねた段階はリークを疑う（喜ぶ前に確認する）
JUMP_LIMIT = 0.10

CHECKLIST = [
    "その列は、予測する時点で手に入るか（注文が入った直後に分かる値か）",
    "その列の計算に、その行自身の結果（is_canceled）が入っていないか",
    "集約して作った列は「その注文より前」だけを見ているか（shift を入れたか）",
    "前処理（標準化・欠損の補完・特徴量の選択）を分割の前にやっていないか",
    "指標が急に跳ねたとき、それを喜ぶ前に 1〜4 を確認したか",
]


def audit() -> dict[str, object]:
    """⑥ と ⑦ を比べ、跳ねた段階を洗い出し、リークの仕組みを数値で示す。"""
    df = add_all_features(load_order_table())
    results = run_steps(df)
    by_key = {result["key"]: result for result in results}
    clean, leaked = by_key["⑥"], by_key["⑦"]

    # 前の段階からの PR-AUC の増減を並べ、跳ねた段階だけを拾う
    jumps = [
        {"key": current["key"], "jump": current["pr_auc"] - previous["pr_auc"]}
        for previous, current in zip(results, results[1:])
    ]
    suspicious = [row for row in jumps if row["jump"] > JUMP_LIMIT]

    zero_rows = df.loc[df[LEAK_COLUMN] == 0]
    return {
        "clean": clean,
        "leaked": leaked,
        "roc_jump": leaked["roc_auc"] - clean["roc_auc"],
        "pr_ratio": leaked["pr_auc"] / clean["pr_auc"],
        "jumps": jumps,
        "suspicious_keys": [row["key"] for row in suspicious],
        "max_other_jump": max(row["jump"] for row in jumps if row["jump"] <= JUMP_LIMIT),
        # その行自身の is_canceled が all_time_cancels に入っていることの確認
        "self_included": bool((df.loc[df["is_canceled"] == 1, LEAK_COLUMN] >= 1).all()),
        "zero_rows_cancel_rate": float(zero_rows["is_canceled"].mean()),
        "past_cancels_zero_rate": float(df.loc[df["past_cancels"] == 0, "is_canceled"].mean()),
    }


def main() -> None:
    facts = audit()
    clean, leaked = facts["clean"], facts["leaked"]

    print("■ 1. やってはいけない例（全期間のキャンセル数を特徴量にする）")
    print(f"{clean['label']} : ROC AUC {clean['roc_auc']:.4f} / PR-AUC {clean['pr_auc']:.4f}")
    print(f"{leaked['label']} : ROC AUC {leaked['roc_auc']:.4f} / PR-AUC {leaked['pr_auc']:.4f}")
    print(f"差 : ROC AUC +{facts['roc_jump']:.3f} / PR-AUC {facts['pr_ratio']:.1f} 倍")
    print()

    print("■ 2. なぜ跳ねるのか")
    print(f"{LEAK_COLUMN} にその行自身の is_canceled が入っているか : {facts['self_included']}")
    print(f"{LEAK_COLUMN} が 0 の行のキャンセル率 : {facts['zero_rows_cancel_rate']:.2%}")
    print(f"past_cancels が 0 の行のキャンセル率は 0% ではない : "
          f"{facts['past_cancels_zero_rate'] > 0}")
    print(f"→ {LEAK_COLUMN} が 0 なら「この注文はキャンセルされていない」と確定してしまいます")
    print()

    print(f"■ 3. どの段階で跳ねたか（PR-AUC が +{JUMP_LIMIT} を超えて増えた段階を疑う）")
    print(f"疑う段階 : {' '.join(facts['suspicious_keys'])}"
          f"（+{facts['leaked']['pr_auc'] - facts['clean']['pr_auc']:.2f}）")
    print(f"それ以外の段階の増減は最大でも +{facts['max_other_jump']:.2f}"
          "（③〜⑥ はむしろ下がっています）")
    print("→ 採用するのは ② の 5 列。跳ねた ⑦ は捨てます")
    print()

    print("■ 4. リーク点検のチェックリスト")
    for index, item in enumerate(CHECKLIST, start=1):
        print(f"{index}. {item}")


if __name__ == "__main__":
    main()
