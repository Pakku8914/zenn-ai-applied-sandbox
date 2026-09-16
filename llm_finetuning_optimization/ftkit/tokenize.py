"""トークナイズと loss マスク（セッション4の主題）。

**プロンプト部分を学習させない**のが要点。プロンプトまで損失に含めると、
モデルは「指示文を覚える」ことに容量を使ってしまう。
"""

from __future__ import annotations

import torch

from .data import Example, build_prompt, build_target

IGNORE_INDEX = -100  # PyTorch の交差エントロピーが無視するラベル


def encode_example(tokenizer, example: Example, task: str = "classify",
                   max_length: int = 320) -> dict:
    """1件を (input_ids, labels, attention_mask) に変換する。

    labels のうちプロンプト部分を IGNORE_INDEX で埋めるのが loss マスク。

    **切り捨ての向きが重要**：素朴に `(prompt + answer)[:max_length]` とすると、
    プロンプトが長い場合に**回答が丸ごと消えて損失がゼロになる**（実際に踏んだ）。
    日本語を英語中心のトークナイザに通すとトークン数が膨らむため、
    短いテキストでも起きる。回答は必ず残し、足りない分はプロンプトの左から削る。
    """
    prompt_messages = [{"role": "user", "content": build_prompt(example, task)}]
    prompt_text = tokenizer.apply_chat_template(
        prompt_messages, tokenize=False, add_generation_prompt=True)
    answer_text = build_target(example, task) + (tokenizer.eos_token or "")

    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer(answer_text, add_special_tokens=False)["input_ids"]

    # 回答が単体で入らないほど max_length が小さい場合は設定ミスなので気づかせる
    if len(answer_ids) >= max_length:
        raise ValueError(
            f"max_length={max_length} が小さすぎます（回答だけで {len(answer_ids)} トークン）。"
            "max_length を増やしてください。"
        )
    budget = max_length - len(answer_ids)
    truncated = max(len(prompt_ids) - budget, 0)
    if truncated:
        prompt_ids = prompt_ids[-budget:]  # 左（指示文の先頭）から削る

    input_ids = prompt_ids + answer_ids
    labels = [IGNORE_INDEX] * len(prompt_ids) + answer_ids
    return {"input_ids": input_ids, "labels": labels,
            "attention_mask": [1] * len(input_ids), "truncated_prompt_tokens": truncated}


def token_report(tokenizer, example: Example, task: str = "classify") -> dict:
    """プロンプト・回答のトークン数を返す（トークナイザ比較に使う）。"""
    prompt_messages = [{"role": "user", "content": build_prompt(example, task)}]
    prompt_text = tokenizer.apply_chat_template(
        prompt_messages, tokenize=False, add_generation_prompt=True)
    answer_text = build_target(example, task) + (tokenizer.eos_token or "")
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer(answer_text, add_special_tokens=False)["input_ids"]
    return {"prompt_chars": len(prompt_text), "prompt_tokens": len(prompt_ids),
            "answer_chars": len(answer_text), "answer_tokens": len(answer_ids),
            "chars_per_token": len(prompt_text) / max(len(prompt_ids), 1)}


def collate(batch: list[dict], pad_token_id: int) -> dict:
    """右パディングでバッチにまとめる。パディング部分も loss から外す。"""
    max_len = max(len(row["input_ids"]) for row in batch)
    out = {"input_ids": [], "labels": [], "attention_mask": []}
    for row in batch:
        pad = max_len - len(row["input_ids"])
        out["input_ids"].append(row["input_ids"] + [pad_token_id] * pad)
        out["labels"].append(row["labels"] + [IGNORE_INDEX] * pad)
        out["attention_mask"].append(row["attention_mask"] + [0] * pad)
    return {k: torch.tensor(v, dtype=torch.long) for k, v in out.items()}


def masked_ratio(encoded: dict) -> float:
    """損失計算から外されているトークンの割合。loss マスクの効き方を可視化する。"""
    labels = encoded["labels"]
    total = len(labels)
    ignored = sum(1 for x in labels if x == IGNORE_INDEX)
    return ignored / total if total else 0.0
