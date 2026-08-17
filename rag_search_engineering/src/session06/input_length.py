#!/usr/bin/env python3
"""最大入力長を超えた入力が黙って切り捨てられることを検出する（セッション6・問題3）。

検出方法は2つ。
  (1) トークナイザで数える（prefix ぶんも数に入れる）
  (2) 先頭が同じで末尾だけ違う長文2本の埋め込みが一致するかを見る
      → 一致するなら末尾は読まれていない。API 型のモデルでも使える方法。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.getLogger("transformers").setLevel(logging.ERROR)  # 長文入力の警告を抑える

import numpy as np  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.dense import Embedder  # noqa: E402

LONG_PREFIX = "みなと商事の社内規程について説明します。" * 200  # 20字 × 200 = 4,000字
TAIL_A = "最後に、駐車場の月額利用料は経費精算の対象外です。"
TAIL_B = "最後に、有給休暇の申請は3営業日前までに行ってください。"


def main() -> None:
    model = Embedder.get()
    tok = model.tokenizer
    limit = int(model.max_seq_length)

    print(f"モデルの最大入力長                   : {limit} トークン")

    n_long = len(tok(f"passage: {LONG_PREFIX}")["input_ids"])
    print("4,000字の入力                        : "
          + ("最大入力長を超える" if n_long > limit else "最大入力長に収まる"))

    va, vb = Embedder.encode_passages([LONG_PREFIX + TAIL_A, LONG_PREFIX + TAIL_B])
    print(f"末尾だけ違う長文2本の内積            : {float(np.dot(va, vb)):.4f}"
          "  <- 1.0000 なら末尾は読まれていない")

    chunks = chunk_all(load_docs(), "fixed", size=400, overlap=80)
    over = [c.chunk_id for c in chunks
            if len(tok(f"passage: {c.text}")["input_ids"]) > limit]
    print(f"fixed(400/80) のチャンク数           : {len(chunks)}")
    print(f"うち最大入力長を超えるチャンク       : {len(over)} 件")
    if over:
        print(f"  超過したチャンク（先頭5件）: {over[:5]}")


if __name__ == "__main__":
    main()
