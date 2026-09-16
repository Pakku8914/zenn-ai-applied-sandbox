"""学習ループ（セッション5〜7の参照実装）。

Trainer を使わず素の PyTorch ループにしている。学習率・勾配累積・シードの効き方を
自分で触れるようにするため（フレームワークが隠すと診断が学べない）。
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch

from .data import Example
from .tokenize import collate, encode_example

RUNS = Path(__file__).resolve().parent.parent / "runs"


@dataclass
class TrainConfig:
    task: str = "classify"
    epochs: int = 1
    batch_size: int = 2
    grad_accum: int = 1
    lr: float = 2e-4
    max_length: int = 192
    seed: int = 20260815
    max_steps: int | None = None
    log_every: int = 10
    warmup_ratio: float = 0.1


@dataclass
class TrainResult:
    config: dict
    steps: int = 0
    seconds: float = 0.0
    losses: list[float] = field(default_factory=list)
    step_seconds: list[float] = field(default_factory=list)
    peak_rss_gb: float = 0.0

    @property
    def first_loss(self) -> float:
        return self.losses[0] if self.losses else float("nan")

    @property
    def last_loss(self) -> float:
        return self.losses[-1] if self.losses else float("nan")

    @property
    def median_step_seconds(self) -> float:
        if not self.step_seconds:
            return float("nan")
        s = sorted(self.step_seconds)
        return s[len(s) // 2]

    def save(self, name: str) -> Path:
        RUNS.mkdir(parents=True, exist_ok=True)
        path = RUNS / f"{name}.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def summary(self) -> str:
        return (f"steps={self.steps} 所要={self.seconds:.1f}s "
                f"中央値={self.median_step_seconds:.2f}s/step "
                f"loss {self.first_loss:.4f} -> {self.last_loss:.4f} "
                f"peak_rss={self.peak_rss_gb:.2f}GB")


def set_seed(seed: int) -> None:
    """再現性のために乱数を固定する。これを忘れると比較実験が成立しない。"""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def train(model, tokenizer, examples: list[Example], config: TrainConfig) -> TrainResult:
    import resource

    set_seed(config.seed)
    model.train()

    encoded = [encode_example(tokenizer, ex, config.task, config.max_length) for ex in examples]
    order = list(range(len(encoded)))
    random.Random(config.seed).shuffle(order)

    batches = [
        [encoded[i] for i in order[s : s + config.batch_size]]
        for s in range(0, len(order), config.batch_size)
    ]
    total_steps = len(batches) * config.epochs
    if config.max_steps:
        total_steps = min(total_steps, config.max_steps)

    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=config.lr)
    warmup = max(int(total_steps * config.warmup_ratio), 1)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: min((step + 1) / warmup, 1.0)
        * max(0.0, 1.0 - max(step - warmup, 0) / max(total_steps - warmup, 1)),
    )

    result = TrainResult(config=asdict(config))
    started = time.perf_counter()
    step = 0
    for _ in range(config.epochs):
        for batch in batches:
            if config.max_steps and step >= config.max_steps:
                break
            t0 = time.perf_counter()
            inputs = collate(batch, tokenizer.pad_token_id)
            loss = model(**inputs).loss / config.grad_accum
            loss.backward()
            if (step + 1) % config.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
            result.step_seconds.append(time.perf_counter() - t0)
            result.losses.append(float(loss.item()) * config.grad_accum)
            step += 1
            if step % config.log_every == 0:
                print(f"  step {step:>4}/{total_steps}  loss={result.losses[-1]:.4f}  "
                      f"lr={scheduler.get_last_lr()[0]:.2e}  "
                      f"{result.step_seconds[-1]:.2f}s")
        if config.max_steps and step >= config.max_steps:
            break

    result.steps = step
    result.seconds = time.perf_counter() - started
    result.peak_rss_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
    return result
