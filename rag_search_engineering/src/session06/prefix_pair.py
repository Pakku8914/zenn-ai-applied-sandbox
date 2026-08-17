#!/usr/bin/env python3
"""prefix あり／なしで「1組のテキストの類似度」を比べる（セッション6・問題1）。

このスクリプトの結論は「prefix なしの方が高く出る」。
そこから「prefix は不要」と言ってはいけない理由がセッション6の主題。
効果を判定できるのは検索全体の順位だけ（tools/bench_prefix.py）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

from ragkit.dense import Embedder  # noqa: E402

QUERY = "年休の手続き"
PASSAGE = "有給休暇の申請手続き"
UNRELATED = "駐車場の月額利用料"


def main() -> None:
    # prefix あり（e5 の正しい使い方）
    q_with = Embedder.encode_query(QUERY)
    p_with, u_with = Embedder.encode_passages([PASSAGE, UNRELATED])

    # prefix なし（誤用）。正規化の有無という別の変数を混ぜないため normalize は付ける
    model = Embedder.get()
    q_raw, p_raw = model.encode([QUERY, PASSAGE], normalize_embeddings=True,
                                show_progress_bar=False)

    # 正規化済みなので内積がそのままコサイン類似度になる
    print(f"prefix あり : 「{QUERY}」×「{PASSAGE}」 = {float(np.dot(q_with, p_with)):.3f}")
    print(f"prefix あり : 「{QUERY}」×「{UNRELATED}」 = {float(np.dot(q_with, u_with)):.3f}")
    print(f"prefix なし : 「{QUERY}」×「{PASSAGE}」 = {float(np.dot(q_raw, p_raw)):.3f}")
    print("=> 1組の類似度では prefix の良し悪しは判定できない。順位で測り直すこと。")


if __name__ == "__main__":
    main()
