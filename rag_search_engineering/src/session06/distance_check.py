#!/usr/bin/env python3
"""正規化と距離尺度の対応を確かめる（セッション6・問題2）。

罠：このモデルは Normalize を最終段に内蔵しているため、
normalize_embeddings=False を渡してもノルムは 1 のまま（フラグが素通りする）。
生のプーリング出力を見るには Normalize を外したモデルを組み直すしかない。

正規化済みなら 内積 = コサイン、ユークリッド距離^2 = 2 - 2×内積。
危険なのは「正規化していないのに内積を使う」組み合わせだけ。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

from ragkit.dense import Embedder  # noqa: E402

EPS = 1e-4
TEXTS = ["query: 年休の手続き", "passage: 有給休暇の申請手続き"]


def main() -> None:
    model = Embedder.get()
    modules = [type(m).__name__ for m in model]

    normed = model.encode(TEXTS, normalize_embeddings=True, show_progress_bar=False)
    flagged = model.encode(TEXTS, normalize_embeddings=False, show_progress_bar=False)
    # 最終段の Normalize を外して組み直すと、初めて生のプーリング出力が得られる
    pooled = SentenceTransformer(modules=list(model)[:2]).encode(
        TEXTS, show_progress_bar=False)

    dot_normed = float(np.dot(normed[0], normed[1]))
    n0, n1 = float(np.linalg.norm(pooled[0])), float(np.linalg.norm(pooled[1]))
    dot_pooled = float(np.dot(pooled[0], pooled[1]))
    cos_pooled = dot_pooled / (n0 * n1)
    d2 = float(np.sum((normed[0] - normed[1]) ** 2))
    ok = abs(d2 - (2 - 2 * dot_normed)) < EPS

    print(f"モデルの構成                          : {' → '.join(modules)}")
    print(f"normalize_embeddings=True のノルム    : {float(np.linalg.norm(normed[0])):.4f}")
    print(f"normalize_embeddings=False のノルム   : {float(np.linalg.norm(flagged[0])):.4f}"
          "  <- フラグは素通りする")
    print(f"Normalize を外したときのノルム        : {n0:.4f} / {n1:.4f}")
    print(f"Normalize を外したときの内積          : {dot_pooled:.4f}")
    print(f"同じペアのコサイン                    : {cos_pooled:.4f}")
    print(f"正規化済みベクトルの内積              : {dot_normed:.4f}")
    print(f"ユークリッド距離^2 == 2 - 2×内積      : {'一致' if ok else '不一致'}"
          f" ({d2:.4f} == {2 - 2 * dot_normed:.4f})")


if __name__ == "__main__":
    main()
