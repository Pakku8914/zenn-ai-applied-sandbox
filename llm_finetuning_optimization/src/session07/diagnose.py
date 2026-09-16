#!/usr/bin/env python3
"""学習を始める前の5段診断（セッション7・問題9の参照実装）。

1つでも不合格なら非0で終了する。安い検査を先に、高い検査を後に並べてある。
2段目の検査は問題2で作った preflight() をそのまま使う（同じ検査を2箇所に書かない）。

  docker compose exec app python src/session07/diagnose.py
  docker compose exec app python src/session07/diagnose.py --task format --max-length 64
  docker compose exec app python src/session07/diagnose.py --lr 1.0
"""

from __future__ import annotations

import argparse
import gc
import sys
from collections import Counter
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # sandbox/ を import 可能にする

from ftkit.data import CATEGORIES, load  # noqa: E402
from ftkit.models import FAST_MODEL, attach_lora, load_model, load_tokenizer  # noqa: E402
from ftkit.tokenize import IGNORE_INDEX, collate, encode_example, masked_ratio  # noqa: E402
from ftkit.train import TrainConfig, set_seed, train  # noqa: E402

SEED = 20260815


def preflight(tokenizer, model, examples, config: TrainConfig, n: int = 3) -> str:
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    assert trainable > 0, "学習対象が0個です（attach_lora の戻り値を代入し忘れていませんか）"

    ratios, supervised, truncated = [], [], 0
    for example in examples[:n]:
        try:
            encoded = encode_example(tokenizer, example, config.task, config.max_length)
        except ValueError as error:            # 回答が max_length に入らない設定ミス
            raise AssertionError(f"入力を作れません: {error}") from error
        ratios.append(masked_ratio(encoded))
        supervised.append(sum(1 for x in encoded["labels"] if x != IGNORE_INDEX))
        truncated += int(encoded["truncated_prompt_tokens"] > 0)

    assert max(ratios) < 0.999, f"マスク率 {max(ratios):.3f} が高すぎます（採点対象がほぼ無い）"
    assert min(supervised) >= 1, "採点対象が0トークンの件があります"
    return (f"preflight OK: 学習対象={trainable:,} マスク率={max(ratios):.3f} "
            f"採点対象={min(supervised)} トークン 切り捨て={truncated}/{n}件")


def fail(stage: str, reason: str) -> None:
    print(f"[{stage}] NG: {reason}")
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["classify", "format"], default="classify")
    ap.add_argument("--max-length", type=int, default=128)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--steps", type=int, default=3)
    args = ap.parse_args()

    # [1/5] データ（モデルもトークナイザも読まない・数秒）
    examples = load("train")
    dist = Counter(ex.category for ex in examples)
    if len(dist) != len(CATEGORIES):
        fail("1/5", f"区分が {len(dist)} 種しかありません（期待は {len(CATEGORIES)} 種）")
    print(f"[1/5] データ      : train={len(examples)} 件 区分{len(dist)}種 "
          f"分布 {'/'.join(str(dist[c]) for c in CATEGORIES)}  OK")

    # [2/5][3/5] 入力の作り方と学習対象 ― 問題2 の門番をそのまま使う
    tokenizer = load_tokenizer(FAST_MODEL)
    set_seed(SEED)                                   # 構築の前に固定する
    model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
    config = TrainConfig(task=args.task, max_length=args.max_length, lr=args.lr)
    try:
        print(f"[2/5] 入力と学習対象: {preflight(tokenizer, model, examples, config)}")
        # preflight は先頭3件しか見ない。「回答だけで max_length を超える」件が
        # 4件目以降にあると、ここは通って 5 段目の train() が落ちる（実際に踏んだ）。
        # トークナイザだけの検査は安いので、致命的な条件は全件で見る。
        encoded = [encode_example(tokenizer, ex, args.task, args.max_length)
                   for ex in examples]
    except (AssertionError, ValueError) as error:
        fail("2/5", str(error))

    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=args.lr)
    held = sum(p.numel() for group in optimizer.param_groups for p in group["params"])
    if sum(p.numel() for p in params) != held:
        fail("3/5", f"学習対象と optimizer の保持数が一致しません（{held:,}）")
    print(f"[3/5] optimizer   : 学習対象と同数 {held:,} を保持  OK")

    # [4/5] 1 step だけ試走して loss と勾配ノルムを見る
    loss = model(**collate(encoded[:2], tokenizer.pad_token_id)).loss
    loss.backward()
    grad_norm = float(torch.nn.utils.clip_grad_norm_(params, 1.0))   # クリップ前の値が返る
    optimizer.zero_grad()
    if loss.item() != loss.item():
        fail("4/5", "loss が nan です（採点対象と学習率を確認してください）")
    print(f"[4/5] 1 step 試走 : loss={loss.item():.4f} 勾配ノルム={grad_norm:.3f}  OK")

    # [5/5] 学習率の妥当性（短い試走で形を見る）
    result = train(model, tokenizer, examples,
                   TrainConfig(task=args.task, batch_size=2, max_length=args.max_length,
                               max_steps=args.steps, log_every=100, lr=args.lr, seed=SEED))
    first, last = result.first_loss, result.last_loss
    del model, optimizer, result
    gc.collect()
    if last != last:
        fail("5/5", f"lr={args.lr:.0e} で nan になりました（大きすぎます）")
    if last > first * 2:
        fail("5/5", f"lr={args.lr:.0e} は大きすぎます（{first:.4f} -> {last:.4f}）")
    verdict = "妥当に見える" if (first - last) / first > 0.01 else "小さすぎる可能性がある"
    print(f"[5/5] 学習率      : lr={args.lr:.0e} は{verdict}"
          f"（{args.steps} step で {first:.4f} -> {last:.4f}）  OK")
    print("診断はすべて合格しました。学習を開始できます。")


if __name__ == "__main__":
    main()
