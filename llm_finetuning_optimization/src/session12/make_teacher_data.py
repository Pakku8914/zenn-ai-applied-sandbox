#!/usr/bin/env python3
"""応答蒸留の第1段：教師で応答を作り、JSONL に落とす（セッション12）。

  docker compose exec app python src/session12/make_teacher_data.py --n 24
  docker compose exec app python src/session12/make_teacher_data.py --n 12 --task format

**このスクリプトは教師モデルだけを読む。生徒モデルは読まない。**
メモリ 5.8GB の環境では、教師（4.94億・bf16）と生徒（1.35億）を同じプロセスに
同居させると、生徒の学習が始まった瞬間に SIGKILL（終了コード 137）で落ちる。
だから蒸留を「生成」と「学習」の2プロセスに割り、間を JSONL でつなぐ。

生成は1件ずつなので遅い（`ftkit.evaluate.evaluate` はバッチ生成しない）。
**まず 24 件で試し、効果を見てから件数を増やす。** 720 件を最初から通さない。
"""

from __future__ import annotations

import argparse
import gc
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from distill import (  # noqa: E402
    build_record, keep_valid, save_jsonl, teacher_data_path, validate_records,
)

from ftkit.data import build_prompt, load  # noqa: E402
from ftkit.evaluate import generate  # noqa: E402
from ftkit.models import JA_MODEL, MODEL_REVISION, load_model, load_tokenizer  # noqa: E402

DTYPES = {"bf16": torch.bfloat16, "fp32": torch.float32}


def generate_records(examples, task: str, model_name: str = JA_MODEL,
                     dtype=torch.bfloat16, max_new_tokens: int | None = None,
                     quiet: bool = False, adapter: str | None = None) -> list[dict]:
    """教師に1件ずつ答えさせて、教師データのリストを返す。

    終了時に `del` と `gc.collect()` で教師を手放す。呼び出し元がこの後に別の
    モデルを読むとしても、教師の 0.74GB（bf16）を抱えたままにしない。

    adapter を渡すと、学習済み LoRA を載せた教師で生成する。**素の 0.5B は
    定型を守らない**（実測：classify でも「この問い合わせは、経費や勤怠に関する問題」
    のような自由文を返し、検証を通る件が 0 件になる）。本文が引用している
    正解率 0.833 は 80 step の SFT を通した教師の値なので、それに相当する
    教師を作るにはアダプタが必要である。
    """
    if max_new_tokens is None:
        max_new_tokens = 12 if task == "classify" else 48
    tokenizer = load_tokenizer(model_name)
    model = load_model(model_name, dtype=dtype)
    if adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter)
        model.eval()
        print(f"  教師に学習済みアダプタを載せました: {adapter}")
    else:
        print("  素の教師で生成します（定型は守りません。検証で全件落ちるのが正常です）")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    records: list[dict] = []
    started = time.perf_counter()
    for index, example in enumerate(examples, start=1):
        output = generate(model, tokenizer, build_prompt(example, task),
                          max_new_tokens=max_new_tokens)
        records.append(build_record(example, task, output, model_name,
                                    MODEL_REVISION, stamp))
        if not quiet:
            print(f"  [{index}/{len(examples)}] {example.id} -> {output.strip()!r}")
    elapsed = time.perf_counter() - started
    print(f"  教師での生成: {elapsed:.1f} 秒 / {len(examples)} 件 "
          f"（1件あたり {elapsed / max(len(examples), 1):.1f} 秒）")

    del model, tokenizer
    gc.collect()          # ここで教師を手放す。次は別プロセスで生徒を読む
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="教師の出力から蒸留用データを作る")
    parser.add_argument("--n", type=int, default=24, help="教師に通す件数（既定 24）")
    parser.add_argument("--task", choices=("classify", "format"), default="classify")
    parser.add_argument("--split", default="train", help="教師に見せる分割（既定 train）")
    parser.add_argument("--dtype", choices=tuple(DTYPES), default="bf16",
                        help="0.5B は bf16 必須。fp32 は既定環境では落ちる")
    parser.add_argument("--out", default=None, help="出力先（既定 data/distill_teacher_{task}.jsonl）")
    parser.add_argument("--adapter", default=None,
                        help="教師に載せる学習済み LoRA アダプタのディレクトリ。"
                             "省略すると素の 0.5B を教師にする（定型を守らない出力になる）")
    parser.add_argument("--keep-invalid", action="store_true",
                        help="検証に落ちた件も保存する（アンチパターンの実演用）")
    args = parser.parse_args()

    examples = load(args.split)[: args.n]
    # 評価に使う分割の id は教師データに入れない（汚染の防止）
    forbidden = {example.id for example in load("test")}
    print(f"教師 {JA_MODEL}（{args.dtype}）で {len(examples)} 件・task={args.task}")

    records = generate_records(examples, args.task, dtype=DTYPES[args.dtype],
                               adapter=args.adapter)

    report = validate_records(records, args.task, forbidden)
    print(f"\n検証: 合格 {report['ok']} 件 / 不合格 {report['ng']} 件")
    for code, count in report["counts"].items():
        print(f"  - {code}: {count} 件")
    gold_mismatch = sum(1 for record in records
                        if record.get("gold") and record["output"].strip() != record["gold"])
    print(f"  参考: 教師の出力が gold と違う件数 {gold_mismatch} / {len(records)}"
          "（実務では gold が無いので測れない）")

    kept = records if args.keep_invalid else keep_valid(records, args.task, forbidden)
    if not kept:
        print("合格した件が0です。--task と教師の出力を確認してください。")
        return 1
    path = save_jsonl(kept, Path(args.out) if args.out else teacher_data_path(args.task))
    print(f"\n{len(kept)} 件を書き出しました -> {path}")
    print("次は別プロセスで: python src/session12/distill_student.py "
          f"--task {args.task}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
