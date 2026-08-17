#!/usr/bin/env python3
"""失敗の分解表から「打ち手の層」を選ぶ。検索を実行しないので数秒で終わる。

数値は `src/review01/verify.py` の実測（2026-08-16 / bm25(morph) / fixed(400/80) /
aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13）をそのまま定数に写している。

  到達不足 = 1 − Recall@100     候補にすら入っていない → 語彙・入力側・索引側の問題
  順位不足 = Recall@100 − Recall@10  候補には居る → 並べ替え（リランク）の問題

実行:  docker compose exec app python src/review03/failure_math.py
"""

from __future__ import annotations

# クエリ型 -> {件数, Recall@10, 到達@100}
SPLIT: dict[str, dict[str, float]] = {
    "abbrev": {"n": 20.0, "recall": 0.182, "reach": 0.408},
    "keyword": {"n": 30.0, "recall": 0.967, "reach": 1.000},
    "multi_condition": {"n": 12.0, "recall": 0.452, "reach": 0.947},
    "natural": {"n": 36.0, "recall": 0.968, "reach": 0.995},
    "temporal": {"n": 12.0, "recall": 0.919, "reach": 1.000},
}
ALL: dict[str, float] = {"n": 110.0, "recall": 0.763, "reach": 0.885}

# 打ち手 -> 効く失敗の層。**層を先に決めてから打ち手を選ぶ**ための対応表
MOVE_LAYER: dict[str, str] = {
    "クエリ側の同義語展開": "reach",
    "索引側の同義語展開": "reach",
    "文字N-gramのトークナイザ": "reach",
    "密ベクトル検索を足す": "reach",
    "コーパスに文書を足す": "corpus",
    "リランク（クロスエンコーダ）": "rank",
    "スコア融合の重み調整": "rank",
    "生成に渡す件数を増やす": "rank",
}


def rank_loss(row: dict[str, float]) -> float:
    return row["reach"] - row["recall"]


def reach_loss(row: dict[str, float]) -> float:
    return 1.0 - row["reach"]


def dominant(row: dict[str, float]) -> str:
    """その型の失敗のうち、量が多いのはどちらか。"""
    return "reach" if reach_loss(row) > rank_loss(row) else "rank"


def moves_for(row: dict[str, float]) -> list[str]:
    """支配的な層に効く打ち手だけを返す。効かない層の打ち手は最初から挙げない。"""
    layer = dominant(row)
    return [name for name, target in MOVE_LAYER.items() if target == layer]


def weighted_mean(field: str, split: dict[str, dict[str, float]] | None = None) -> float:
    """型別の値を件数で重み付けして平均する。ALL の値と一致するはず。"""
    split = SPLIT if split is None else split
    total = sum(row["n"] for row in split.values())
    return sum(row["n"] * row[field] for row in split.values()) / total


def contribution(qtype: str, new_recall: float,
                 split: dict[str, dict[str, float]] | None = None) -> float:
    """その型だけを new_recall まで直したときの、全体の Recall@10 の増分。

    型の改善幅に **件数の比** を掛ける。ここを掛け忘れると、12件のクエリの改善を
    110件ぶんの改善として報告してしまう。
    """
    split = SPLIT if split is None else split
    row = split[qtype]
    return (new_recall - row["recall"]) * row["n"] / ALL["n"]


def overall_after(qtype: str, new_recall: float) -> float:
    return ALL["recall"] + contribution(qtype, new_recall)


def ceiling_for_type(qtype: str) -> float:
    """その型の順位不足をゼロにしたときの全体（＝並べ替えだけで届く上限）。"""
    return overall_after(qtype, SPLIT[qtype]["reach"])


def ceiling_rank_fixed() -> float:
    """すべての型の順位不足をゼロにしたときの全体の上限＝到達@100 そのもの。"""
    return ALL["reach"]


def print_table() -> None:
    print("[失敗の分解（bm25(morph) / fixed(400/80)・2026-08-16 実測 / "
          "aarch64 / CPU 2コア / メモリ 5.8GB）]")
    head = (f"{'型':<16}{'n':>5}{'Recall@10':>11}{'到達@100':>10}"
            f"{'順位不足':>10}{'到達不足':>10}{'支配的な層':>12}")
    print(head)
    for qtype in list(SPLIT) + ["ALL"]:
        row = SPLIT.get(qtype, ALL)
        layer = "到達不足" if dominant(row) == "reach" else "順位不足"
        print(f"{qtype:<16}{int(row['n']):>5}{row['recall']:>11.3f}{row['reach']:>10.3f}"
              f"{rank_loss(row):>10.3f}{reach_loss(row):>10.3f}{layer:>12}")

    print("\n[打ち手を選ぶ]")
    for qtype, row in SPLIT.items():
        print(f"  {qtype:<16} -> " + " / ".join(moves_for(row)))

    print("\n[直したときの全体への寄与]")
    print(f"  略語を 0.182 -> 0.873（クエリ側の同義語展開の実測）: "
          f"{contribution('abbrev', 0.873):+.3f} -> 全体 {overall_after('abbrev', 0.873):.3f}")
    print(f"  複数条件を 0.452 -> 0.947（順位不足をゼロにした上限）: "
          f"{contribution('multi_condition', 0.947):+.3f} -> "
          f"全体 {ceiling_for_type('multi_condition'):.3f}")
    print(f"  すべての型の順位不足をゼロ（並べ替えだけで届く上限）: "
          f"全体 {ceiling_rank_fixed():.3f}")

    print("\n[検算]")
    print(f"  件数で重み付けした Recall@10 = {weighted_mean('recall'):.3f}（ALL は "
          f"{ALL['recall']:.3f}）")
    print(f"  件数で重み付けした 到達@100  = {weighted_mean('reach'):.3f}（ALL は "
          f"{ALL['reach']:.3f}）")


if __name__ == "__main__":
    print_table()
