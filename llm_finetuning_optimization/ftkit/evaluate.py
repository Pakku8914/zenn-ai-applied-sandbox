"""評価（セッション9の参照実装）。

学習の成否を「loss が下がった」で判断してはいけない。
タスクの指標（分類の正解率・整形の遵守率）で測る。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import torch

from .data import CATEGORIES, Example, build_prompt

FORMAT_RE = re.compile(r"^【区分】(.+)\n【担当】(.+)\n【期限】(.+)$")


@dataclass
class EvalResult:
    n: int = 0
    correct: int = 0
    format_ok: int = 0
    predictions: list[tuple[str, str, str]] = field(default_factory=list)  # (id, 正解, 予測)

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0

    @property
    def format_rate(self) -> float:
        return self.format_ok / self.n if self.n else 0.0

    def summary(self) -> str:
        return f"n={self.n} 正解率={self.accuracy:.3f} 形式遵守率={self.format_rate:.3f}"

    def confusion(self) -> dict[str, dict[str, int]]:
        table = {c: {d: 0 for d in CATEGORIES + ["その他"]} for c in CATEGORIES}
        for _, gold, pred in self.predictions:
            key = pred if pred in CATEGORIES else "その他"
            if gold in table:
                table[gold][key] += 1
        return table


@torch.no_grad()
def generate(model, tokenizer, prompt: str, max_new_tokens: int = 24) -> str:
    messages = [{"role": "user", "content": prompt}]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt", add_special_tokens=False)
    model.eval()
    out = model.generate(
        **inputs, max_new_tokens=max_new_tokens, do_sample=False,  # 決定的にする
        pad_token_id=tokenizer.pad_token_id,
    )
    generated = out[0][inputs["input_ids"].shape[1] :]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def extract_category(text: str) -> str:
    """出力から区分名を取り出す。定型に従っていなくても拾えるようにする。"""
    match = FORMAT_RE.match(text.strip())
    if match:
        return match.group(1).strip()
    for category in CATEGORIES:
        if category in text:
            return category
    return text.strip().splitlines()[0][:12] if text.strip() else ""


def evaluate(model, tokenizer, examples: list[Example], task: str = "classify",
             limit: int | None = None) -> EvalResult:
    result = EvalResult()
    for example in examples[:limit] if limit else examples:
        output = generate(model, tokenizer, build_prompt(example, task),
                          max_new_tokens=12 if task == "classify" else 48)
        predicted = extract_category(output)
        result.n += 1
        result.correct += int(predicted == example.category)
        if task == "format":
            result.format_ok += int(bool(FORMAT_RE.match(output.strip())))
        else:
            result.format_ok += int(output.strip() in CATEGORIES)
        result.predictions.append((example.id, example.category, predicted))
    return result
