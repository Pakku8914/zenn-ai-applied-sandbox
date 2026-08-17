#!/usr/bin/env python3
"""問題2：「正規化」という同じ言葉が指している4つの別物を突き合わせる。

  ① 文字の正規化（S03）        ＮＦＫＣ・小文字化。保存用と索引用で役割が違う
  ② 索引用の正規化（S03 × S05） ragkit.tokenize_ja.normalize。辞書の照合もこれを通す
  ③ ベクトルの L2正規化（S06）  長さを1にする。距離尺度の選択と対で意味を持つ
  ④ スコアの正規化（S08）        min-max。尺度の違う2つのスコアを混ぜるための変換

既存のコレクションからベクトルを読み出すだけなので、埋め込みは作り直しません。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from fusion_lab import load_vectors, query_vector  # noqa: E402

from ragkit.dense import DenseIndex, Embedder  # noqa: E402
from ragkit.tokenize_ja import normalize  # noqa: E402

COLLECTION = "minato_docs_fixed"
SAMPLES = ["ＭＦＡ", "Ｗｉ－Ｆｉ", "有給休暇 　の　申請", "PASSWORD"]


def main() -> None:
    print("--- ① / ② 文字の正規化（S03 × S05）---")
    for s in SAMPLES:
        print(f"  {s!r} -> {normalize(s)!r}")

    print("\n--- ③ ベクトルの L2正規化（S06）---")
    vec = Embedder.encode_query("有給休暇の申請期限")
    print(f"  encode_query のノルム: {float(np.linalg.norm(vec)):.6f}")
    flagged = Embedder.get().encode(
        "query: 有給休暇の申請期限", normalize_embeddings=False, show_progress_bar=False
    )
    print(f"  normalize_embeddings=False のノルム: {float(np.linalg.norm(flagged)):.6f}"
          "（このモデルは Normalize を内蔵しているので外れない）")

    idx = DenseIndex(COLLECTION)
    ids, mat = load_vectors(idx)
    q = np.asarray(query_vector("有給休暇の申請期限"), dtype="float32")
    dot = mat @ q
    cos = dot / (np.linalg.norm(mat, axis=1) * float(np.linalg.norm(q)))
    euc2 = np.sum((mat - q) ** 2, axis=1)
    print(f"  コレクションから読んだベクトル: {len(ids)} 件 / {mat.shape[1]} 次元")
    print(f"  |内積 - コサイン| の最大: {float(np.max(np.abs(dot - cos))):.8f}")
    print(f"  |ユークリッド距離^2 - (2 - 2×内積)| の最大: "
          f"{float(np.max(np.abs(euc2 - (2 - 2 * dot)))):.8f}")
    for label, order in [("内積", np.argsort(-dot)), ("コサイン", np.argsort(-cos)),
                         ("ユークリッド", np.argsort(euc2))]:
        print(f"  {label:<12}上位3件: {[ids[i] for i in order[:3]]}")

    print("\n--- 正規化されていないベクトルに内積を使うと壊れる ---")
    scale = 1.0 + (np.arange(len(mat)) % 5) * 0.5  # 1.0〜3.0 の長さの違いを人工的に作る
    skewed = mat * scale[:, None]
    dot_s = skewed @ q
    cos_s = dot_s / (np.linalg.norm(skewed, axis=1) * float(np.linalg.norm(q)))
    print(f"  内積の上位3件（長さがそろっていない）: "
          f"{[ids[i] for i in np.argsort(-dot_s)[:3]]}")
    print(f"  コサインの上位3件（長さの影響を受けない）: "
          f"{[ids[i] for i in np.argsort(-cos_s)[:3]]}")


if __name__ == "__main__":
    main()
