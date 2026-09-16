"""valid が悪化したら止める学習ループ（セッション7で読者が補う「欠け」）。

`ftkit.train()` は早期終了しない。valid で悪化しても最後まで回りきる。
このモジュールは ftkit の部品（`encode_example` / `collate` / `TrainConfig`）を
そのまま使いながら、ループの側に次の3つを足したものである。

  1. 一定 step ごとに valid の平均 loss を測る
  2. 最良の評価点で学習対象パラメータのスナップショットを取る
  3. 最良から patience 回続けて改善しなければ止め、最良時点の重みに戻す

判定そのものは `should_stop()` という純関数に切り出してある。学習を回さずに
テストできるようにするため（診断のコードこそテストしやすく書く）。

  python src/session07/early_stop.py        # 単体で走らせると 135M で短いデモを回す
"""

from __future__ import annotations

import gc
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import Example  # noqa: E402
from ftkit.tokenize import collate, encode_example  # noqa: E402
from ftkit.train import TrainConfig, set_seed  # noqa: E402


@dataclass
class EarlyStopResult:
    """学習の結果と、止めた理由を後から読める形で残す。"""

    config: dict
    steps: int = 0
    seconds: float = 0.0
    train_losses: list[float] = field(default_factory=list)
    valid_history: list[tuple[int, float]] = field(default_factory=list)
    best_step: int = 0
    best_valid: float = float("inf")
    stopped_early: bool = False
    restored: bool = False
    fingerprint_before_restore: float = 0.0
    fingerprint_after_restore: float = 0.0

    def summary(self) -> str:
        tail = f"（最良 step {self.best_step} / valid {self.best_valid:.4f}）"
        reason = "早期終了" if self.stopped_early else "step 上限に到達"
        return (f"steps={self.steps} 所要={self.seconds:.1f}s {reason}{tail} "
                f"最良復元={'した' if self.restored else 'しなかった'}")


def make_batches(tokenizer, examples: list[Example], config: TrainConfig,
                 shuffle_seed: int | None = None) -> list[list[dict]]:
    """トークナイズしてバッチに束ねる。`ftkit.train()` と同じ手順にそろえてある。"""
    encoded = [encode_example(tokenizer, ex, config.task, config.max_length) for ex in examples]
    order = list(range(len(encoded)))
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(order)
    return [
        [encoded[i] for i in order[s : s + config.batch_size]]
        for s in range(0, len(order), config.batch_size)
    ]


@torch.no_grad()
def valid_loss(model, tokenizer, examples: list[Example], config: TrainConfig) -> float:
    """valid の平均 loss。止めるかどうかの判断に使う唯一の数字。

    `model.eval()` にするのは LoRA の dropout を切って測定を安定させるため。
    測り終わったら学習モードに戻す（戻し忘れると以降の学習が変わってしまう）。
    """
    was_training = model.training
    model.eval()
    batches = make_batches(tokenizer, examples, config)   # valid はシャッフルしない
    total = 0.0
    for batch in batches:
        inputs = collate(batch, tokenizer.pad_token_id)
        total += float(model(**inputs).loss)
    if was_training:
        model.train()
    return total / max(len(batches), 1)


def should_stop(valid_history: list[float], patience: int, min_delta: float = 0.0) -> bool:
    """最良の評価点から patience 回続けて改善しなければ True。

    - `min_delta` より小さい改善は「改善していない」とみなす（誤差で止めないため）
    - 評価回数が patience 以下のうちは絶対に止めない（初期の揺れで止めないため）
    - 同じ値が並んだ場合は最初の出現を最良とみなす（早めに止まる側に倒す）
    """
    if len(valid_history) <= patience:
        return False
    best = float("inf")
    best_index = 0
    for index, value in enumerate(valid_history):
        if value < best - min_delta:
            best, best_index = value, index
    return len(valid_history) - 1 - best_index >= patience


def trainable_snapshot(model) -> dict[str, torch.Tensor]:
    """学習対象のパラメータだけを複製する。LoRA なら数MBで済む。"""
    return {name: param.detach().clone()
            for name, param in model.named_parameters() if param.requires_grad}


def restore_snapshot(model, snapshot: dict[str, torch.Tensor]) -> None:
    with torch.no_grad():
        for name, param in model.named_parameters():
            if name in snapshot:
                param.copy_(snapshot[name])


def param_fingerprint(model) -> float:
    """学習対象パラメータの絶対値の総和。重みが入れ替わったかの確認に使う。"""
    return float(sum(param.detach().abs().sum()
                     for param in model.parameters() if param.requires_grad))


def train_with_early_stop(model, tokenizer, train_examples: list[Example],
                          valid_examples: list[Example], config: TrainConfig,
                          eval_every: int = 10, patience: int = 2,
                          min_delta: float = 0.0,
                          eval_fn: Callable[[int], float] | None = None) -> EarlyStopResult:
    """valid が悪化したら止める学習ループ。

    `eval_fn` を渡すと valid の測定をその関数で差し替える（判定の仕組みだけを
    テストしたいときに使う。実運用では None のまま）。
    """
    set_seed(config.seed)          # モデル構築の前にも呼んでおくこと（本章の 4 節）
    model.train()

    batches = make_batches(tokenizer, train_examples, config, shuffle_seed=config.seed)
    total_steps = len(batches) * config.epochs
    if config.max_steps:
        total_steps = min(total_steps, config.max_steps)

    params = [p for p in model.parameters() if p.requires_grad]
    if not params:
        raise ValueError("学習対象のパラメータが 0 個です（凍結されていないか確認してください）")
    optimizer = torch.optim.AdamW(params, lr=config.lr)
    warmup = max(int(total_steps * config.warmup_ratio), 1)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: min((step + 1) / warmup, 1.0)
        * max(0.0, 1.0 - max(step - warmup, 0) / max(total_steps - warmup, 1)),
    )

    result = EarlyStopResult(config=asdict(config))
    best_snapshot = trainable_snapshot(model)
    history: list[float] = []
    started = time.perf_counter()
    step = 0
    stop = False

    for _ in range(config.epochs):
        for batch in batches:
            if stop or (config.max_steps and step >= config.max_steps):
                stop = True
                break
            inputs = collate(batch, tokenizer.pad_token_id)
            loss = model(**inputs).loss / config.grad_accum
            loss.backward()
            if (step + 1) % config.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
            result.train_losses.append(float(loss.item()) * config.grad_accum)
            step += 1

            if step % eval_every == 0:
                current = eval_fn(step) if eval_fn else valid_loss(
                    model, tokenizer, valid_examples, config)
                history.append(current)
                result.valid_history.append((step, current))
                improved = current < result.best_valid - min_delta
                print(f"  step {step:>4}  train={result.train_losses[-1]:.4f}  "
                      f"valid={current:.4f}  {'改善' if improved else '非改善'}")
                if improved:
                    result.best_valid = current
                    result.best_step = step
                    best_snapshot = trainable_snapshot(model)
                if should_stop(history, patience, min_delta):
                    print(f"  早期終了：valid が {patience} 回続けて改善しませんでした")
                    result.stopped_early = True
                    stop = True
                    break
        if stop:
            break

    result.steps = step
    result.fingerprint_before_restore = param_fingerprint(model)
    if result.best_step and result.best_step != step:
        restore_snapshot(model, best_snapshot)
        result.restored = True
    result.fingerprint_after_restore = param_fingerprint(model)
    result.seconds = time.perf_counter() - started
    del best_snapshot
    gc.collect()
    return result


def _demo() -> None:
    """単体実行したときの短いデモ（135M / 12 step / valid 8 件）。"""
    from ftkit.data import load
    from ftkit.models import FAST_MODEL, attach_lora, load_model, load_tokenizer

    tokenizer = load_tokenizer(FAST_MODEL)
    config = TrainConfig(task="classify", batch_size=2, max_length=128,
                         max_steps=12, log_every=100, seed=20260815)
    set_seed(config.seed)                      # モデル構築の前に呼ぶ
    model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
    result = train_with_early_stop(model, tokenizer, load("train"), load("valid")[:8],
                                   config, eval_every=6, patience=2)
    print(result.summary())
    del model
    gc.collect()


if __name__ == "__main__":
    _demo()
