#!/usr/bin/env python3
"""問題3：索引作成の所要時間を見積もり、実測と突き合わせて外れ方を測る。

計算に使う数値はすべて実測値です（2026-08-15 / aarch64 / CPU 2コア / メモリ 5.8GB /
Python 3.12.13）。埋め込みも索引作成もこのスクリプトでは行いません（計算だけ）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fusion_lab import index_seconds  # noqa: E402

# tools/bench_embed.py の実測（passage 200件をバッチサイズを変えて符号化）
BATCH = [(8, 10.27), (16, 12.46), (32, 13.08)]
MS_PER_CHUNK = 56.8  # 673件を 38.21 秒で符号化したときの1件あたり

# tools/chunk_stats.py の実測（方式 -> (チャンク数, 平均文字数)）
CHUNKS = {
    "fixed(400/80)": (673, 301),
    "fixed(800/160)": (373, 497),
    "sentence(400)": (628, 276),
    "heading(600)": (2004, 101),
    "parent_window(200/600)": (1007, 172),
}

# tools/eval_matrix.py が記録した索引作成の実測（秒）
MEASURED = {"fixed(400/80)": 56.6, "heading(600)": 36.8}


def main() -> None:
    print("--- バッチサイズとスループット（passage 200件）---")
    print(f"{'batch':>6}{'秒':>8}{'ms/件':>9}{'件/秒':>9}")
    for batch, sec in BATCH:
        print(f"{batch:>6}{sec:>8.2f}{sec / 200 * 1000:>9.1f}{200 / sec:>9.1f}")
    print("  バッチを大きくするほど遅くなっています（2コアの CPU では GPU の常識が反転します）")

    print("\n--- 件数モデルによる見積もりと実測 ---")
    print(f"{'方式':<24}{'件数':>7}{'平均字':>7}{'見積もり秒':>12}{'実測秒':>9}{'ずれ':>8}")
    for name, (n, avg) in CHUNKS.items():
        est = index_seconds(n, MS_PER_CHUNK)
        actual = MEASURED.get(name)
        gap = f"{est / actual:.2f}倍" if actual else "-"
        print(f"{name:<24}{n:>7}{avg:>7}{est:>12.1f}"
              f"{(f'{actual:.1f}' if actual else '-'):>9}{gap:>8}")

    print("\n--- 2つの方式を比べる ---")
    n_fixed, avg_fixed = CHUNKS["fixed(400/80)"]
    n_head, avg_head = CHUNKS["heading(600)"]
    print(f"  件数の比 heading/fixed       : {n_head / n_fixed:.3f} 倍")
    print(f"  総文字数の比 heading/fixed   : "
          f"{(n_head * avg_head) / (n_fixed * avg_fixed):.3f} 倍"
          f"（{n_head * avg_head:,} 字 / {n_fixed * avg_fixed:,} 字）")
    print(f"  実測時間の比 heading/fixed   : "
          f"{MEASURED['heading(600)'] / MEASURED['fixed(400/80)']:.3f} 倍")
    print("  件数モデルも文字数モデルも実測を当てられていません")

    print("\n--- 10万チャンクの見積もり ---")
    print(f"  {index_seconds(100_000, MS_PER_CHUNK) / 60:.1f} 分"
          "（前提：fixed(400/80) と同じ長さのチャンク・batch=16・CPU 2コア・"
          "モデルのロードと登録は含まない）")


if __name__ == "__main__":
    main()
