"""「最良」は誤差の中で入れ替わる ― 差とばらつきを並べて見る（本文 5 節）。

判定そのもの（analyze）は学習しません。grid_search.search() が返した表を読み直すだけです
（main では表を作るために探索を 1 回走らせます）。

実行:
    docker compose exec lab python src/session23/score_noise.py
"""

from __future__ import annotations

from common import format_params, load_review_table
from default_baseline import baseline
from grid_search import search as run_grid_search


def analyze(grid_result: dict, baseline_mean: float) -> dict[str, object]:
    """上位 3 件の差・標準偏差・最下位との差を並べ、「差が誤差に埋もれるか」を判定する。"""
    table = grid_result["table"]
    top3 = table[:3]
    best, second, third = top3
    worst = table[-1]
    bands = [(row["mean"] - row["std"], row["mean"] + row["std"]) for row in top3]
    # 上位 3 件の「平均 ± 標準偏差」の帯が、最良の帯と重なっているか
    overlap = all(low <= bands[0][1] and bands[0][0] <= high for low, high in bands[1:])
    return {
        "top3": top3,
        "worst": worst,
        "bands": bands,
        "best_std": best["std"],
        "gap_to_second": best["mean"] - second["mean"],
        "gap_to_third": best["mean"] - third["mean"],
        "gap_to_worst": best["mean"] - worst["mean"],
        "gap_to_baseline": best["mean"] - baseline_mean,
        "top3_within_noise": (best["mean"] - third["mean"]) < best["std"],
        "worst_beyond_noise": (best["mean"] - worst["mean"]) > 2 * best["std"],
        "bands_overlap": bool(overlap),
    }


def main() -> None:
    df = load_review_table()
    grid_result = run_grid_search(df)
    baseline_result = baseline(df)
    result = analyze(grid_result, float(baseline_result["mean"]))

    print("■ 上位 3 件と、その「平均 ± 標準偏差」の帯")
    print("設定                                             | CV の平均 | 標準偏差 | 帯")
    for row, (low, high) in zip(result["top3"], result["bands"]):
        print(f"{format_params(row):<48} | {row['mean']:.4f}    | {row['std']:.4f}   | {low:.4f}〜{high:.4f}")
    print()

    print("■ 差をばらつきと比べる")
    print(f"1 位 − 2 位            : {result['gap_to_second']:.4f}")
    print(f"1 位 − 3 位            : {result['gap_to_third']:.4f}")
    print(f"1 位の標準偏差         : {result['best_std']:.4f}")
    print(f"上位 3 件の差は誤差の中 : {result['top3_within_noise']}")
    print(f"帯がすべて重なっている  : {result['bands_overlap']}")
    print()

    print("■ それでも「意味のある差」はある")
    print(f"1 位 − 最下位          : {result['gap_to_worst']:.4f}（標準偏差の 2 倍より大きい: {result['worst_beyond_noise']}）")
    print(f"1 位 − 探索なし        : {result['gap_to_baseline']:.4f}")
    print()
    print("小数第 3 位の差で勝ち負けを語らないこと。順位表の上のほうは誤差で入れ替わります。")


if __name__ == "__main__":
    main()
