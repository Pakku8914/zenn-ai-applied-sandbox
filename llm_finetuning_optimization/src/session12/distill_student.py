#!/usr/bin/env python3
"""応答蒸留の第2段：教師データで生徒を LoRA 学習し、一致率とタスク指標を測る。

  docker compose exec app python src/session12/distill_student.py --steps 40 --eval-n 10

**このスクリプトは生徒モデルだけを読む。教師モデルは読まない。**
教師の情報は前段が JSONL に落としてあるので、学習の時点では要らない。
これが応答蒸留の実務上の利点でもある（教師を1回動かせば、あとは何度でも
学習し直せる。教師の課金・待ち時間は1回で済む）。

学習前の基準線を必ず測ってから学習する（本書のすべての学習演習の作法）。
結果は runs/compare_distill_{task}.json に、**条件ごと**書き出す。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from distill import agreement, load_jsonl, teacher_data_path, to_examples  # noqa: E402

from ftkit.data import load  # noqa: E402
from ftkit.evaluate import evaluate, generate  # noqa: E402
from ftkit.models import FAST_MODEL, attach_lora, load_model, load_tokenizer, param_stats  # noqa: E402
from ftkit.train import TrainConfig, set_seed, train  # noqa: E402

SEED = 20260815
RUNS = Path(__file__).resolve().parents[2] / "runs"


def measure_agreement(model, tokenizer, records: list[dict], task: str,
                      limit: int) -> dict:
    """教師データと同じプロンプトを生徒に投げ、教師の出力と比べる。

    ここで比べているのは gold ではなく**教師の出力**である。これが「教師との
    一致率」で、蒸留に固有の指標。タスクの正解率とは別に記録する。
    """
    max_new_tokens = 12 if task == "classify" else 48
    pairs = [(record["output"],
              generate(model, tokenizer, record["prompt"], max_new_tokens=max_new_tokens))
             for record in records[:limit]]
    result = agreement(pairs)
    for teacher_output, student_output in pairs[:5]:
        print(f"  教師={teacher_output.strip()!r} / 生徒={student_output.strip()!r}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="教師データで生徒を蒸留する")
    parser.add_argument("--task", choices=("classify", "format"), default="classify")
    parser.add_argument("--data", default=None, help="教師データの JSONL")
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=320)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--eval-n", type=int, default=10, help="test で測る件数")
    parser.add_argument("--agree-n", type=int, default=10, help="一致率を測る件数")
    parser.add_argument("--normalize", action="store_true",
                        help="教師の出力を区分名だけに正規化してから学習する")
    parser.add_argument("--tag", default=None)
    args = parser.parse_args()

    path = Path(args.data) if args.data else teacher_data_path(args.task)
    records = load_jsonl(path)
    examples = to_examples(records, args.task, normalize=args.normalize)
    print(f"教師データ {len(examples)} 件（{path.name}）/ task={args.task}")
    print(f"教師: {records[0].get('teacher')} @ {records[0].get('teacher_revision')} "
          f"（生成 {records[0].get('generated_at')}）")

    # 1エポックで足りない分は繰り返す（件数が少ないので必要になる）
    epochs = max(1, math.ceil(args.steps * args.batch_size / max(len(examples), 1)))
    tokenizer = load_tokenizer(FAST_MODEL)
    set_seed(SEED)                     # モデル構築の前に呼ぶ（セッション7）
    model = attach_lora(load_model(FAST_MODEL), r=args.lora_r, alpha=2 * args.lora_r)
    stats = param_stats(model)
    print(f"生徒: {FAST_MODEL} / 学習対象 {stats['trainable']:,} 個"
          f"（{stats['ratio'] * 100:.2f}%）")

    test = load("test")[: args.eval_n]
    print("\n--- 学習前の基準線 ---")
    before = evaluate(model, tokenizer, test, args.task)
    print(f"  {before.summary()}")

    print(f"\n--- 学習（{args.steps} step / epochs={epochs}） ---")
    result = train(model, tokenizer, examples,
                   TrainConfig(task=args.task, epochs=epochs,
                               batch_size=args.batch_size, lr=args.lr,
                               max_length=args.max_length, max_steps=args.steps,
                               log_every=10, seed=SEED))
    print(f"  {result.summary()}")

    print("\n--- 学習後 ---")
    after = evaluate(model, tokenizer, test, args.task)
    print(f"  {after.summary()}")
    print("\n--- 教師との一致率 ---")
    agree = measure_agreement(model, tokenizer, records, args.task, args.agree_n)
    print(f"  n={agree['n']} 完全一致={agree['exact']:.3f} "
          f"区分一致={agree['category']:.3f}")

    tag = args.tag or f"distill_{args.task}"
    RUNS.mkdir(parents=True, exist_ok=True)
    payload = {
        "tag": tag,
        # 条件（これを残さないと比較実験にならない。ftkit の compare には入らない項目も入れる）
        "config": {"student": FAST_MODEL, "teacher": records[0].get("teacher"),
                   "teacher_revision": records[0].get("teacher_revision"),
                   "teacher_data": path.name, "teacher_records": len(records),
                   "normalize": args.normalize, "task": args.task,
                   "steps": result.steps, "epochs": epochs,
                   "batch_size": args.batch_size, "max_length": args.max_length,
                   "lora_r": args.lora_r, "lr": args.lr, "seed": SEED,
                   "eval_n": args.eval_n, "agree_n": args.agree_n},
        "before": {"accuracy": before.accuracy, "format_rate": before.format_rate},
        "after": {"accuracy": after.accuracy, "format_rate": after.format_rate},
        "agreement": agree,
        "loss": {"first": result.first_loss, "last": result.last_loss},
        "seconds": result.seconds, "peak_rss_gb": result.peak_rss_gb,
    }
    out = RUNS / f"compare_{tag}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n記録 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
