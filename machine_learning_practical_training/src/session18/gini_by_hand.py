"""ジニ係数（不純度）で分岐を決めるしくみを、20 件の小さな表で手でたどる。

使い方:
    docker compose exec lab python src/session18/gini_by_hand.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import OUT_DIR, TARGET, gini, root_split_of, toy_candidates, toy_frame, toy_matrix


def print_toy_table(df) -> None:
    """20 件の表をそのまま表示する（この表だけで分岐の計算が追える）。"""
    print("番号 | カテゴリ | 単価 | 本文長 | 高評価")
    for row in df.itertuples(index=False):
        mark = "○" if row.is_high == 1 else "×"
        print(f"{row.book_no:>4} | {row.category:<5} | {row.unit_price:>5,} | {row.body_length:>6} | {mark}")


def plot_decrease(candidates: list[dict], path) -> None:
    """候補ごとのジニ係数の減少量を横棒で並べる（長いほど良い分岐）。"""
    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    names = [row["name"] for row in candidates]
    values = [row["decrease"] for row in candidates]
    best = max(values)
    colors = ["#e45756" if value == best else "#a9b7c6" for value in values]
    positions = list(range(len(names)))
    ax.barh(positions, values, color=colors)
    ax.set_yticks(positions)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlabel("ジニ係数の減少量（大きいほど良い分岐）")
    ax.set_title("決定木は「不純度がいちばん下がる分岐」を選ぶ")
    for position, value in zip(positions, values):
        ax.text(value + 0.004, position, f"{value:.4f}", va="center")
    ax.set_xlim(0, best * 1.25)
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    df = toy_frame()
    high = int(df[TARGET].sum())
    parent = gini(df[TARGET])

    print("■ 不純度を手で計算する（20 件の小さな例）")
    print_toy_table(df)
    print()
    print(f"全体 {len(df)} 件（高評価 {high} 件 / 低評価 {len(df) - high} 件）")
    print(f"親のジニ係数 = 1 - ({high}/{len(df)})^2 - ({len(df) - high}/{len(df)})^2 = {parent:.4f}")
    print()

    candidates = toy_candidates(df)
    print("■ 候補の分岐を比べる（親のジニ係数からどれだけ下がるか）")
    for row in candidates:
        print(row["name"])
        print(
            f"   満たす側 {row['n_left']} 件（高 {row['high_left']} / 低 {row['low_left']}）"
            f"ジニ {row['gini_left']:.4f}"
            f" ／ 満たさない側 {row['n_right']} 件（高 {row['high_right']} / 低 {row['low_right']}）"
            f"ジニ {row['gini_right']:.4f}"
        )
        print(f"   加重平均 {row['weighted']:.4f} → ジニ係数の減少 {row['decrease']:.4f}")
    print()

    best = max(candidates, key=lambda row: row["decrease"])
    print(f"■ いちばん良い候補: {best['name']}（減少 {best['decrease']:.4f}）")
    print()

    # 決定木は「人が思いつく境目」だけでなく、すべての特徴量 × すべての境目を試す
    matrix = toy_matrix(df)
    root = root_split_of(matrix, df[TARGET])
    print(f"■ scikit-learn が選んだ根の分岐（深さ 1 の決定木・候補の列は {matrix.shape[1]} 列）")
    print(f"{root['feature']} <= {root['threshold']:.1f}")
    print(f"親のジニ {root['parent_gini']:.4f} → 減少 {root['decrease']:.4f}")
    print(f"手で選んだ候補と一致したか: {round(root['decrease'], 4) == round(best['decrease'], 4)}")
    print()

    plot_decrease(candidates, OUT_DIR / "s18_gini_toy.png")
    print("図を保存しました: outputs/s18_gini_toy.png")


if __name__ == "__main__":
    main()
