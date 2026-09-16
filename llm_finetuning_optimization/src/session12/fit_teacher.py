#!/usr/bin/env python3
"""教師をタスクに適合させる（蒸留の第0段）。

素の Qwen2.5-0.5B-Instruct は、指示を理解しても**定型を守りません**。
classify に通すと「この問い合わせは、経費や勤怠に関する問題」のような自由文を
返し、`make_teacher_data.py` の検証で全件落ちます（実測）。

蒸留は「教師の出力を正解として学習する」ので、**教師が定型を守れていないと
始まりません**。ここで教師を LoRA で SFT し、アダプタを書き出します。

  docker compose exec app python src/session12/fit_teacher.py --task classify --steps 40

書き出したアダプタは第1段で使います。

  docker compose exec app python src/session12/make_teacher_data.py \
      --task classify --n 24 --adapter export/session12/teacher_classify
"""

from __future__ import annotations

import argparse
import gc
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import load  # noqa: E402
from ftkit.evaluate import evaluate  # noqa: E402
from ftkit.models import JA_MODEL, attach_lora, load_model, load_tokenizer, param_stats  # noqa: E402
from ftkit.train import TrainConfig, set_seed, train  # noqa: E402

EXPORT = Path(__file__).resolve().parents[2] / "export" / "session12"
SEED = 20260815


def main() -> int:
    parser = argparse.ArgumentParser(description="教師を LoRA で SFT してアダプタを書き出す")
    parser.add_argument("--task", choices=("classify", "format"), default="classify")
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--eval-n", type=int, default=8, help="適合の確認に使う test 件数")
    parser.add_argument("--max-length", type=int, default=192, help="0.5B は 192 に絞る")
    parser.add_argument("--name", default=None, help="export/session12/{name} に書き出す")
    args = parser.parse_args()

    name = args.name or f"teacher_{args.task}"
    out = EXPORT / name
    print(f"教師 {JA_MODEL}（bf16）を task={args.task} に {args.steps} step 適合させます")
    print("0.5B は 7.27 秒/step の実測（測定条件は本文前掲）なので、時間がかかります")

    # set_seed はモデル構築の前に呼ぶ（セッション7の実測。後にすると LoRA 初期化が再現しない）
    set_seed(SEED)
    tokenizer = load_tokenizer(JA_MODEL)
    model = attach_lora(load_model(JA_MODEL, dtype=torch.bfloat16), r=16, alpha=32)
    stats = param_stats(model)
    print(f"学習対象 {stats['trainable']:,} / {stats['total']:,}"
          f"（{stats['ratio'] * 100:.2f}%）")

    test = load("test")[: args.eval_n]
    before = evaluate(model, tokenizer, test, args.task)
    print(f"適合前: {before.summary()}")

    result = train(model, tokenizer, load("train"), TrainConfig(
        task=args.task, batch_size=2, max_length=args.max_length,
        max_steps=args.steps, lr=2e-4, seed=SEED, log_every=10))
    print(result.summary())

    after = evaluate(model, tokenizer, test, args.task)
    print(f"適合後: {after.summary()}")

    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)
    size_mb = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"-> {out}（{size_mb:.1f} MiB）")

    del model, tokenizer
    gc.collect()

    if after.format_rate <= before.format_rate:
        print("\n形式遵守率が上がっていません。step を増やすか task を確認してください。")
        print("この教師で蒸留を始めても、生徒は定型を学べません。")
        return 1
    print("\n形式遵守率が上がりました。この教師なら蒸留を始められます。")
    print(f"次: python src/session12/make_teacher_data.py --task {args.task} "
          f"--n 24 --adapter export/session12/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
