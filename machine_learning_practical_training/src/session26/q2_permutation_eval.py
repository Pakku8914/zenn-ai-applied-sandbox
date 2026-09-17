"""問題2: permutation importance を評価データで計算し、ばらつきつきで並べる。

使い方:
    docker compose exec lab python src/session26/q2_permutation_eval.py
"""

from __future__ import annotations

from common import N_REPEATS, SCORING, fitted, permutation_table


def summary() -> dict:
    """評価データの permutation importance をまとめ、負の列とばらつき最大の列を拾う。"""
    table = permutation_table("test")
    return {
        "table": table,
        "n_test": len(fitted()["X_test"]),
        "top": str(table.iloc[0]["feature"]),
        "negative": table.loc[table["mean"] < 0, "feature"].tolist(),
        "widest": str(table.loc[table["std"].idxmax(), "feature"]),
        # 平均が標準偏差の 2 倍より大きい列を「ばらつきを踏まえても効いている」とみなす
        "solid": table.loc[table["mean"] > 2 * table["std"], "feature"].tolist(),
    }


def main() -> None:
    result = summary()

    print(f"■ 1. permutation importance（評価データ {result['n_test']:,} 件・scoring={SCORING}・n_repeats={N_REPEATS}）")
    print(f"{'順位':<4}{'特徴量':<16}平均の低下 ± ばらつき")
    for rank, row in enumerate(result["table"].itertuples(index=False), start=1):
        print(f"{str(rank) + '位':<4}{row.feature:<16}{row.mean:+.4f} ± {row.std:.4f}")
    print()

    print("■ 2. 読み取り")
    print(f"1 位の列              : {result['top']}")
    print(f"マイナスになった列    : {result['negative']}")
    print(f"ばらつきが最大の列    : {result['widest']}")
    print(f"ばらつきを踏まえても効いている列: {result['solid']}")
    print()
    print("説明: マイナスは『壊したのに性能が上がった』という意味です。")
    print("      その列が予測に使われていないとき、シャッフルの当たり外れだけが残るので符号は揺れます。")
    print("      0 と読むのが正しく、『邪魔をしている』とは読みません。")
    print("      One-Hot で開いた 5 列ではなく category が 1 行になっているのは、")
    print("      Pipeline ごと渡して『前処理より前の列』をシャッフルしているからです。")


if __name__ == "__main__":
    main()
