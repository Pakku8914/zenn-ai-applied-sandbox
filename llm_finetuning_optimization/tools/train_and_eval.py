#!/usr/bin/env python3
"""学習前後の指標を比較する（本書の中心的な実験）。

  python tools/train_and_eval.py --model fast --steps 60 --eval-n 60
  python tools/train_and_eval.py --model ja --steps 120 --eval-n 60 --task format

「loss が下がった」ではなく **タスクの指標**（分類の正解率・整形の遵守率）で
学習の成否を判断する。結果は runs/ に保存する。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ftkit.data import load  # noqa: E402
from ftkit.evaluate import evaluate  # noqa: E402
from ftkit.models import (  # noqa: E402
    FAST_MODEL, JA_MODEL, attach_lora, load_model, load_tokenizer, param_stats,
)
from ftkit.train import TrainConfig, train  # noqa: E402

RUNS = Path(__file__).resolve().parent.parent / "runs"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["fast", "ja"], default="fast")
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--eval-n", type=int, default=60)
    ap.add_argument("--task", choices=["classify", "format"], default="classify")
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-length", type=int, default=128)
    ap.add_argument("--dtype", choices=["fp32", "bf16"], default="fp32",
                    help="bf16 はメモリを半分にできる（既定の 5.8GB 環境で 0.5B を扱うときに使う）")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    model_name = FAST_MODEL if args.model == "fast" else JA_MODEL
    tokenizer = load_tokenizer(model_name)
    train_examples = load("train")
    test_examples = load("test")

    print(f"モデル: {model_name}")
    print(f"設定  : task={args.task} steps={args.steps} lora_r={args.lora_r} "
          f"lr={args.lr} max_length={args.max_length} eval_n={args.eval_n} dtype={args.dtype}\n")

    import torch

    dtype = torch.float32 if args.dtype == "fp32" else torch.bfloat16
    model = load_model(model_name, dtype=dtype)

    print("--- 学習前の評価 ---")
    t0 = time.perf_counter()
    before = evaluate(model, tokenizer, test_examples, args.task, limit=args.eval_n)
    print(f"{before.summary()}  （{time.perf_counter() - t0:.1f}s）")

    print("\n--- LoRA 学習 ---")
    model = attach_lora(model, r=args.lora_r)
    stats = param_stats(model)
    print(f"学習対象: {stats['trainable'] / 1e6:.3f}M / 全体 {stats['total'] / 1e6:.1f}M "
          f"= {stats['ratio'] * 100:.2f}%")
    config = TrainConfig(task=args.task, batch_size=2, lr=args.lr,
                         max_length=args.max_length, max_steps=args.steps, log_every=10)
    result = train(model, tokenizer, train_examples, config)
    print(result.summary())

    print("\n--- 学習後の評価 ---")
    t0 = time.perf_counter()
    after = evaluate(model, tokenizer, test_examples, args.task, limit=args.eval_n)
    print(f"{after.summary()}  （{time.perf_counter() - t0:.1f}s）")

    print("\n=== 比較 ===")
    print(f"{'指標':<14}{'学習前':>10}{'学習後':>10}{'差':>10}")
    print(f"{'正解率':<14}{before.accuracy:>10.3f}{after.accuracy:>10.3f}"
          f"{after.accuracy - before.accuracy:>+10.3f}")
    print(f"{'形式遵守率':<14}{before.format_rate:>10.3f}{after.format_rate:>10.3f}"
          f"{after.format_rate - before.format_rate:>+10.3f}")

    tag = args.tag or f"{args.model}_{args.task}_s{args.steps}"
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"compare_{tag}.json").write_text(json.dumps({
        "model": model_name, "dtype": args.dtype, "task": args.task, "steps": args.steps,
        "lora_r": args.lora_r, "lr": args.lr, "eval_n": args.eval_n,
        "trainable_params": stats["trainable"], "total_params": stats["total"],
        "median_step_seconds": result.median_step_seconds,
        "train_seconds": result.seconds, "peak_rss_gb": result.peak_rss_gb,
        "first_loss": result.first_loss, "last_loss": result.last_loss,
        "before": {"accuracy": before.accuracy, "format_rate": before.format_rate},
        "after": {"accuracy": after.accuracy, "format_rate": after.format_rate},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> runs/compare_{tag}.json")

    print("\n=== 学習後の混同表（正解 → 予測）===")
    table = after.confusion()
    keys = list(next(iter(table.values())).keys())
    print(f"{'':<12}" + "".join(f"{k:>8}" for k in keys))
    for gold, row in table.items():
        print(f"{gold:<12}" + "".join(f"{row[k]:>8}" for k in keys))


if __name__ == "__main__":
    main()
