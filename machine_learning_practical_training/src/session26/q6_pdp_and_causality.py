"""問題6: 部分依存プロットを描き、「解釈 ≠ 因果」のチェックリストで 3 列を判定する。

使い方:
    docker compose exec lab python src/session26/q6_pdp_and_causality.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import GRID_RESOLUTION, pdp_int_error, pdp_table, permutation_table, save_figure

TARGETS = [("unit_price", "単価（円）"), ("body_length", "レビュー本文の長さ（文字）")]

# チェックリストの判定（permutation の値だけをモデルから取り、残りは業務の知識で決める）
JUDGEMENTS = [
    {
        "feature": "unit_price",
        "before": "はい",
        "is_outcome": "いいえ",
        "can_act": "はい",
        "verdict": "予測に使える。値付けの検討にも使えるが、効果の確認は実験が必要",
    },
    {
        "feature": "body_length",
        "before": "いいえ",
        "is_outcome": "はい",
        "can_act": "形式的には可能",
        "verdict": "予測に使うのも危険（星を付けたあとに決まる量・セッション22）",
    },
    {
        "feature": "published_year",
        "before": "はい",
        "is_outcome": "いいえ",
        "can_act": "いいえ",
        "verdict": "予測にも効かない（permutation はほぼ 0・p 値 0.2425）",
    },
]


def judge() -> list[dict]:
    """判定表に permutation importance（評価データ）の値を差し込む。"""
    perm = permutation_table("test").set_index("feature")
    return [dict(item, permutation=float(perm.loc[item["feature"], "mean"])) for item in JUDGEMENTS]


def draw(tables: dict, path_name: str) -> str:
    """2 つの列の部分依存を並べ、介入できるかどうかを図の表題に書き分ける。"""
    notes = {"unit_price": "動かせる（値付け）", "body_length": "動かしても意味がない"}
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.2))
    for ax, (feature, label) in zip(axes, TARGETS):
        table = tables[feature]
        ax.plot(table["grid"], table["average"], marker="o", color="#4c78a8")
        ax.set_ylim(0.0, 1.0)
        ax.set_xlabel(label)
        ax.set_ylabel("高評価と予測される確率の平均")
        ax.set_title(f"{feature}：{notes[feature]}")
        ax.grid(alpha=0.3)
    fig.suptitle("部分依存の形が似ていても、介入できるかどうかは別の問題")
    fig.tight_layout()
    path = save_figure(fig, path_name)
    plt.close(fig)
    return path.name


def main() -> None:
    print("■ 1. int 型のまま渡したときのエラー")
    message = pdp_int_error("unit_price")
    print(f"ValueError: {message.split(':', 1)[0]}: ...")
    print('対処: astype("float64") で float にしてから渡す')
    print()

    tables = {feature: pdp_table(feature) for feature, _ in TARGETS}
    for number, (feature, label) in enumerate(TARGETS, start=2):
        print(f"■ {number}. {feature} の部分依存（grid_resolution={GRID_RESOLUTION}・横軸は{label}）")
        print(f"{'動かす値':>8}{'高評価の確率の平均':>12}")
        for row in tables[feature].itertuples(index=False):
            print(f"{row.grid:>8,.0f}{row.average:>12.4f}")
        print()

    print("■ 4. チェックリストによる判定")
    print(f"{'列':<16}{'permutation':>12}  予測時点より前  結果の一部  介入できる")
    for item in judge():
        print(
            f"{item['feature']:<16}{item['permutation']:>12.4f}  {item['before']:<14}"
            f"{item['is_outcome']:<12}{item['can_act']}"
        )
    print()
    for item in judge():
        print(f"{item['feature']}: {item['verdict']}")
    print()
    print("■ 5. 結論")
    print("部分依存プロットが右下がりでも、『単価を下げれば星が上がる』とは言えません。")
    print("図が示しているのは『単価の低い本を選ぶと、モデルは高評価と予測しやすい』という関係だけです。")
    print("原因を知りたいときは、値付けを変えて結果を観測する実験（A/B テスト）が必要です。")

    name = draw(tables, "s26_q6_pdp.png")
    print(f"図を保存しました: outputs/{name}")


if __name__ == "__main__":
    main()
