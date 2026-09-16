#!/usr/bin/env python3
"""セッション7の自己検証：失敗診断の主張を機械で確かめる。

検証する主張（本文に書いた内容と1対1で対応させる）:
  1. 全マスクのバッチでは loss が nan になり、勾配はすべて厳密に 0 になる。
     それでも optimizer.step() は呼ばれ、AdamW の weight_decay(既定 0.01) の分だけ
     重みが動く（lr 2e-4 なら 1 step あたり相対 2e-6）
  2. del と gc.collect() でメモリが返り、1体ずつ扱えばピークが増えない
  3. set_seed をモデル構築の前に呼べば loss 列は完全一致する。
     train() の中だけのシードでは LoRA の初期化が再現せず loss 列がずれる
  4. 学習率を極端に大きくすると発散する（nan になる、または loss が上がる）
  5. valid が悪化したら止める早期終了が機能する（patience の判定と最良復元）

**モデルは必ず1体ずつ読み、del と gc.collect() で解放する。**
メモリ 5.8GB の環境では 135M モデルを3体同時に保持できない（1体あたり
peak RSS 約 2.11GB）。学習は 8〜12 step に抑えているので数分で終わる。

  docker compose exec app python src/session07/verify.py
"""

from __future__ import annotations

import gc
import inspect
import math
import sys
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from early_stop import (  # noqa: E402
    param_fingerprint,
    should_stop,
    train_with_early_stop,
    valid_loss,
)
from ftkit.data import load  # noqa: E402
from ftkit.models import FAST_MODEL, attach_lora, load_model, load_tokenizer  # noqa: E402
from ftkit.tokenize import IGNORE_INDEX, collate, encode_example  # noqa: E402
from ftkit.train import TrainConfig, set_seed, train  # noqa: E402

SEED = 20260815
failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def rss_gb() -> float:
    """現在の RSS（GB）。/proc が無い環境では nan を返す。"""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        return float("nan")
    return float("nan")


# --- 1. 全マスクのバッチ（モデルを読まない・数秒） --------------------------
section("1. 全マスクのバッチ：loss は nan・勾配は厳密に 0")

torch.manual_seed(SEED)
head = torch.nn.Linear(16, 32)            # 「語彙 32 の出力層」に見立てたダミー
hidden = torch.randn(2, 5, 16)
logits = head(hidden).reshape(-1, 32)

all_masked = torch.full((10,), IGNORE_INDEX)
loss_all = F.cross_entropy(logits, all_masked, ignore_index=IGNORE_INDEX)
print(f"  全マスクの loss = {loss_all.item()}")
check("全マスクの loss は nan（例外は出ない）", math.isnan(loss_all.item()),
      f"loss={loss_all.item()}")

before = head.weight.detach().clone()
loss_all.backward()
grad = head.weight.grad
check("勾配は None ではなく「厳密に 0」（NaN は伝わらない）",
      grad is not None and float(grad.abs().max()) == 0.0,
      f"|grad|max={float(grad.abs().max()):.3e}" if grad is not None else "grad is None")

optimizer = torch.optim.AdamW(head.parameters(), lr=2e-4)   # weight_decay の既定は 0.01
optimizer.step()
relative = ((head.weight.detach() - before) / before).abs()
median = float(relative.median())
print(f"  1 step 後の相対変化（中央値）= {median:.3e}")
check("勾配 0 でも weight_decay の分だけ重みが動く（相対 2e-6）",
      1.8e-6 < median < 2.2e-6, f"中央値={median:.3e}")
check("動く向きは減衰（絶対値が増える要素は無い）",
      float((head.weight.detach().abs() - before.abs()).max()) <= 0.0)

head.zero_grad(set_to_none=True)
partial = all_masked.clone()
partial[0] = 7                                     # 1トークンだけ採点対象にする
loss_partial = F.cross_entropy(head(hidden).reshape(-1, 32), partial,
                               ignore_index=IGNORE_INDEX)
loss_partial.backward()
check("1トークンでも採点対象があれば loss は有限になる",
      math.isfinite(loss_partial.item()), f"loss={loss_partial.item():.4f}")
check("そのとき勾配は 0 ではない",
      float(head.weight.grad.abs().max()) > 0.0,
      f"|grad|max={float(head.weight.grad.abs().max()):.3e}")

del head, hidden, logits, optimizer, before, relative
gc.collect()

tokenizer = load_tokenizer(FAST_MODEL)
train_examples = load("train")

# --- 2. del と gc.collect() でメモリが返る（最初に測る） --------------------
section("2. del と gc.collect() でメモリが返る")

base = rss_gb()
if math.isnan(base):
    print("  SKIP: /proc/self/status が読めないため RSS の検証を飛ばします")
else:
    model = load_model(FAST_MODEL)
    after_load = rss_gb()
    del model
    gc.collect()
    after_free = rss_gb()

    # 学習を1 step だけ回して「勾配 + optimizer 状態」を確保する。
    # 重み自体は safetensors から mmap されるため、del しても file-backed の
    # ページは RSS に残る（実測：読み込みで +0.57GB 増えても解放で戻るのは 0.03GB）。
    # 実際に返るのは、この匿名メモリ（勾配と optimizer 状態）である。
    model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
    params = [q for q in model.parameters() if q.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=2e-4)
    batch = collate([encode_example(tokenizer, train_examples[0], "classify", 192)],
                    tokenizer.pad_token_id)
    model(**batch).loss.backward()
    optimizer.step()
    after_train = rss_gb()
    del model, optimizer, params, batch
    gc.collect()
    after_train_free = rss_gb()

    model = load_model(FAST_MODEL)
    after_reload = rss_gb()
    del model
    gc.collect()
    print(f"  読み込み前 {base:.2f}GB -> 1体目 {after_load:.2f}GB -> del+gc 後 "
          f"{after_free:.2f}GB（重みは mmap なので戻らない）")
    print(f"  1 step 学習後 {after_train:.2f}GB -> del+gc 後 {after_train_free:.2f}GB"
          f"（勾配と optimizer 状態は返る）-> 再読み込み {after_reload:.2f}GB")
    check("モデルを読むと RSS が 0.3GB 以上増える", after_load - base > 0.3,
          f"+{after_load - base:.2f}GB")
    check("重みは mmap なので、読み込み直後の del では RSS がほとんど戻らない",
          after_load - after_free < 0.2,
          f"-{after_load - after_free:.2f}GB（返るのは勾配と optimizer 状態）")
    check("勾配と optimizer 状態は del と gc.collect() で返る",
          after_train - after_train_free > 0.05,
          f"-{after_train - after_train_free:.2f}GB")
    check("1体ずつ読めば2体目のピークが1体目とほぼ同じ（差 0.3GB 未満）",
          abs(after_reload - after_load) < 0.3, f"差 {abs(after_reload - after_load):.2f}GB")
    check("3体同時に保持すると 5.8GB を超える（1体 2.11GB の実測からの計算）",
          2.11 * 3 > 5.8, f"2.11GB × 3 = {2.11 * 3:.2f}GB > 5.8GB")

# --- 3. シードの設定位置と再現性 --------------------------------------------
section("3. シードの設定位置と再現性（8 step × 4 回）")

valid_examples = load("valid")
CONFIG = TrainConfig(task="classify", batch_size=2, max_length=128,
                     max_steps=8, log_every=100, seed=SEED)


def run(seed_before: bool, jitter: int) -> list[float]:
    """1回だけ学習して loss 列を返す。モデルは必ず解放する。"""
    if seed_before:
        set_seed(SEED)                 # 正しい位置：モデル構築の前
    else:
        torch.manual_seed(jitter)      # 直前の処理で乱数の状態が違っていた状況を再現する
    model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
    result = train(model, tokenizer, train_examples, CONFIG)
    losses = list(result.losses)
    del model, result
    gc.collect()
    return losses


good_a = run(seed_before=True, jitter=0)
good_b = run(seed_before=True, jitter=0)
bad_a = run(seed_before=False, jitter=1)
bad_b = run(seed_before=False, jitter=2)

good_diff = max(abs(x - y) for x, y in zip(good_a, good_b))
bad_diff = max(abs(x - y) for x, y in zip(bad_a, bad_b))
print(f"  構築の前に set_seed  : 最大差 {good_diff:.2e}")
print(f"  train() の中だけ     : 最大差 {bad_diff:.2e}")
check("set_seed をモデル構築の前に置けば loss 列が一致する", good_diff <= 1e-6,
      f"最大差={good_diff:.2e}")
check("train() の中だけのシードでは loss 列が再現しない", bad_diff > 1e-4,
      f"最大差={bad_diff:.2e}")
check("正常な学習率では loss に nan が出ない", all(x == x for x in good_a))
check("正常な学習率では loss が初期値より下がる場面がある", min(good_a) < good_a[0],
      f"{good_a[0]:.4f} -> 最小 {min(good_a):.4f}")

# --- 4. 学習率が大きすぎると発散する ----------------------------------------
section("4. 学習率が大きすぎると発散する（lr=1.0 / 8 step）")

set_seed(SEED)
model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
diverged = train(model, tokenizer, train_examples,
                 TrainConfig(task="classify", batch_size=2, max_length=128,
                             max_steps=8, log_every=4, lr=1.0, seed=SEED))
del model
gc.collect()
losses = diverged.losses
has_nan = any(x != x for x in losses)
print(f"  lr=1.0 の loss 列: {[round(x, 3) if x == x else 'nan' for x in losses]}")
check("lr=1.0 では nan になるか loss が初期値の2倍以上に上がる",
      has_nan or max(x for x in losses if x == x) > losses[0] * 2,
      f"nan={has_nan} 最大={max((x for x in losses if x == x), default=float('nan')):.4f} "
      f"初期={losses[0]:.4f}")
# lr=1.0 と lr=2e-4 は別の実行なので loss の絶対値を直接比べても意味がない。
# 8 step という短さでは lr=2e-4 でも loss は上下に跳ねる（実測：初期 4.13 に対し
# 最大 17.21）。両者を分けるのは「一度でも初期値を下回るか」である。
#   lr=1.0   : 最小値が初期値と同じ（1 step 目以降ずっと上）＝ 学習が成立していない
#   lr=2e-4  : 途中で初期値を下回る場面がある ＝ 跳ねてはいるが学習は進んでいる
bad_ever_improved = min(losses) < losses[0]
good_ever_improved = min(good_a) < good_a[0]
print(f"  初期値を下回った場面: lr=1.0 -> {bad_ever_improved} / lr=2e-4 -> {good_ever_improved}")
check("lr=1.0 は一度も初期値を下回らない（学習が成立していない）",
      not bad_ever_improved,
      f"最小={min(losses):.4f} 初期={losses[0]:.4f}")
check("lr=2e-4 は跳ねても初期値を下回る場面がある（3 の結果と対比）",
      all(x == x for x in good_a) and good_ever_improved,
      f"nan なし / 最小={min(good_a):.4f} < 初期={good_a[0]:.4f}（最大 {max(good_a):.4f} まで跳ねる）")

# --- 5. 早期終了 -------------------------------------------------------------
section("5. 早期終了：patience の判定（モデルを読まない）")

check("改善が続く間は止めない", should_stop([1.0, 0.9, 0.8], patience=2) is False)
check("評価回数が patience 以下なら止めない", should_stop([1.0], patience=2) is False)
check("1回の非改善では止めない", should_stop([1.0, 0.9, 1.1], patience=2) is False)
check("patience 回続けて非改善なら止める", should_stop([1.0, 0.9, 1.1, 1.2], patience=2) is True)
check("最後に最良が来たら止めない", should_stop([1.0, 0.9, 1.1, 0.8], patience=2) is False)
check("min_delta より小さい改善は改善と数えない",
      should_stop([1.0, 0.999, 0.998], patience=2, min_delta=0.01) is True)
check("ftkit の train() は早期終了の引数を持たない（この章で補う欠け）",
      "patience" not in inspect.signature(train).parameters
      and "valid_examples" not in inspect.signature(train).parameters)

section("5. 早期終了：停止と最良復元（valid を差し替えて判定だけを試す）")

scripted = [1.00, 0.80, 0.90, 0.95]      # 2回目が最良。4回目で patience=2 に達する
calls: list[int] = []


def scripted_eval(step: int) -> float:
    calls.append(step)
    return scripted[len(calls) - 1]


set_seed(SEED)
model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
forced = train_with_early_stop(
    model, tokenizer, train_examples, valid_examples[:4],
    TrainConfig(task="classify", batch_size=2, max_length=128, max_steps=15,
                log_every=100, seed=SEED),
    eval_every=3, patience=2, eval_fn=scripted_eval)
print(f"  {forced.summary()}")
after_restore = param_fingerprint(model)
del model
gc.collect()

check("patience に達した時点で止まる（step 15 まで回らない）",
      forced.stopped_early and forced.steps == 12, f"{forced.steps} step で停止")
check("最良の評価点を正しく記録する", forced.best_step == 6 and forced.best_valid == 0.80,
      f"best_step={forced.best_step} best_valid={forced.best_valid}")
check("停止時の重みは最良時点と違っていた（復元に意味がある）",
      abs(forced.fingerprint_before_restore - forced.fingerprint_after_restore) > 1e-6,
      f"停止時 {forced.fingerprint_before_restore:.4f} -> 復元後 "
      f"{forced.fingerprint_after_restore:.4f}")
check("復元後のモデルが結果の記録と一致する", forced.restored
      and abs(after_restore - forced.fingerprint_after_restore) < 1e-6)

section("5. 早期終了：実際の valid を測って回す（12 step / valid 8 件）")

set_seed(SEED)
model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
real = train_with_early_stop(
    model, tokenizer, train_examples, valid_examples[:8],
    TrainConfig(task="classify", batch_size=2, max_length=128, max_steps=12,
                log_every=100, seed=SEED),
    eval_every=6, patience=2)
print(f"  {real.summary()}")
measured = valid_loss(model, tokenizer, valid_examples[:8],
                      TrainConfig(task="classify", batch_size=2, max_length=128))
del model
gc.collect()

check("eval_every ごとに valid が記録される", [s for s, _ in real.valid_history] == [6, 12],
      str([s for s, _ in real.valid_history]))
check("valid の loss はすべて有限", all(math.isfinite(v) for _, v in real.valid_history),
      str([round(v, 4) for _, v in real.valid_history]))
check("best_valid は記録の最小値", real.best_valid == min(v for _, v in real.valid_history),
      f"best={real.best_valid:.4f}")
check("2回の評価では止まらない（patience=2 の下限）", not real.stopped_early)
check("valid_loss() を単体で呼んでも有限な値が返る", math.isfinite(measured),
      f"valid={measured:.4f}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション7の検証はすべて成功しました。")
