#!/usr/bin/env python3
"""学習の実測（ステップ時間・メモリ・学習対象パラメータ数）。

セッション5〜7で本文に書く数値の出典。GPU を使わないので、
「何分で終わるか」を読者が自分の環境で見積もれるようにするのが目的。

  python tools/bench_train.py                # 既定（fast モデルで短く）
  python tools/bench_train.py --model ja --steps 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ftkit.data import load  # noqa: E402
from ftkit.models import (  # noqa: E402
    FAST_MODEL, JA_MODEL, attach_lora, load_model, load_tokenizer, param_stats,
)
from ftkit.train import TrainConfig, train  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["fast", "ja"], default="fast")
    ap.add_argument("--steps", type=int, default=10)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--max-length", type=int, default=128)
    ap.add_argument("--task", choices=["classify", "format"], default="classify")
    args = ap.parse_args()

    model_name = FAST_MODEL if args.model == "fast" else JA_MODEL
    examples = load("train")
    tokenizer = load_tokenizer(model_name)

    print(f"モデル: {model_name}")
    print(f"設定  : steps={args.steps} batch={args.batch_size} "
          f"max_length={args.max_length} task={args.task}\n")

    for label, use_lora in (("フル微調整", False), ("LoRA (r=16)", True)):
        model = load_model(model_name)
        if use_lora:
            model = attach_lora(model)
        stats = param_stats(model)
        print(f"--- {label} ---")
        print(f"学習対象: {stats['trainable'] / 1e6:.3f}M / 全体 {stats['total'] / 1e6:.1f}M "
              f"= {stats['ratio'] * 100:.2f}%")
        config = TrainConfig(task=args.task, batch_size=args.batch_size,
                             max_length=args.max_length, max_steps=args.steps, log_every=5)
        result = train(model, tokenizer, examples, config)
        print(result.summary())
        n_full = len(examples) // args.batch_size
        print(f"1エポック（{n_full} step）の見積もり: "
              f"{n_full * result.median_step_seconds / 60:.1f} 分\n")
        result.save(f"bench_{args.model}_{'lora' if use_lora else 'full'}")
        del model


if __name__ == "__main__":
    main()
