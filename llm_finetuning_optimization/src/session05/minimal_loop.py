#!/usr/bin/env python3
"""セッション5：素の PyTorch で学習ループを書く（135M モデルで 20 step・数分）。

  python src/session05/minimal_loop.py

Trainer も ftkit.train も使わず、forward → loss → backward → step を自分で書く。
`ftkit.train.train()` が中で何をしているかを、手で書いて確かめるためのスクリプト。

確かめること:
  1. 同じバッチを 3 回 backward すると勾配がちょうど 3 倍になる（= zero_grad が要る理由）
  2. clip_grad_norm_ が勾配ノルムを上限まで抑えること
  3. 6 行のループで loss が下がること
  4. lr が warmup で上がりきり、そのあと減衰すること

**loss・ノルム・秒数の絶対値は環境で変わる。** このスクリプトが検証するのは
「3倍になる」「上限を超えない」「下がる」という**関係**だけである。
1つでも崩れたら非0で終了する。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import torch  # noqa: E402

from ftkit.data import load  # noqa: E402
from ftkit.models import FAST_MODEL, load_model, load_tokenizer  # noqa: E402
from ftkit.tokenize import collate, encode_example  # noqa: E402
from ftkit.train import set_seed  # noqa: E402

MAX_LENGTH = 320   # SmolLM2 は日本語が膨らむ（S04 の実測で最長 260 トークン）
BATCH_SIZE = 2
STEPS = 20
LR = 5e-5          # フル微調整なので小さめに取る
WARMUP_RATIO = 0.1
SEED = 20260815

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def grad_norm(params) -> float:
    """全パラメータの勾配を1本のベクトルと見なしたときの長さ（L2ノルム）。"""
    total = 0.0
    for p in params:
        if p.grad is not None:
            total += float((p.grad.detach() ** 2).sum())
    return total ** 0.5


# --- 準備 -------------------------------------------------------------------
set_seed(SEED)                      # モデル構築の**前**に呼ぶ
tokenizer = load_tokenizer(FAST_MODEL)
model = load_model(FAST_MODEL)      # 学習対象を絞らない（フル微調整）
examples = load("train")

params = [p for p in model.parameters() if p.requires_grad]
print(f"モデル  : {FAST_MODEL}")
print(f"学習対象: {sum(p.numel() for p in params) / 1e6:.1f}M パラメータ（フル微調整）")

# 順序は固定する（シャッフルは ftkit.train が担当する。ここは説明を追いやすくするため）
encoded = [encode_example(tokenizer, ex, "classify", MAX_LENGTH)
           for ex in examples[: STEPS * BATCH_SIZE]]
batches = [encoded[i: i + BATCH_SIZE] for i in range(0, len(encoded), BATCH_SIZE)]
print(f"バッチ  : {len(batches)} 個（batch_size={BATCH_SIZE} / max_length={MAX_LENGTH}）\n")

# --- 1. 勾配は「上書き」ではなく「足し込み」される -------------------------
model.eval()   # dropout の乱れを除いて厳密に比べる（重みの更新はまだしない）
inputs = collate(batches[0], tokenizer.pad_token_id)

model.zero_grad(set_to_none=True)
loss1 = model(**inputs).loss
loss1.backward()
n1 = grad_norm(params)

for _ in range(2):
    model(**inputs).loss.backward()   # zero_grad しないまま、同じバッチをもう2回
n3 = grad_norm(params)

print(f"loss（同じバッチ）      : {float(loss1.item()):.4f}")
print(f"勾配ノルム 1回 backward : {n1:.4f}")
print(f"勾配ノルム 3回 backward : {n3:.4f}（{n3 / n1:.2f} 倍）")
check("zero_grad しないと勾配が足し込まれる（ちょうど3倍）",
      abs(n3 / n1 - 3.0) < 0.01, f"{n3 / n1:.3f} 倍")

# --- 2. 勾配クリッピングは上限を超えた分だけ縮める -------------------------
before = grad_norm(params)
returned = float(torch.nn.utils.clip_grad_norm_(params, 1.0))
after = grad_norm(params)
print(f"クリッピング            : {before:.4f} -> {after:.4f}（戻り値 {returned:.4f}）")
check("clip_grad_norm_ が上限に抑える", after <= min(before, 1.0) + 1e-3,
      f"{before:.4f} -> {after:.4f}")
check("clip_grad_norm_ の戻り値はクリップ前のノルム",
      abs(returned - before) <= max(1e-3, before * 1e-3), f"戻り値={returned:.4f}")
model.zero_grad(set_to_none=True)

# --- 3. 学習ループ本体 -------------------------------------------------------
model.train()
optimizer = torch.optim.AdamW(params, lr=LR)
warmup = max(int(STEPS * WARMUP_RATIO), 1)
scheduler = torch.optim.lr_scheduler.LambdaLR(
    optimizer,
    lambda step: min((step + 1) / warmup, 1.0)
    * max(0.0, 1.0 - max(step - warmup, 0) / max(STEPS - warmup, 1)),
)

losses: list[float] = []
lrs: list[float] = []
print(f"\n--- 学習ループ（{STEPS} step / lr={LR:.1e} / warmup={warmup} step）---")
started = time.perf_counter()
for step, batch in enumerate(batches[:STEPS]):
    t0 = time.perf_counter()
    inputs = collate(batch, tokenizer.pad_token_id)
    lrs.append(scheduler.get_last_lr()[0])          # この step で使う lr
    loss = model(**inputs).loss                     # ① 前向き計算 → 損失
    loss.backward()                                 # ② 勾配を計算する
    torch.nn.utils.clip_grad_norm_(params, 1.0)     # ③ 勾配の暴走を抑える
    optimizer.step()                                # ④ 重みを更新する
    scheduler.step()                                # ⑤ 次の lr へ進める
    optimizer.zero_grad()                           # ⑥ 勾配を消す
    losses.append(float(loss.item()))
    if (step + 1) % 5 == 0 or step == 0:
        print(f"  step {step + 1:>3}/{STEPS}  loss={losses[-1]:.4f}  lr={lrs[-1]:.2e}  "
              f"{time.perf_counter() - t0:.2f}s")
seconds = time.perf_counter() - started

early = sum(losses[:4]) / 4
late = sum(losses[-4:]) / 4
print(f"\n{STEPS} step / {seconds:.1f}s（{seconds / STEPS:.2f} 秒/step）"
      f"  loss {losses[0]:.4f} -> {losses[-1]:.4f}\n")

check(f"{STEPS} step 走った", len(losses) == STEPS, f"{len(losses)} step")
check("loss が NaN になっていない", all(x == x for x in losses))
check("loss が下がっている", late < early, f"前半平均 {early:.4f} -> 後半平均 {late:.4f}")
check("lr が warmup の終わりで base_lr に達する",
      abs(lrs[warmup - 1] - LR) <= LR * 1e-6, f"{lrs[warmup - 1]:.2e}")
check("lr が最後は減衰している", 0 < lrs[-1] < lrs[warmup - 1],
      f"{lrs[warmup - 1]:.2e} -> {lrs[-1]:.2e}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n学習ループの検証はすべて成功しました。")
