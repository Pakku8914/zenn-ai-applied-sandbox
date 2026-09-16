#!/usr/bin/env python3
"""セッション5：学習率スケジューラの形を数値で確かめる。

  python src/session05/lr_curve.py

モデルの重みを一度も読まないので一瞬で終わる（ダミーのパラメータ1個で
`ftkit/train.py` と同じスケジューラを組み立てる）。

確かめること:
  1. warmup 区間で lr が線形に上がりきること
  2. 頂点が base_lr と一致すること
  3. その後は線形に減衰し、最後の step でも 0 にはならないこと
  4. grad_accum を上げると、スケジューラが終端まで進まないこと（本章の落とし穴）

すべて算数で答えが決まる（環境によって変わらない）。
1つでも合わなければ非0で終了する。
"""

from __future__ import annotations

import sys

import torch

BASE_LR = 5e-5
TOTAL = 60
WARMUP_RATIO = 0.1
WARMUP = max(int(TOTAL * WARMUP_RATIO), 1)  # = 6
ACCUM = 4

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def close(a: float, b: float, rel: float = 1e-9) -> bool:
    return abs(a - b) <= 1e-15 + rel * abs(b)


def lr_series(base_lr: float, total_steps: int, warmup_ratio: float = 0.1,
              grad_accum: int = 1) -> list[float]:
    """ftkit/train.py と同じスケジューラを組み、各更新で使われた lr を順に返す。

    ダミーのパラメータで optimizer を作る。勾配は 0 なので重みは動かないが、
    scheduler の進み方は本物の学習とまったく同じになる。
    """
    param = torch.nn.Parameter(torch.zeros(1))
    optimizer = torch.optim.SGD([param], lr=base_lr)
    warmup = max(int(total_steps * warmup_ratio), 1)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: min((step + 1) / warmup, 1.0)
        * max(0.0, 1.0 - max(step - warmup, 0) / max(total_steps - warmup, 1)),
    )

    used: list[float] = []
    for step in range(total_steps):
        # 勾配累積の途中の step では重みを更新しない（= scheduler も進めない）
        if (step + 1) % grad_accum == 0:
            used.append(scheduler.get_last_lr()[0])  # この更新で実際に使う lr
            param.grad = torch.zeros_like(param)
            optimizer.step()
            scheduler.step()
    return used


lrs = lr_series(BASE_LR, TOTAL, WARMUP_RATIO)

print(f"base_lr={BASE_LR:.1e} total_steps={TOTAL} warmup={WARMUP}\n")
print(f"{'step':>6}{'lr':>12}")
for step in (0, 1, WARMUP - 1, WARMUP, WARMUP + 1, TOTAL // 2, TOTAL - 1):
    print(f"{step:>6}{lrs[step]:>12.3e}")
print()

check("更新回数が step 数と一致する", len(lrs) == TOTAL, f"{len(lrs)} 回")
check("最初の step の lr は base_lr の 1/warmup",
      close(lrs[0], BASE_LR / WARMUP), f"{lrs[0]:.3e}")
check("warmup の終わりで base_lr に到達する",
      close(lrs[WARMUP - 1], BASE_LR), f"{lrs[WARMUP - 1]:.3e}")
check("warmup 区間は単調に増える",
      all(lrs[i] < lrs[i + 1] for i in range(WARMUP - 1)))
check("warmup 後は単調に減る",
      all(lrs[i] >= lrs[i + 1] for i in range(WARMUP - 1, TOTAL - 1)))
check("最後の step でも lr は 0 にならない",
      lrs[-1] > 0 and close(lrs[-1], BASE_LR / (TOTAL - WARMUP)), f"{lrs[-1]:.3e}")

# --- 勾配累積を入れるとスケジューラの進み方が変わる ------------------------
lrs_accum = lr_series(BASE_LR, TOTAL, WARMUP_RATIO, grad_accum=ACCUM)

print(f"\ngrad_accum={ACCUM} のとき（micro step は同じ {TOTAL} 回）")
print(f"  重みを更新した回数  : {len(lrs_accum)} 回")
print(f"  最後の更新に使う lr : {lrs_accum[-1]:.3e}")
print(f"  grad_accum=1 の終端 : {lrs[-1]:.3e}")
print(f"  比                  : {lrs_accum[-1] / lrs[-1]:.1f} 倍\n")

check("grad_accum を上げると更新回数が減る",
      len(lrs_accum) == TOTAL // ACCUM, f"{len(lrs_accum)} 回")
check("スケジューラが終端まで進まない（減衰しきらない）",
      lrs_accum[-1] > lrs[-1] * 10, f"{lrs_accum[-1] / lrs[-1]:.1f} 倍高いまま終わる")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nスケジューラの検証はすべて成功しました。")
