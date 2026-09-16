#!/usr/bin/env python3
"""環境構築の最終確認：10 step だけ学習して loss が動くのを見る。

学習の入口として最小限のことしかしない。評価もしない（それは本文で扱う）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import torch

from ftkit.data import build_prompt, build_target, load
from ftkit.models import FAST_MODEL, attach_lora, load_model, load_tokenizer, param_stats
from ftkit.tokenize import encode_example, masked_ratio
from ftkit.train import TrainConfig, set_seed, train

print(f"torch: {torch.__version__}")
print(f"CUDA が使えるか: {torch.cuda.is_available()}（本書では使いません）\n")

examples = load("train")
tokenizer = load_tokenizer(FAST_MODEL)
print(f"学習データ: {len(examples)} 件")
print(f"例: {build_prompt(examples[0], 'classify')[:40]}... -> "
      f"{build_target(examples[0], 'classify')}")

encoded = encode_example(tokenizer, examples[0], "classify", max_length=320)
print(f"トークン数: {len(encoded['input_ids'])} / "
      f"損失から外した割合: {masked_ratio(encoded):.3f}\n")

# シードはモデル構築の前に設定する（後にすると LoRA の初期化が再現しない）
set_seed(20260815)
model = attach_lora(load_model(FAST_MODEL), r=16)
stats = param_stats(model)
print(f"学習対象: {stats['trainable'] / 1e6:.3f}M / 全体 {stats['total'] / 1e6:.1f}M "
      f"= {stats['ratio'] * 100:.2f}%\n")

result = train(model, tokenizer, examples,
               TrainConfig(task="classify", batch_size=2, max_length=320,
                           max_steps=20, log_every=10))
print(f"\n{result.summary()}")
