#!/usr/bin/env python3
"""LoRA を統合して GGUF 変換の入力（HF形式）を書き出す（セッション10）。

  # 135M（速い・約 513MB）
  python src/session10/merge_for_gguf.py --model fast --name smol135m
  # 0.5B（本文の実測と同じ経路。fp32 では既定環境で落ちるので bf16 で読む）
  python src/session10/merge_for_gguf.py --model ja --dtype bf16 --name qwen05b
  # 学習済みアダプタを統合する
  python src/session10/merge_for_gguf.py --model ja --dtype bf16 --name qwen05b \
      --adapter export/session06/adapter_classify

--adapter を渡さない場合は「初期化直後（B=0 なので差分ゼロ）の LoRA」を統合するので、
中身は元のモデルとまったく同じになる。**変換手順の確認とサイズの実測にはこれで十分**で、
品質を測るときは必ず学習済みアダプタを渡すこと。

書き出し先は export/{name}/。**既存の同名ディレクトリは削除される**
（ftkit.quantize.save_merged が rmtree してから書く）。

書き出したらこの Python プロセスを終了させ、別コンテナで変換する:

  docker compose run --rm llamacpp --convert --outtype f16 /work/export/qwen05b
"""

from __future__ import annotations

import argparse
import gc
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.models import (  # noqa: E402
    FAST_MODEL,
    JA_MODEL,
    attach_lora,
    load_model,
    load_tokenizer,
    param_stats,
)
from ftkit.quantize import dir_size_mb, save_merged  # noqa: E402
from ftkit.train import set_seed  # noqa: E402

DTYPES = {"fp32": torch.float32, "bf16": torch.bfloat16}


def main() -> int:
    parser = argparse.ArgumentParser(description="LoRA を統合して GGUF 変換の入力を作る")
    parser.add_argument("--model", choices=("fast", "ja"), default="fast")
    parser.add_argument("--dtype", choices=tuple(DTYPES), default="fp32")
    parser.add_argument("--adapter", default=None, help="学習済みアダプタのディレクトリ")
    parser.add_argument("--name", default=None, help="export/{name}/ に書き出す")
    parser.add_argument("--seed", type=int, default=20260815)
    args = parser.parse_args()

    model_name = FAST_MODEL if args.model == "fast" else JA_MODEL
    out_name = args.name or ("smol135m" if args.model == "fast" else "qwen05b")

    tokenizer = load_tokenizer(model_name)
    set_seed(args.seed)                      # モデル構築の前に呼ぶ（再現性）
    base = load_model(model_name, dtype=DTYPES[args.dtype])

    if args.adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(base, args.adapter)
        print(f"アダプタを読み込みました: {args.adapter}")
    else:
        model = attach_lora(base)
        print("アダプタ未指定：差分ゼロの LoRA を統合します（中身は元のモデルと同じ）")

    stats = param_stats(model)
    print(f"パラメータ: 学習対象 {stats['trainable']:,} / 全体 {stats['total']:,}")

    out = save_merged(model, tokenizer, out_name)
    print(f"書き出し: {out}  {dir_size_mb(out):.1f} MB  (dtype={args.dtype})")

    del model, base
    gc.collect()

    print("この Python を終了させたうえで、別コンテナで変換してください:")
    print(f"  docker compose run --rm llamacpp --convert --outtype f16 /work/export/{out_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
