#!/usr/bin/env python3
"""日本語トークナイズの2方式を見比べる。

文字 bi-gram は「表記が似ている語」を救うが「文字列を共有しない略語」は救えない。
この非対称がセッション5の中心的な事実なので、まず机上で確認する。

    python src/session05/tokens_demo.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.tokenize_ja import tokens_bigram, tokens_morph  # noqa: E402

WORDS = ["多要素認証", "二要素認証", "MFA", "有給休暇", "年休", "MN-Book13", "MN-Book15"]
PAIRS = [("多要素認証", "二要素認証"), ("多要素認証", "MFA"),
         ("有給休暇", "年休"), ("MN-Book13", "MN-Book15")]
SAMPLE = "有給休暇の申請期限を教えてください"
PARTICLES = ("の", "を", "は", "が", "に", "で")
STOPWORDS = ("こと", "もの", "ため", "する", "ある")
KANA_ONE = re.compile(r"[ぁ-んァ-ヶー]")


def main() -> None:
    print("--- 文字 bi-gram ---")
    for w in WORDS:
        print(f"{w} -> {tokens_bigram(w)}")

    print("\n--- 共有する bi-gram の数 ---")
    for a, b in PAIRS:
        shared = sorted(set(tokens_bigram(a)) & set(tokens_bigram(b)))
        print(f"{a} ∩ {b} = {len(shared)} 個 {shared}")

    print("\n--- 形態素解析の後処理（tokens_morph の性質）---")
    morph = tokens_morph(SAMPLE)
    print(f"助詞が残っているか: {any(t in PARTICLES for t in morph)}")
    print(f"ストップワードが残っているか: {any(t in STOPWORDS for t in morph)}")
    print(f"1文字のかなが残っているか: "
          f"{any(len(t) == 1 and KANA_ONE.fullmatch(t) is not None for t in morph)}")
    print(f"bi-gram の語数（{len(SAMPLE)}文字のクエリ）: {len(tokens_bigram(SAMPLE))}")

    # 語の並びそのものは辞書に依存する。--show を付けたときだけ表示する
    if "--show" in sys.argv:
        print("\n--- 実際の語の並び（辞書に依存するので自分の目で確かめる）---")
        print(f"morph : {morph}")
        print(f"bigram: {tokens_bigram(SAMPLE)}")


if __name__ == "__main__":
    main()
