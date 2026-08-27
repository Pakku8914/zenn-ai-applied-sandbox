#!/usr/bin/env python3
"""メモリ予算から同時実行数を逆算する（セッション3・問題8の解答）。

予算・重みのサイズ・上乗せは **読者が入れる値** であり、本書の実測値ではない。
重みのサイズは、自分が使う GGUF の実ファイルサイズ（ls -l）を入れること。

  python src/session03/kv_budget.py --model llama8b --memory-gb 16 --weights-gb 5.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.kvcache import LLAMA_8B, QWEN_05B, kv_cache_bytes, max_concurrent  # noqa: E402

GB = 1024 ** 3
MB = 1024 ** 2
MODELS = {"qwen05b": QWEN_05B, "llama8b": LLAMA_8B}
SEQ_LENS = (1024, 2048, 4096, 8192)


def shape(name: str) -> dict:
    """kv_cache_bytes / max_concurrent に渡せる形（hidden を除く）にする。"""
    return {k: v for k, v in MODELS[name].items() if k != "hidden"}


def rows(name: str, kv_budget: int, bytes_per_elem: int = 2) -> list[tuple[int, float, int]]:
    """(系列長, 1本あたりのMB, 持てる本数) の一覧。"""
    out: list[tuple[int, float, int]] = []
    for seq_len in SEQ_LENS:
        one = kv_cache_bytes(seq_len=seq_len, batch=1, bytes_per_elem=bytes_per_elem,
                             **shape(name))
        out.append((seq_len, one.total_bytes / MB,
                    max_concurrent(kv_budget, seq_len, bytes_per_elem=bytes_per_elem,
                                   **shape(name))))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=sorted(MODELS), default="llama8b")
    ap.add_argument("--memory-gb", type=float, default=16.0)
    ap.add_argument("--weights-gb", type=float, default=5.0)
    ap.add_argument("--overhead-gb", type=float, default=1.5)
    args = ap.parse_args()

    kv_budget = int(args.memory_gb * GB) - int(args.weights_gb * GB) - int(args.overhead_gb * GB)

    print(f"=== メモリ予算（モデル: {args.model}）===")
    print(f"全体              : {args.memory_gb:>6.2f} GB  ← 入力値")
    print(f"重み              : {args.weights_gb:>6.2f} GB  ← 入力値（実ファイルサイズを入れる）")
    print(f"実装とOSの上乗せ  : {args.overhead_gb:>6.2f} GB  ← 入力値")
    print(f"KVキャッシュに使える: {kv_budget / GB:>6.2f} GB")

    if kv_budget <= 0:
        print("\n重みと上乗せだけで予算を使い切っている。同時実行は 0 本。"
              "予算を増やすか、量子化を強くすること。")
        return

    for bytes_per_elem, label in ((2, "f16（2バイト）"), (1, "1バイト型")):
        print(f"\n=== 系列長ごとに持てる同時実行数（KVキャッシュ {label}）===")
        for seq_len, one_mb, n in rows(args.model, kv_budget, bytes_per_elem):
            print(f"系列長 {seq_len:>4}: 1本 {one_mb:>6.1f} MB → 同時 {n:>3} 本")

    print("\n※ これは式による下限。実装の上乗せで実際は上振れする。"
          "起動ログの KV cache size と突き合わせること。")


if __name__ == "__main__":
    main()
