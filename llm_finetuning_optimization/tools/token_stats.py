#!/usr/bin/env python3
"""トークナイザの比較（セッション4の実測値の出典）。

同じ日本語テキストが、モデルによって何トークンになるかを測る。
英語中心のトークナイザは日本語で膨らみ、コストと max_length の設計に直接影響する。
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ftkit.data import load  # noqa: E402
from ftkit.models import FAST_MODEL, JA_MODEL, load_tokenizer  # noqa: E402
from ftkit.tokenize import token_report  # noqa: E402


def main() -> None:
    examples = load("train")[:100]
    print(f"{'モデル':<34}{'指示+質問':>12}{'回答':>8}{'合計':>8}{'文字/トークン':>14}")
    print("-" * 78)
    for model_name in (FAST_MODEL, JA_MODEL):
        tokenizer = load_tokenizer(model_name)
        rows = [token_report(tokenizer, ex, "format") for ex in examples]
        prompt = statistics.mean(r["prompt_tokens"] for r in rows)
        answer = statistics.mean(r["answer_tokens"] for r in rows)
        cpt = statistics.mean(r["chars_per_token"] for r in rows)
        print(f"{model_name:<34}{prompt:>12.1f}{answer:>8.1f}{prompt + answer:>8.1f}{cpt:>14.2f}")

    print("\n=== 語彙サイズ ===")
    for model_name in (FAST_MODEL, JA_MODEL):
        tokenizer = load_tokenizer(model_name)
        print(f"{model_name:<34}{len(tokenizer):>10,}")

    print("\n=== 同じ文の分割を見る ===")
    sample = "有給休暇の申請はいつまでですか"
    for model_name in (FAST_MODEL, JA_MODEL):
        tokenizer = load_tokenizer(model_name)
        ids = tokenizer(sample, add_special_tokens=False)["input_ids"]
        pieces = [tokenizer.decode([i]) for i in ids]
        print(f"{model_name}")
        print(f"  {len(ids)} トークン: {' | '.join(pieces)}")


if __name__ == "__main__":
    main()
