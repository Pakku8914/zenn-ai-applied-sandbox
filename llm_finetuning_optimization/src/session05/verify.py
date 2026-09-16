#!/usr/bin/env python3
"""セッション5の自己検証：学習ループが正しく動くこと。

- loss マスクがプロンプト部分を外していること
- シードを固定すれば同じ loss 列になること
- 学習で loss が下がること
- LoRA が学習対象を大幅に減らすこと

小型モデル（SmolLM2-135M）で 20 step だけ回すので数分で終わる。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import CATEGORIES, build_prompt, build_target, load  # noqa: E402
from ftkit.models import FAST_MODEL, attach_lora, load_model, load_tokenizer, param_stats  # noqa: E402
from ftkit.tokenize import IGNORE_INDEX, collate, encode_example, masked_ratio  # noqa: E402
from ftkit.train import TrainConfig, set_seed, train  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- データセット -----------------------------------------------------------
train_examples = load("train")
test_examples = load("test")
check("train が読める", len(train_examples) == 720, f"{len(train_examples)} 件")
check("test が読める", len(test_examples) == 90, f"{len(test_examples)} 件")
check("区分が6種類", len({e.category for e in train_examples}) == len(CATEGORIES))
check("分類タスクの正解は区分名そのもの",
      build_target(train_examples[0], "classify") == train_examples[0].category)
check("整形タスクの正解は3行", build_target(train_examples[0], "format").count("\n") == 2,
      repr(build_target(train_examples[0], "format")))

# --- loss マスク -----------------------------------------------------------
tokenizer = load_tokenizer(FAST_MODEL)
encoded = encode_example(tokenizer, train_examples[0], "classify", max_length=320)
ratio = masked_ratio(encoded)
check("プロンプト部分が損失から外れている", 0.5 < ratio < 1.0, f"マスク率={ratio:.3f}")
check("マスクされていない位置が末尾にある",
      encoded["labels"][-1] != IGNORE_INDEX,
      f"末尾のラベル={encoded['labels'][-1]}")
check("input_ids と labels の長さが一致",
      len(encoded["input_ids"]) == len(encoded["labels"]))

# 長さの違う2件を束ねてパディングを発生させる
short = encode_example(tokenizer, train_examples[0], "classify", 320)
long_ = encode_example(tokenizer, train_examples[0], "format", 320)
check("整形タスクの方が回答が長い", len(long_["input_ids"]) > len(short["input_ids"]),
      f"{len(short['input_ids'])} vs {len(long_['input_ids'])}")
batch = collate([short, long_], tokenizer.pad_token_id)
check("パディング部分も損失から外れている",
      (batch["labels"] == IGNORE_INDEX).sum().item() > 0)
check("attention_mask がパディングを 0 にしている",
      int(batch["attention_mask"].sum().item()) < batch["attention_mask"].numel(),
      f"有効 {int(batch['attention_mask'].sum().item())} / 全体 {batch['attention_mask'].numel()}")
check("回答は切り捨てられていない", short["truncated_prompt_tokens"] >= 0
      and short["labels"][-1] != IGNORE_INDEX)

# --- LoRA が学習対象を減らす -----------------------------------------------
# メモリ 5.8GB の環境では 135M モデルを3体同時に保持すると OOM で殺される
# （1体あたり peak RSS 約 2.1GB）。使い終わったら必ず解放する。
import gc  # noqa: E402

full = load_model(FAST_MODEL)
full_stats = param_stats(full)
del full
gc.collect()

# シードは **モデル構築の前** に設定する。train() の中だけで設定しても
# LoRA の初期化（A・B 行列の乱数）が再現せず、loss 列が一致しない（実測で 3.2e-2 ずれた）。
set_seed(20260815)
lora = attach_lora(load_model(FAST_MODEL), r=16)
lora_stats = param_stats(lora)
check("フル微調整は全パラメータが学習対象", full_stats["ratio"] > 0.99,
      f"{full_stats['ratio'] * 100:.2f}%")
check("LoRA は学習対象が 5% 未満", lora_stats["ratio"] < 0.05,
      f"{lora_stats['trainable'] / 1e6:.3f}M / {lora_stats['total'] / 1e6:.1f}M "
      f"= {lora_stats['ratio'] * 100:.2f}%")

# --- 学習で loss が下がる ---------------------------------------------------
config = TrainConfig(task="classify", batch_size=2, max_length=320, max_steps=20, log_every=10)
result = train(lora, tokenizer, train_examples, config)
print(f"\n{result.summary()}")
check("20 step 走った", result.steps == 20, f"{result.steps} step")
early = sum(result.losses[:5]) / 5
late = sum(result.losses[-5:]) / 5
check("loss が下がっている", late < early, f"前半平均 {early:.4f} -> 後半平均 {late:.4f}")
check("loss が NaN になっていない", all(x == x for x in result.losses))

# --- シード固定で再現する ---------------------------------------------------
del lora
gc.collect()
set_seed(20260815)
lora2 = attach_lora(load_model(FAST_MODEL), r=16)
result2 = train(lora2, tokenizer, train_examples, config)
del lora2
gc.collect()
diffs = [abs(a - b) for a, b in zip(result.losses, result2.losses)]
check("同じシードなら loss 列が一致する", max(diffs) < 1e-4, f"最大差={max(diffs):.2e}")

# --- シードを変えると変わる -------------------------------------------------
set_seed(999)
lora3 = attach_lora(load_model(FAST_MODEL), r=16)
config_other = TrainConfig(task="classify", batch_size=2, max_length=320, max_steps=20,
                           log_every=100, seed=999)
result3 = train(lora3, tokenizer, train_examples, config_other)
del lora3
gc.collect()
check("シードを変えると loss 列が変わる",
      max(abs(a - b) for a, b in zip(result.losses, result3.losses)) > 1e-4)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション5の検証はすべて成功しました。")
